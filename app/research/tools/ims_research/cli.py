"""Command-line interface for the research workflow."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .capture import collect, prepare
from .validation import validate, verify


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "collect", "validate", "verify"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--design", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    root = args.root.resolve()
    design = (
        args.design or root / "app/research" / "designs" / "local-language-services-smoke-v2.json"
    ).resolve()
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
