"""Check that the complete evidence tree is bound by its checksum inventory."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .common import sha256_file

HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
EXCLUDED = {"checksums.sha256", "validation.json"}


def artifact_errors(run_dir: Path, design: dict[str, Any], capture: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    checksum_path = run_dir / "checksums.sha256"
    if not checksum_path.is_file():
        return ["checksums missing"]

    listed: dict[str, str] = {}
    for number, line in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), 1):
        if "  " not in line:
            errors.append(f"malformed checksum row {number}")
            continue
        digest, relative = line.split("  ", 1)
        posix = PurePosixPath(relative)
        if (
            not HASH_RE.fullmatch(digest)
            or not relative
            or "\\" in relative
            or ":" in relative
            or posix.is_absolute()
            or any(part in (".", "..") for part in relative.split("/"))
            or relative in EXCLUDED
        ):
            errors.append(f"unsafe checksum row {number}")
            continue
        if relative in listed:
            errors.append(f"duplicate checksum path: {relative}")
            continue
        listed[relative] = digest

    actual = {
        path.relative_to(run_dir).as_posix(): path
        for path in run_dir.rglob("*")
        if path.is_file() and path.relative_to(run_dir).as_posix() not in EXCLUDED
    }
    required = {"manifest.json", "shareable/gates.json"}
    required.update(f"shareable/gates/{gate['id']}.log" for gate in design["capture"]["gates"])
    required.update(f"shareable/logs/{name}.log" for name in design["capture"]["containers"])
    for relative in sorted(required - actual.keys()):
        errors.append(f"required artifact missing: {relative}")
    for relative in sorted(actual.keys() - listed.keys()):
        errors.append(f"artifact not hashed: {relative}")
    for relative in sorted(listed.keys() - actual.keys()):
        errors.append(f"checksum path missing: {relative}")
    for relative in sorted(actual.keys() & listed.keys()):
        path = actual[relative]
        if (
            not path.resolve().is_relative_to(run_dir.resolve())
            or sha256_file(path) != listed[relative]
        ):
            errors.append(f"checksum mismatch: {relative}")

    gates_path = run_dir / "shareable/gates.json"
    if gates_path.is_file():
        try:
            gate_file = json.loads(gates_path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            errors.append("gates.json malformed")
        else:
            if gate_file != capture.get("gates"):
                errors.append("gates.json differs from manifest capture.gates")
    return errors
