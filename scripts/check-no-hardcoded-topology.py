#!/usr/bin/env python3
"""Reject topology/identity literals outside the canonical env files."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    re.compile(r"\b(?:172\.22|10\.45|10\.46)\.\d{1,3}(?:\.\d{1,3})?(?:/\d+)?\b"),
    re.compile(r"\b00101000000000[12]\b"),
    re.compile(r"\bims\.mnc001\.mcc001\.3gppnetwork\.org\b"),
)
# Validate private values without ever embedding them in source or diagnostics.
secret_path = ROOT / "local/secrets/ims.env"
if secret_path.exists():
    private_values = [
        line.split("=", 1)[1].strip()
        for line in secret_path.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.startswith("#")
    ]
    PATTERNS += tuple(re.compile(re.escape(value)) for value in private_values if len(value) >= 16)

SUFFIXES = {".sh", ".py", ".ps1", ".js", ".yaml", ".yml"}
ALLOWED = {
    ROOT / "app/config/lab.env",
    ROOT / "local/secrets" / "ims.env",
    Path(__file__).resolve(),
}

violations: list[str] = []
for path in ROOT.rglob("*"):
    if (
        not path.is_file()
        or path.suffix not in SUFFIXES
        or {"vendor", "local", ".venv", ".git"}.intersection(path.relative_to(ROOT).parts)
    ):
        continue
    if path in ALLOWED:
        continue
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("#", "//")):
            continue
        if any(pattern.search(line) for pattern in PATTERNS):
            violations.append(
                f"{path.relative_to(ROOT)}:{number}: forbidden literal (value redacted)"
            )

if violations:
    print(
        "ERROR: topology/identity literals must live in app/config/lab.env or local/secrets/ims.env",
        file=sys.stderr,
    )
    print("\n".join(violations), file=sys.stderr)
    raise SystemExit(1)
print("PASS: no hardcoded lab topology or subscriber identity in executable configuration")
