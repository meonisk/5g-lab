"""Prepare and collect bounded evidence for one explicit research design."""

from __future__ import annotations

import secrets
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .common import (
    RUN_ID_RE,
    SCHEMA_VERSION,
    checksum_tree,
    command,
    load_json,
    parse_env,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_json,
)
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
    run_dir = root / "local/evidence" / "runs" / run_id
    manifest_path = run_dir / "manifest.json"
    manifest = load_json(manifest_path)
    design = load_json(design_path)
    validate_design(design)
    if manifest["design"]["sha256"] != sha256_file(design_path):
        raise ValueError("design changed after prepare; create a new run")
    key = private_key_path(root, run_id).read_bytes()
    exact, _ = sensitive_values(root)
    redactor = Pseudonymizer(key, exact)
    gate_results = []
    gate_dir = run_dir / "shareable" / "gates"
    gate_dir.mkdir(parents=True, exist_ok=True)
    for gate in design["capture"].get("gates", []):
        gate_command = list(gate["command"])
        if gate_command[0] == "bash":
            windows_bash = Path("C:/Program Files/Git/bin/bash.exe")
            bash = str(windows_bash) if windows_bash.exists() else shutil.which("bash")
            gate_command[0] = bash or "bash"
        result = subprocess.run(
            gate_command,
            cwd=root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=float(parse_env(root / "app/config/lab.env")["RESEARCH_GATE_TIMEOUT_SECONDS"]),
        )
        output = result.stdout + (("\n" + result.stderr) if result.stderr else "")
        (gate_dir / f"{gate['id']}.log").write_text(redactor.text(output), encoding="utf-8")
        gate_results.append({"id": gate["id"], "returncode": result.returncode})
    write_json(run_dir / "shareable" / "gates.json", gate_results)
    containers, stats = docker_records(root, design["capture"]["compose_project"])
    write_json(run_dir / "shareable" / "containers.json", containers)
    write_json(
        run_dir / "shareable" / "resource-snapshot.json",
        {
            "observed_at_utc": utc_now(),
            "method": "docker stats --no-stream",
            "records": stats,
        },
    )
    known = {c["name"] for c in containers}
    captured = []
    for name in design["capture"]["containers"]:
        if name not in known:
            continue
        log = command(
            [
                "docker",
                "logs",
                "--tail",
                str(design["capture"]["log_tail_lines"]),
                name,
            ],
            root,
            required=False,
            timeout=60,
        )
        (run_dir / "shareable" / "logs" / f"{name}.log").write_text(
            redactor.text(log) + "\n", encoding="utf-8"
        )
        captured.append(name)
    manifest["collection_status"] = "COLLECTED"
    manifest["collected_at_utc"] = utc_now()
    manifest["capture"] = {
        "running_container_count": len(containers),
        "logs": captured,
        "gates": gate_results,
        "raw_audio_collected": False,
        "raw_payloads_collected": False,
    }
    write_json(manifest_path, manifest)
    checksum_tree(run_dir)
    print(f"COLLECTED {run_id}: {len(containers)} containers, {len(captured)} sanitized logs")
