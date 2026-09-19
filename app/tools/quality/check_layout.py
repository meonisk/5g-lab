"""Check the team's source-size and syntax contract without running containers."""

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAX_LINES = 300
SOURCE_SUFFIXES = {".py", ".sh", ".ps1", ".js", ".yml", ".yaml"}


def main():
    # Git's inventory excludes private recordings, secrets, evidence, and caches.
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    errors = []
    checked = 0
    for relative in sorted(set(result.stdout.decode().split("\0")) - {""}):
        path = ROOT / relative
        if relative.startswith("vendor/") or not path.is_file():
            continue
        if path.suffix not in SOURCE_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8-sig")
        checked += 1
        if len(text.splitlines()) > MAX_LINES:
            errors.append(f"{relative}: {len(text.splitlines())} lines exceeds {MAX_LINES}")
        if path.suffix == ".py":
            try:
                ast.parse(text, filename=relative)
            except SyntaxError as exc:
                errors.append(str(exc))
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"PASS: {checked} owned source/config files, each <= {MAX_LINES} physical lines")


if __name__ == "__main__":
    main()
