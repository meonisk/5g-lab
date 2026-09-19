"""Single offline developer/CI command; never changes the running stand."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    commands = [
        [sys.executable, "tools/quality/check_layout.py"],
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "services",
            "research/tools",
            "tools",
            "tests/unit",
        ],
        [
            sys.executable,
            "-m",
            "ruff",
            "format",
            "--check",
            "services",
            "research/tools",
            "tools",
            "tests/unit",
        ],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-v"],
        [sys.executable, "scripts/check-no-hardcoded-topology.py"],
        [sys.executable, "research/tools/research_run.py", "verify", "--root", "."],
    ]
    for command in commands:
        subprocess.run(command, cwd=ROOT, check=True)
    print("TEAM OFFLINE CHECKS: PASS")


if __name__ == "__main__":
    main()
