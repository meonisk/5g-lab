"""Temporarily select the no-AS PyHSS iFC for two existing IMS subscribers.

The caller owns the exclusive stand lock, registration refresh, and call cleanup.
This context changes only ifc_path and keeps a private restoration journal.
"""

import json
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import ims_readiness  # noqa: E402

TEMPLATE = ROOT / "app/infrastructure/configs/pyhss/baseline_ifc.xml"
PROFILE = "baseline_ifc.xml"
connected_hss_peer = ims_readiness.connected_hss_peer
wait_ims_peers = ims_readiness.wait_ims_peers


@dataclass
class ProfileState:
    journal: Path
    rollback_ok: bool | None = None


def api_json(base, path, *, method="GET", payload=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json"} if body else {},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        data = response.read()
    return json.loads(data) if data else None


def subscriber_rows(base, imsis):
    rows = api_json(base, "/ims_subscriber/list?page=0&page_size=200")
    if not isinstance(rows, list):
        raise RuntimeError("PyHSS IMS subscriber list has unexpected shape")
    selected = []
    for imsi in imsis:
        matches = [row for row in rows if row.get("imsi") == imsi]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one IMS subscriber for {imsi}; found {len(matches)}")
        row = matches[0]
        if "ims_subscriber_id" not in row or not row.get("ifc_path"):
            raise RuntimeError("IMS subscriber lacks id or current ifc_path")
        selected.append({"id": row["ims_subscriber_id"], "ifc_path": row["ifc_path"]})
    return selected


def write_journal(path, rows, status):
    payload = {"rows": rows, "rollback_status": status}
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def select_ifc(base, subscriber_id, ifc_path):
    api_json(
        base, f"/ims_subscriber/{subscriber_id}", method="PATCH", payload={"ifc_path": ifc_path}
    )
    rows = api_json(base, "/ims_subscriber/list?page=0&page_size=200")
    matches = [row for row in rows if row.get("ims_subscriber_id") == subscriber_id]
    if len(matches) != 1 or matches[0].get("ifc_path") != ifc_path:
        raise RuntimeError(f"PyHSS did not retain ifc_path for id={subscriber_id}")


def check_template():
    root = ET.parse(TEMPLATE).getroot()
    if root.tag != "IMSSubscription" or root.findall(".//InitialFilterCriteria"):
        raise RuntimeError("Baseline iFC must preserve IMSSubscription without AS triggers")
    if len(root.findall(".//PublicIdentity")) != 3:
        raise RuntimeError("Baseline iFC must retain all three public identities")


@contextmanager
def baseline_ifc(settings, run_dir):
    """Yield state; restore both old paths even after partial patch failure."""
    imsis = (settings["UE1_IMSI"], settings["UE2_IMSI"])
    if imsis[0] == imsis[1]:
        raise RuntimeError("Baseline requires two distinct IMS subscribers")
    base = settings.get("PYHSS_API_BASE") or (
        f"http://{settings['PYHSS_API_BIND']}:{settings['PYHSS_API_PORT']}"
    )
    run_dir = Path(run_dir).resolve()
    if not run_dir.is_relative_to((ROOT / "local/private").resolve()):
        raise RuntimeError("Baseline profile journal must remain under local/private")
    run_dir.mkdir(parents=True, exist_ok=True)
    journal = run_dir / "baseline-ifc-journal.json"
    if journal.exists():
        raise RuntimeError("Baseline iFC journal already exists")
    check_template()
    rows = subscriber_rows(base, imsis)
    state = ProfileState(journal)
    write_journal(journal, rows, "PENDING")
    try:
        subprocess.run(
            ["docker", "cp", str(TEMPLATE), f"lab-pyhss:/pyhss/{PROFILE}"],
            check=True,
        )
        for row in rows:
            select_ifc(base, row["id"], PROFILE)
        yield state
    finally:
        failures = []
        for row in rows:
            try:
                select_ifc(base, row["id"], row["ifc_path"])
            except Exception as error:
                failures.append(f"id={row['id']}: {type(error).__name__}")
        state.rollback_ok = not failures
        write_journal(journal, rows, "RESTORED" if state.rollback_ok else "RESTORE_FAILED")
        if failures:
            raise RuntimeError("Baseline iFC restore failed: " + ", ".join(failures))
