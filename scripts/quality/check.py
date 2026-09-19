"""Single offline developer/CI command; never changes the running stand."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    commands = [
        [sys.executable, "scripts/quality/check_layout.py"],
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "app/services",
            "app/research/tools",
            "scripts/quality",
            "app/tests/unit",
        ],
        [
            sys.executable,
            "-m",
            "ruff",
            "format",
            "--check",
            "app/services",
            "app/research/tools",
            "scripts/quality",
            "app/tests/unit",
        ],
        [sys.executable, "-m", "unittest", "discover", "-s", "app/tests/unit", "-v"],
        [sys.executable, "scripts/check-no-hardcoded-topology.py"],
        [sys.executable, "app/research/tools/research_run.py", "verify", "--root", "."],
    ]
    for command in commands:
        subprocess.run(command, cwd=ROOT, check=True)
    print("TEAM OFFLINE CHECKS: PASS")


if __name__ == "__main__":
    main()
