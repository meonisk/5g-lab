"""Prepare and collect bounded evidence for one explicit research design."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .common import (
    RUN_ID_RE,
    SCHEMA_VERSION,
    checksum_tree,
    load_json,
    parse_env,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_json,
)
from .execution import StandLock, run_gate
from .inventory import docker_records, git_snapshot, host_snapshot, input_hashes
from .privacy import Pseudonymizer, private_key_path, sensitive_values
from .validation import validate_design


def prepare(root: Path, design_path: Path, requested_id: str | None) -> str:
    design = load_json(design_path)
    validate_design(design)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = requested_id or f"{stamp}-{design['design_id']}-{uuid.uuid4().hex[:8]}"
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run id contains unsupported characters")
    run_dir = root / "local/evidence" / "runs" / run_id
    if run_dir.exists():
        raise FileExistsError(f"run already exists: {run_id}")
    (run_dir / "shareable" / "logs").mkdir(parents=True)
    key_path = private_key_path(root, run_id)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    key_path.write_bytes(key)
    try:
        key_path.chmod(0o600)
    except OSError:
        pass
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at_utc": utc_now(),
        "collection_status": "PREPARED",
        "stage": design["stage"],
        "evidence_class": design["evidence_class"],
        "scientific_claim_allowed": bool(design["scientific_claim_allowed"]),
        "claim_boundary": "Instrumentation evidence only; not a scientific AI performance result.",
        "design": {
            "id": design["design_id"],
            "status": design["design_status"],
            "path": str(design_path.relative_to(root)).replace("\\", "/"),
            "sha256": sha256_file(design_path),
        },
        "repository": git_snapshot(root),
        "host": host_snapshot(root),
        "inputs": input_hashes(root, design_path),
        "privacy": {
            **design["privacy"],
            "pseudonym_key_id": sha256_bytes(key)[:16],
            "pseudonym_scope": "within-run",
            "key_in_shareable_artifacts": False,
        },
    }
    write_json(run_dir / "manifest.json", manifest)
    (run_dir / "README.txt").write_text(
        "This run is labelled instrumentation evidence. Review manifest.json and shareable/; "
        "never distribute the separate local/evidence/private pseudonym key.\n",
        encoding="utf-8",
    )
    print(run_id)
    return run_id


def collect(root: Path, design_path: Path, run_id: str) -> None:
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run id contains unsupported characters")
    with StandLock(root):
        _collect_locked(root, design_path, run_id)


def _collect_locked(root: Path, design_path: Path, run_id: str) -> None:
    run_dir = root / "local/evidence" / "runs" / run_id
    manifest_path = run_dir / "manifest.json"
    manifest = load_json(manifest_path)
    if manifest.get("collection_status") != "PREPARED":
        raise ValueError("attempt already started; preserve its evidence and prepare a new run")
    design = load_json(design_path)
    validate_design(design)
    if manifest["design"]["sha256"] != sha256_file(design_path):
        raise ValueError("design changed after prepare; create a new run")
    timeout = float(parse_env(root / "app/config/lab.env")["RESEARCH_GATE_TIMEOUT_SECONDS"])
    if not 0 < timeout < float("inf"):
        raise ValueError("gate timeout must be finite and positive")
    key = private_key_path(root, run_id).read_bytes()
    exact, _ = sensitive_values(root)
    redactor = Pseudonymizer(key, exact)
    gates = [
        {"id": gate["id"], "status": "NOT_TESTED", "returncode": None}
        for gate in design["capture"].get("gates", [])
    ]
    manifest.update(collection_status="COLLECTING", collection_started_at_utc=utc_now())
    manifest["capture"] = {
        "gates": gates,
        "logs": [],
        "raw_audio_collected": False,
        "raw_payloads_collected": False,
    }
    gate_dir = run_dir / "shareable/gates"
    gate_dir.mkdir(parents=True, exist_ok=True)

    def checkpoint():
        event = {
            "at_utc": utc_now(),
            "collection_status": manifest["collection_status"],
            "gates": gates,
        }
        with (run_dir / "shareable/execution.jsonl").open("a", encoding="utf-8") as journal:
            journal.write(json.dumps(event) + "\n")
            journal.flush()
            os.fsync(journal.fileno())
        write_json(run_dir / "shareable/gates.json", gates)
        write_json(manifest_path, manifest)

    checkpoint()
    try:
        before, _ = docker_records(root, design["capture"]["compose_project"])
        write_json(run_dir / "shareable/containers-pre.json", before)
        for index, gate in enumerate(design["capture"].get("gates", [])):
            gates[index]["status"] = "RUNNING"
            checkpoint()
            result, output = run_gate(root, gate, timeout)
            (gate_dir / f"{gate['id']}.log").write_text(
                redactor.shareable_log(output, source=gate["id"]), encoding="utf-8"
            )
            gates[index] = result
            checkpoint()
            if result["status"] != "COMPLETED" or result["returncode"] != 0:
                # Later gates may create calls on an invalid baseline or failed cleanup.
                raise RuntimeError(f"gate did not complete successfully: {gate['id']}")
        manifest["collection_status"] = "COLLECTED"
    except BaseException as exc:
        for gate in gates:
            if gate["status"] == "RUNNING":
                gate.update(
                    status="INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "ERROR",
                    finished_at_utc=utc_now(),
                )
        manifest["collection_status"] = "FAILED"
        raise
    finally:
        try:
            _capture_logs(root, run_dir, design, manifest, redactor)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            manifest["capture"]["post_capture_error"] = type(exc).__name__
            manifest["collection_status"] = "FAILED"
        manifest["collected_at_utc"] = utc_now()
        checkpoint()
        checksum_tree(run_dir)
    if manifest["collection_status"] != "COLLECTED":
        raise RuntimeError("required post-capture failed; inspect the preserved attempt")
    print(f"COLLECTED {run_id}: {len(manifest['capture']['logs'])} sanitized logs")


def _capture_logs(root, run_dir, design, manifest, redactor):
    containers, stats = docker_records(root, design["capture"]["compose_project"])
    write_json(run_dir / "shareable/containers.json", containers)
    write_json(
        run_dir / "shareable/resource-snapshot.json",
        {
            "observed_at_utc": utc_now(),
            "method": "docker stats --no-stream",
            "records": stats,
        },
    )
    known = {c["name"] for c in containers}
    manifest["capture"]["running_container_count"] = sum(
        c["state"] == "running" for c in containers
    )
    missing = sorted(set(design["capture"]["containers"]) - known)
    manifest["capture"]["missing_containers"] = missing
    for name in design["capture"]["containers"]:
        if name not in known:
            continue
        result = subprocess.run(
            [
                "docker",
                "logs",
                "--since",
                manifest["collection_started_at_utc"],
                "--tail",
                str(design["capture"]["log_tail_lines"]),
                name,
            ],
            cwd=root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=60,
            check=True,
        )
        log = result.stdout + ("\n" + result.stderr if result.stderr else "")
        (run_dir / "shareable/logs" / f"{name}.log").write_text(
            redactor.shareable_log(log, source=name) + "\n", encoding="utf-8"
        )
        manifest["capture"]["logs"].append(name)
    manifest["capture"]["log_capture"] = "since-start, bounded tail; completeness not asserted"
    if missing:
        raise RuntimeError("required container evidence missing: " + ", ".join(missing))
