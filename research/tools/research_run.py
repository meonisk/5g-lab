#!/usr/bin/env python3
"""Prepare, collect, and validate bounded IMS research evidence.

The default design is an instrumentation smoke test. This tool intentionally
does not promote admission/pilot output to a scientific result.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
IMSI_RE = re.compile(r"(?i)\b(?:imsi[-_: ]*)?\d{14,16}\b")
SIP_RE = re.compile(r"(?i)(sips?:)([^@;>\s]+)(@)")
CALL_ID_RE = re.compile(r"(?i)([\"']?call[_ -]?id[\"']?\s*[=:]\s*[\"']?)([A-Za-z0-9_.+~@-]{4,})")
CALL_LIST_RE = re.compile(r"(?i)([\"']?(?:calls|call_ids)[\"']?\s*[=:]\s*\[)([^\]]*)(\])")
RAW_CORRELATION_RE = re.compile(
    r"(?i)(?:[\"']?(?:calls|call_ids)[\"']?\s*[:=]\s*\[\s*[\"']?[A-Za-z0-9]|"
    r"[\"']?call_id[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9])"
)
SECRET_KEY_RE = re.compile(r"(?i)(?:^|_)(?:K|KI|OP|OPC|AMF|PASSWORD|PASS|SECRET|TOKEN|KEY)$")
IDENTITY_KEY_RE = re.compile(r"(?i)(?:IMSI|MSISDN|SUPI|SIP_USER)$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def command(args: list[str], cwd: Path, *, required: bool = True, timeout: int = 30) -> str:
    result = subprocess.run(args, cwd=cwd, text=True, encoding="utf-8", errors="replace",
                            capture_output=True, timeout=timeout)
    if required and result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def validate_design(design: dict[str, Any]) -> None:
    required = {"schema_version", "design_id", "design_status", "stage", "evidence_class",
                "scientific_claim_allowed", "purpose", "capture", "privacy"}
    missing = sorted(required - design.keys())
    if missing:
        raise ValueError(f"design missing fields: {', '.join(missing)}")
    if design["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported design schema_version")
    if design["stage"] not in {"ADMISSION", "PILOT", "MAIN", "CLOSED_ANALYSIS"}:
        raise ValueError("executable design has invalid stage")
    if design["stage"] in {"ADMISSION", "PILOT"} and design["scientific_claim_allowed"]:
        raise ValueError("admission/pilot designs cannot allow scientific claims")
    if design["stage"] == "MAIN":
        if design["design_status"] != "FROZEN_FOR_MAIN":
            raise ValueError("MAIN requires design_status=FROZEN_FOR_MAIN")
        if int(design.get("repetitions", 0)) < 2:
            raise ValueError("MAIN requires a frozen repetition count greater than one")
    privacy = design["privacy"]
    if privacy.get("raw_audio") != "FORBIDDEN" or privacy.get("raw_payloads") != "FORBIDDEN":
        raise ValueError("the v1 harness only permits designs that forbid raw audio and payloads")


def git_snapshot(root: Path) -> dict[str, Any]:
    commit = command(["git", "rev-parse", "HEAD"], root)
    status = command(["git", "status", "--porcelain=v1"], root)
    diff = command(["git", "diff", "--binary", "HEAD"], root)
    return {
        "commit": commit,
        "dirty": bool(status),
        "status_sha256": sha256_bytes(status.encode()),
        "diff_sha256": sha256_bytes(diff.encode()),
    }


def host_snapshot(root: Path) -> dict[str, Any]:
    ps = (
        "$c=Get-CimInstance Win32_Processor|Select-Object -First 1 Name,NumberOfCores,NumberOfLogicalProcessors;"
        "$s=Get-CimInstance Win32_ComputerSystem;"
        "$g=Get-CimInstance Win32_VideoController|Select-Object Name,DriverVersion;"
        "[pscustomobject]@{cpu=$c;memory_bytes=[int64]$s.TotalPhysicalMemory;gpus=@($g)}|ConvertTo-Json -Depth 4 -Compress"
    )
    raw = command(["powershell", "-NoProfile", "-Command", ps], root, required=False)
    try:
        hw = json.loads(raw)
    except json.JSONDecodeError:
        hw = {"cpu": {"Name": platform.processor()}, "memory_bytes": 0, "gpus": []}
    nvidia = command(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                      "--format=csv,noheader,nounits"], root, required=False)
    if nvidia:
        parsed_gpus = []
        for line in nvidia.splitlines():
            fields = [part.strip() for part in line.split(",")]
            if len(fields) == 3:
                parsed_gpus.append({"name": fields[0], "memory_mib": int(fields[1]),
                                    "driver_version": fields[2], "source": "nvidia-smi"})
        if parsed_gpus:
            hw["gpus"] = parsed_gpus
    return {
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu": hw.get("cpu", {}),
        "memory_bytes": hw.get("memory_bytes", 0),
        "gpus": hw.get("gpus", []),
        "timezone": datetime.now().astimezone().tzname(),
        "clock": "host UTC wall clock; cross-host uncertainty not measured in this profile",
    }


def input_hashes(root: Path, design_path: Path) -> list[dict[str, str]]:
    paths = [design_path, root / "lab.env", root / "docker-compose.yml"]
    paths.extend(root / p for p in (
        "services/ai-worker/worker.py", "services/media-adapter/adapter.py",
        "services/sip-as/server.py", "services/voice-agent/agent.py",
        "research/tools/research_run.py", "research/schemas/run-manifest.schema.json",
        "research/schemas/metric-record.schema.json"))
    return [{"path": str(p.relative_to(root)).replace("\\", "/"), "sha256": sha256_file(p)}
            for p in paths if p.is_file()]


class Pseudonymizer:
    def __init__(self, key: bytes, exact: dict[str, str]):
        self.key = key
        self.exact = {v: self.alias(k.lower(), v) for k, v in exact.items() if len(v) >= 4}

    def alias(self, kind: str, value: str) -> str:
        digest = hmac.new(self.key, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:12]
        return f"<{kind}:{digest}>"

    def text(self, value: str) -> str:
        for raw in sorted(self.exact, key=len, reverse=True):
            value = value.replace(raw, self.exact[raw])
        value = IMSI_RE.sub(lambda m: self.alias("subscriber", m.group(0)), value)
        value = SIP_RE.sub(lambda m: m.group(1) + self.alias("sip-user", m.group(2)) + m.group(3), value)
        value = CALL_ID_RE.sub(lambda m: m.group(1) + self.alias("call-id", m.group(2)), value)
        value = CALL_LIST_RE.sub(self._call_list, value)
        return value

    def _call_list(self, match: re.Match[str]) -> str:
        body = re.sub(r"[A-Za-z0-9_.+~@-]{4,}",
                      lambda m: self.alias("call-id", m.group(0)), match.group(2))
        return match.group(1) + body + match.group(3)


def private_key_path(root: Path, run_id: str) -> Path:
    return root / "evidence" / "private" / f"{run_id}.pseudonym.key"


def prepare(root: Path, design_path: Path, requested_id: str | None) -> str:
    design = load_json(design_path)
    validate_design(design)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = requested_id or f"{stamp}-{design['design_id']}-{uuid.uuid4().hex[:8]}"
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run id contains unsupported characters")
    run_dir = root / "evidence" / "runs" / run_id
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
        "design": {"id": design["design_id"], "status": design["design_status"],
                   "path": str(design_path.relative_to(root)).replace("\\", "/"),
                   "sha256": sha256_file(design_path)},
        "repository": git_snapshot(root),
        "host": host_snapshot(root),
        "inputs": input_hashes(root, design_path),
        "privacy": {**design["privacy"], "pseudonym_key_id": sha256_bytes(key)[:16],
                    "pseudonym_scope": "within-run", "key_in_shareable_artifacts": False},
    }
    write_json(run_dir / "manifest.json", manifest)
    (run_dir / "README.txt").write_text(
        "This run is labelled instrumentation evidence. Review manifest.json and shareable/; "
        "never distribute the separate evidence/private pseudonym key.\n", encoding="utf-8")
    print(run_id)
    return run_id


def docker_records(root: Path, project: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ids = command(["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={project}"], root)
    containers: list[dict[str, Any]] = []
    if ids:
        inspected = json.loads(command(["docker", "inspect", *ids.splitlines()], root, timeout=60))
        for item in inspected:
            labels = item.get("Config", {}).get("Labels", {}) or {}
            containers.append({
                "name": item.get("Name", "").lstrip("/"),
                "service": labels.get("com.docker.compose.service"),
                "image_reference": item.get("Config", {}).get("Image"),
                "image_id": item.get("Image"),
                "state": item.get("State", {}).get("Status"),
                "started_at": item.get("State", {}).get("StartedAt"),
            })
    stats: list[dict[str, Any]] = []
    raw_stats = command(["docker", "stats", "--no-stream", "--format", "{{json .}}",
                         *[c["name"] for c in containers]], root, required=False, timeout=60)
    for line in raw_stats.splitlines():
        try:
            stats.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return containers, stats


def sensitive_values(root: Path) -> tuple[dict[str, str], list[str]]:
    exact: dict[str, str] = {}
    secrets_for_scan: list[str] = []
    for path in (root / "lab.env", root / "secrets" / "ims.env"):
        for key, value in parse_env(path).items():
            if IDENTITY_KEY_RE.search(key):
                exact[key] = value
            if SECRET_KEY_RE.search(key) and len(value) >= 8:
                exact[key] = value
                secrets_for_scan.append(value)
    return exact, secrets_for_scan


def checksum_tree(run_dir: Path) -> None:
    rows = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name != "checksums.sha256":
            rows.append(f"{sha256_file(path)}  {path.relative_to(run_dir).as_posix()}")
    (run_dir / "checksums.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")


def collect(root: Path, design_path: Path, run_id: str) -> None:
    run_dir = root / "evidence" / "runs" / run_id
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
        result = subprocess.run(gate_command, cwd=root, text=True, encoding="utf-8", errors="replace",
                                capture_output=True, timeout=300)
        output = result.stdout + (("\n" + result.stderr) if result.stderr else "")
        (gate_dir / f"{gate['id']}.log").write_text(redactor.text(output), encoding="utf-8")
        gate_results.append({"id": gate["id"], "returncode": result.returncode})
    write_json(run_dir / "shareable" / "gates.json", gate_results)
    containers, stats = docker_records(root, design["capture"]["compose_project"])
    write_json(run_dir / "shareable" / "containers.json", containers)
    write_json(run_dir / "shareable" / "resource-snapshot.json",
               {"observed_at_utc": utc_now(), "method": "docker stats --no-stream", "records": stats})
    known = {c["name"] for c in containers}
    captured = []
    for name in design["capture"]["containers"]:
        if name not in known:
            continue
        log = command(["docker", "logs", "--tail", str(design["capture"]["log_tail_lines"]), name],
                      root, required=False, timeout=60)
        (run_dir / "shareable" / "logs" / f"{name}.log").write_text(redactor.text(log) + "\n", encoding="utf-8")
        captured.append(name)
    manifest["collection_status"] = "COLLECTED"
    manifest["collected_at_utc"] = utc_now()
    manifest["capture"] = {"running_container_count": len(containers), "logs": captured,
                           "gates": gate_results, "raw_audio_collected": False,
                           "raw_payloads_collected": False}
    write_json(manifest_path, manifest)
    checksum_tree(run_dir)
    print(f"COLLECTED {run_id}: {len(containers)} containers, {len(captured)} sanitized logs")


def validate(root: Path, design_path: Path, run_id: str) -> None:
    run_dir = root / "evidence" / "runs" / run_id
    manifest = load_json(run_dir / "manifest.json")
    design = load_json(design_path)
    validate_design(design)
    errors: list[str] = []
    for field in ("schema_version", "run_id", "created_at_utc", "stage", "evidence_class",
                  "scientific_claim_allowed", "design", "repository", "host", "privacy"):
        if field not in manifest:
            errors.append(f"manifest missing {field}")
    if manifest.get("collection_status") != "COLLECTED":
        errors.append("run has not been collected")
    gates = manifest.get("capture", {}).get("gates", [])
    expected_gates = design.get("capture", {}).get("gates", [])
    if len(gates) != len(expected_gates):
        errors.append("required admission gates were not all captured")
    for gate in gates:
        if gate.get("returncode") != 0:
            errors.append(f"admission gate failed: {gate.get('id')}")
    if manifest.get("design", {}).get("sha256") != sha256_file(design_path):
        errors.append("design hash mismatch")
    checksum_path = run_dir / "checksums.sha256"
    if not checksum_path.exists():
        errors.append("checksums missing")
    else:
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            expected, relative = line.split("  ", 1)
            path = run_dir / Path(relative)
            if not path.is_file() or sha256_file(path) != expected:
                errors.append(f"checksum mismatch: {relative}")
    _, secret_values = sensitive_values(root)
    shareable_files = [p for p in (run_dir / "shareable").rglob("*") if p.is_file()]
    shareable_files.append(run_dir / "manifest.json")
    for path in shareable_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if IMSI_RE.search(text):
            errors.append(f"direct subscriber identifier in {path.relative_to(run_dir)}")
        if RAW_CORRELATION_RE.search(text):
            errors.append(f"unprotected call correlation id in {path.relative_to(run_dir)}")
        if any(secret in text for secret in secret_values):
            errors.append(f"secret value in {path.relative_to(run_dir)}")
    if manifest.get("stage") in {"ADMISSION", "PILOT"} and manifest.get("scientific_claim_allowed"):
        errors.append("admission/pilot run incorrectly permits a scientific claim")
    report = {"schema_version": SCHEMA_VERSION, "run_id": run_id, "validated_at_utc": utc_now(),
              "status": "FAIL" if errors else "PASS", "errors": errors,
              "claim_boundary": manifest.get("claim_boundary")}
    write_json(run_dir / "validation.json", report)
    if errors:
        raise RuntimeError("RESEARCH READINESS: FAIL\n- " + "\n- ".join(errors))
    print("RESEARCH READINESS: PASS (instrumentation only; not a scientific outcome)")


def verify(root: Path) -> None:
    smoke = root / "research" / "designs" / "local-instrumentation-smoke-v1.json"
    candidate = load_json(root / "research" / "designs" / "ai-scale-study-v1.json")
    design = load_json(smoke)
    validate_design(design)
    if candidate.get("design_status") != "DRAFT_REQUIRES_PILOT_FREEZE":
        raise ValueError("AI scale candidate must remain explicitly unfrozen")
    for schema in ("run-manifest.schema.json", "metric-record.schema.json"):
        load_json(root / "research" / "schemas" / schema)
    key = b"x" * 32
    raw_identity = "999990000000001"
    raw_secret = "0123456789ABCDEF0123456789ABCDEF"
    p = Pseudonymizer(key, {"UE1_IMSI": raw_identity, "SUBSCRIBER_K": raw_secret})
    first = p.text(f"imsi-{raw_identity} call-id=abcde calls=['fghij'] secret={raw_secret}")
    second = p.text(f"subscriber {raw_identity}")
    if raw_identity in first + second or raw_secret in first or first.count("<ue1_imsi:") != 1:
        raise AssertionError("pseudonymization self-test failed")
    if p.alias("ue1_imsi", raw_identity) not in second:
        raise AssertionError("pseudonyms are not stable within a run")
    if "fghij" in first:
        raise AssertionError("call-list correlation identifiers were not pseudonymized")
    print("RESEARCH TOOLING OFFLINE VALIDATION: PASS")
    print("AI scale design status: DRAFT_REQUIRES_PILOT_FREEZE (correctly not a result)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "collect", "validate", "verify"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--design", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    root = args.root.resolve()
    design = (args.design or root / "research" / "designs" / "local-instrumentation-smoke-v1.json").resolve()
    try:
        if args.command == "prepare":
            prepare(root, design, args.run_id)
        elif args.command == "collect":
            if not args.run_id:
                parser.error("collect requires --run-id")
            collect(root, design, args.run_id)
        elif args.command == "validate":
            if not args.run_id:
                parser.error("validate requires --run-id")
            validate(root, design, args.run_id)
        else:
            verify(root)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
