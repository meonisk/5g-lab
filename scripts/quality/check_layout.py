"""Check source size and Python syntax without running containers."""

import ast
import io
import subprocess
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAX_LOGICAL_LINES = 300
SOURCE_SUFFIXES = {".py", ".sh", ".ps1", ".js", ".yml", ".yaml"}


def python_logical_lines(text: str) -> int:
    """Count completed Python statements, not their visual wrapping."""
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    return sum(token.type == tokenize.NEWLINE for token in tokens)


def text_logical_lines(text: str) -> int:
    """Count non-empty, non-comment lines in shell and configuration files."""
    return sum(
        bool(line) and not line.startswith(("#", "//"))
        for line in (source_line.strip() for source_line in text.splitlines())
    )


def logical_lines(path: Path, text: str) -> int:
    if path.suffix == ".py":
        return python_logical_lines(text)
    return text_logical_lines(text)


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
        if relative.startswith("app/infrastructure/vendor/") or not path.is_file():
            continue
        if path.suffix not in SOURCE_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8-sig")
        checked += 1
        line_count = logical_lines(path, text)
        if line_count > MAX_LOGICAL_LINES:
            errors.append(
                f"{relative}: {line_count} logical lines exceeds {MAX_LOGICAL_LINES} "
                f"({len(text.splitlines())} physical lines)"
            )
        if path.suffix == ".py":
            try:
                ast.parse(text, filename=relative)
            except SyntaxError as exc:
                errors.append(str(exc))
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"PASS: {checked} owned source/config files, each <= {MAX_LOGICAL_LINES} logical lines")


if __name__ == "__main__":
    main()
