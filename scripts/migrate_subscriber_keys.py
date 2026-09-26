"""Explicit, reversible migration from shared AKA keys to four UE/domain profiles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app/research/tools"))
sys.path.insert(0, str(ROOT / "scripts"))
from ims_research.execution import StandLock  # noqa: E402
from subscriber_key_backend import read_pyhss_rows  # noqa: E402

SECRET_PATH = ROOT / "local/secrets/ims.env"
PUBLIC_PATH = ROOT / "app/config/lab.env"
PRIVATE_ROOT = ROOT / "local/private"
CONTAINERS = ("lab-ue1", "lab-ue2", "lab-sipue1", "lab-sipue2")
MARKER = "__MIGRATION_JSON__"


def env_values(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def atomic_private(path: Path, content: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".migration-", dir=path.parent)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def private_json(path: Path, value: object) -> None:
    atomic_private(path, json.dumps(value, indent=2, sort_keys=True).encode())


def old_keys(secret: dict[str, str], ue: int, domain: str) -> dict[str, str]:
    prefix = f"UE{ue}_{domain}"
    names = (f"{prefix}_K", f"{prefix}_OPC", f"{prefix}_AMF")
    legacy = ("SUBSCRIBER_K", "SUBSCRIBER_OPC", "SUBSCRIBER_AMF")
    selected = names if any(name in secret for name in names) else legacy
    if any(not secret.get(name) for name in selected):
        raise RuntimeError(f"Incomplete source AKA profile for UE{ue} {domain}")
    return dict(zip(("k", "opc", "amf"), (secret[name] for name in selected), strict=True))


def matches(actual: dict, expected: dict, key_field: str = "k") -> bool:
    return all(
        str(actual.get(field, "")).lower() == expected[name].lower()
        for field, name in ((key_field, "k"), ("opc", "opc"), ("amf", "amf"))
    )


class Backend:
    def __init__(self, api_base: str):
        self.api_base = api_base.rstrip("/")
        self._db_rows = None

    def pyhss_rows(self, imsis: list[str]) -> dict:
        self._db_rows = read_pyhss_rows(imsis)
        return self._db_rows

    def stopped(self) -> None:
        for name in CONTAINERS:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Status}}", name],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            if result.returncode or result.stdout.strip() not in {"exited", "created"}:
                raise RuntimeError(f"Stop {name} before AKA migration")

    def mongo(self, operation: str, payload: dict) -> object:
        # Key material travels only through stdin, never Docker command arguments.
        encoded = json.dumps(json.dumps({"operation": operation, "payload": payload}))
        script = f"""
const request = JSON.parse({encoded});
const collection = db.getSiblingDB('open5gs').subscribers;
let result;
if (request.operation === 'read') {{
  result = collection.find({{imsi: {{$in: request.payload.imsis}}}},
    {{_id: 0, imsi: 1, security: 1}}).toArray();
}} else {{
  const p = request.payload;
  const update = request.operation === 'restore'
    ? {{$set: {{security: p.security}}}}
    : {{$set: {{'security.k': p.security.k, 'security.opc': p.security.opc,
               'security.amf': p.security.amf}}}};
  result = collection.updateOne({{imsi: p.imsi}}, update).matchedCount;
}}
print('{MARKER}' + JSON.stringify(result));
"""
        result = subprocess.run(
            ["docker", "exec", "-i", "lab-mongo", "mongosh", "--quiet", "--file", "/dev/stdin"],
            input=script,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if result.returncode:
            raise RuntimeError("Mongo operation failed")
        lines = [
            line[len(MARKER) :] for line in result.stdout.splitlines() if line.startswith(MARKER)
        ]
        if len(lines) != 1:
            raise RuntimeError("Mongo response was not parseable")
        return json.loads(lines[0])

    def auc(self, imsi: str, payload: dict | None = None, auc_id: int | None = None) -> dict:
        url = (
            f"{self.api_base}/auc/imsi/{imsi}"
            if payload is None
            else f"{self.api_base}/auc/{auc_id}"
        )
        request = urllib.request.Request(
            url,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="GET" if payload is None else "PATCH",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read()
            api_row = json.loads(body) if body else {}
            if payload is not None:
                return api_row
            if self._db_rows is None:
                raise RuntimeError("PyHSS database snapshot missing")
            matches = [row for row in self._db_rows["auc"] if row.get("imsi") == imsi]
            if len(matches) != 1:
                raise RuntimeError("PyHSS database AuC identity missing or duplicated")
            db_row = matches[0]
            if (
                str(api_row.get("auc_id")) != str(db_row["auc_id"])
                or api_row.get("imsi") != imsi
                or str(api_row.get("sqn")) != str(db_row["sqn"])
            ):
                raise RuntimeError("PyHSS API and database AuC state disagree")
            for field in ("ki", "opc", "amf"):
                if field in api_row and str(api_row[field]).lower() != str(db_row[field]).lower():
                    raise RuntimeError("PyHSS API and database AKA state disagree")
            return db_row
        except Exception as error:
            raise RuntimeError("PyHSS AuC request failed") from error

    def auc_inventory(self) -> list[dict]:
        rows = []
        for page in range(100):
            request = urllib.request.Request(f"{self.api_base}/auc/list?page={page}&page_size=200")
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    batch = json.load(response)
            except Exception as error:
                raise RuntimeError("PyHSS AuC inventory failed") from error
            if not isinstance(batch, list):
                raise RuntimeError("PyHSS AuC inventory is not a list")
            rows.extend(batch)
            if len(batch) < 200:
                return rows
        raise RuntimeError("PyHSS AuC inventory exceeded pagination bound")


def source_state(backend: Backend, public: dict, secret: dict) -> tuple[list[dict], list[dict]]:
    imsis = [public[f"UE{ue}_IMSI"] for ue in (1, 2)]
    if len(set(imsis)) != 2:
        raise RuntimeError("Two distinct UE IMSIs are required")
    mongo = backend.mongo("read", {"imsis": imsis})
    if len(mongo) != 2 or {row.get("imsi") for row in mongo} != set(imsis):
        raise RuntimeError("Expected exactly two Open5GS subscriber records")
    by_imsi = {row["imsi"]: row for row in mongo}
    mongo = [by_imsi[imsi] for imsi in imsis]
    db_rows = backend.pyhss_rows(imsis)
    auc = [backend.auc(imsi) for imsi in imsis]
    if len(db_rows["auc"]) != 2:
        raise RuntimeError("Expected exactly two target PyHSS AuC rows")
    subscribers = db_rows["subscriber"]
    ims_subscribers = db_rows["ims_subscriber"]
    for imsi, auc_row in zip(imsis, auc, strict=True):
        linked = [row for row in subscribers if row.get("imsi") == imsi]
        if len(linked) != 1 or str(linked[0].get("auc_id")) != str(auc_row["auc_id"]):
            raise RuntimeError(f"PyHSS subscriber-AuC link mismatch for IMSI {imsi}")
        if sum(str(row.get("auc_id")) == str(auc_row["auc_id"]) for row in subscribers) != 1:
            raise RuntimeError(f"PyHSS AuC shared by another subscriber for IMSI {imsi}")
        if sum(row.get("imsi") == imsi for row in ims_subscribers) != 1:
            raise RuntimeError(f"Expected exactly one IMS subscriber for IMSI {imsi}")
    inventory = backend.auc_inventory()
    for imsi in imsis:
        if sum(row.get("imsi") == imsi for row in inventory) != 1:
            raise RuntimeError(f"Expected exactly one PyHSS AuC record for IMSI {imsi}")
    if len({row.get("auc_id") for row in auc}) != 2:
        raise RuntimeError("Expected two distinct PyHSS AuC records")
    for index, ue in enumerate((1, 2)):
        if not matches(mongo[index].get("security", {}), old_keys(secret, ue, "5GS")):
            raise RuntimeError(f"Open5GS AKA source mismatch for UE{ue}")
        if auc[index].get("imsi") != imsis[index] or "sqn" not in auc[index]:
            raise RuntimeError(f"Incomplete PyHSS AuC source for UE{ue}")
        if not matches(auc[index], old_keys(secret, ue, "IMS"), "ki"):
            raise RuntimeError(f"PyHSS AKA source mismatch for UE{ue}")
    return mongo, auc


def stable_auc(rows: list[dict]) -> list[dict]:
    # PyHSS changes this metadata timestamp on PATCH; security fields and SQN
    # still participate in every comparison.
    return [{key: value for key, value in row.items() if key != "last_modified"} for row in rows]


def destination(secret: dict) -> dict[str, str]:
    if any(f"UE{ue}_{domain}_K" in secret for ue in (1, 2) for domain in ("5GS", "IMS")):
        raise RuntimeError("Per-UE destination already configured; refusing key rotation")
    result = dict(secret)
    used = {value.lower() for value in secret.values()}
    for ue in (1, 2):
        for domain in ("5GS", "IMS"):
            for suffix in ("K", "OPC"):
                value = secrets.token_hex(16).upper()
                while value.lower() in used:
                    value = secrets.token_hex(16).upper()
                result[f"UE{ue}_{domain}_{suffix}"] = value
                used.add(value.lower())
            result[f"UE{ue}_{domain}_AMF"] = old_keys(secret, ue, domain)["amf"]
    return result


def secret_bytes(original: bytes, target: dict[str, str]) -> bytes:
    added = [
        f"{key}={value}"
        for key, value in target.items()
        if key not in env_values_from_bytes(original)
    ]
    return original.rstrip(b"\n") + b"\n" + ("\n".join(added) + "\n").encode()


def env_values_from_bytes(content: bytes) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in content.decode().splitlines()
        if line and not line.startswith("#") and "=" in line
    )


def migrate(backend: Backend, backup_dir: Path, *, apply: bool, root: Path = ROOT) -> dict:
    public = env_values(root / "app/config/lab.env")
    secret_path = root / "local/secrets/ims.env"
    original = secret_path.read_bytes()
    secret = env_values_from_bytes(original)
    target = destination(secret)
    backend.stopped()
    mongo, auc = source_state(backend, public, secret)
    summary = {
        "imsis": [row["imsi"] for row in mongo],
        "source_hash": fingerprint(secret),
        "destination_hash": fingerprint(target),
    }
    if not apply:
        return summary

    private_root = (root / "local/private").resolve()
    resolved = backup_dir.resolve()
    if not resolved.is_relative_to(private_root) or resolved == private_root:
        raise RuntimeError("Backup destination must be a new path under local/private")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.mkdir(mode=0o700, exist_ok=False)
    atomic_private(resolved / "secrets.env", original)
    private_json(resolved / "mongo.json", mongo)
    private_json(resolved / "auc.json", auc)
    receipt = {**summary, "status": "backed_up"}
    private_json(resolved / "receipt.json", receipt)

    mutated = False
    try:
        backend.stopped()
        fresh_mongo, fresh_auc = source_state(backend, public, secret)
        if (
            fresh_mongo != mongo
            or stable_auc(fresh_auc) != stable_auc(auc)
            or secret_path.read_bytes() != original
        ):
            raise RuntimeError("Source changed after backup; no migration performed")
        for index, ue in enumerate((1, 2)):
            backend.stopped()
            imsi = mongo[index]["imsi"]
            security = old_keys(target, ue, "5GS")
            mutated = True
            if backend.mongo("set", {"imsi": imsi, "security": security}) != 1:
                raise RuntimeError("Open5GS update matched no subscriber")
            ims = old_keys(target, ue, "IMS")
            patch = {
                "imsi": imsi,
                "ki": ims["k"],
                "opc": ims["opc"],
                "amf": ims["amf"],
                "sqn": auc[index]["sqn"],
            }
            backend.auc(imsi, patch, auc[index]["auc_id"])
        backend.stopped()
        updated_mongo, updated_auc = source_state(backend, public, target)
        for before, after in zip(mongo, updated_mongo, strict=True):
            preserved_before = {
                key: value
                for key, value in before["security"].items()
                if key not in {"k", "opc", "amf"}
            }
            preserved_after = {
                key: value
                for key, value in after["security"].items()
                if key not in {"k", "opc", "amf"}
            }
            if preserved_before != preserved_after:
                raise RuntimeError("Open5GS security runtime state changed during migration")
        for before, after in zip(auc, updated_auc, strict=True):
            if before["sqn"] != after["sqn"]:
                raise RuntimeError("PyHSS SQN changed during migration")
        atomic_private(secret_path, secret_bytes(original, target))
        receipt["status"] = "applied"
        private_json(resolved / "receipt.json", receipt)
    except BaseException:
        rollback_errors = []
        if mutated:
            try:
                backend.stopped()
            except BaseException:
                rollback_errors.append("containers_running")
        if mutated and not rollback_errors:
            for row in mongo:
                try:
                    if backend.mongo("restore", row) != 1:
                        raise RuntimeError("restore matched no subscriber")
                except BaseException:
                    rollback_errors.append("Open5GS")
            for row in auc:
                try:
                    payload = {key: row[key] for key in ("imsi", "ki", "opc", "amf", "sqn")}
                    backend.auc(row["imsi"], payload, row["auc_id"])
                except BaseException:
                    rollback_errors.append("PyHSS")
        try:
            atomic_private(secret_path, original)
        except BaseException:
            rollback_errors.append("secrets")
        if mutated and not rollback_errors:
            try:
                restored_mongo, restored_auc = source_state(backend, public, secret)
                if (
                    restored_mongo != mongo
                    or stable_auc(restored_auc) != stable_auc(auc)
                    or secret_path.read_bytes() != original
                ):
                    raise RuntimeError("rollback readback mismatch")
            except BaseException:
                rollback_errors.append("readback")
        receipt["status"] = (
            "rollback_incomplete"
            if rollback_errors
            else "rolled_back"
            if mutated
            else "aborted_no_changes"
        )
        receipt["rollback_errors"] = rollback_errors
        private_json(resolved / "receipt.json", receipt)
        raise RuntimeError(f"Migration failed; {receipt['status']} (backup: {resolved})") from None
    return {**summary, "backup": str(resolved)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="perform migration after private backup"
    )
    parser.add_argument("--backup-dir", type=Path, help="new directory under local/private")
    args = parser.parse_args()
    if args.apply and args.backup_dir is None:
        parser.error("--apply requires --backup-dir")
    public = env_values(PUBLIC_PATH)
    api_base = f"http://{public['PYHSS_API_BIND']}:{public['PYHSS_API_PORT']}"
    try:
        with StandLock(ROOT):
            result = migrate(
                Backend(api_base), args.backup_dir or PRIVATE_ROOT / "unused", apply=args.apply
            )
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    print("AKA migration applied" if args.apply else "AKA migration dry run passed")
    print(f"Source hash: {result['source_hash']}; destination hash: {result['destination_hash']}")


if __name__ == "__main__":
    main()
