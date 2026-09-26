"""Shared file, hashing, process, and environment helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
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
TRANSCRIPT_CONTENT_RE = re.compile(r"(?i)(?:\btranscript\s*=|[\"']transcript[\"']\s*:)")
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
    # Replace only after the complete snapshot is durable; readers never see partial JSON.
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def command(args: list[str], cwd: Path, *, required: bool = True, timeout: int = 30) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    if required and result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr.strip()}"
        )
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


def checksum_tree(run_dir: Path) -> None:
    rows = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.relative_to(run_dir).as_posix() not in {
            "checksums.sha256",
            "validation.json",
        }:
            rows.append(f"{sha256_file(path)}  {path.relative_to(run_dir).as_posix()}")
    (run_dir / "checksums.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")
