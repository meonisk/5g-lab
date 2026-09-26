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


def shell_line_ending_error(relative: str, data: bytes) -> str | None:
    # Bind-mounted Linux scripts execute the working-tree bytes, not Git's index.
    # A CR in the shebang becomes an interpreter name such as /usr/bin/env bash\r.
    if relative.endswith(".sh") and b"\r" in data:
        return f"{relative}: shell script has CR line endings; use LF in the working tree"
    return None


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
        data = path.read_bytes()
        error = shell_line_ending_error(relative, data)
        if error:
            errors.append(error)
        text = data.decode("utf-8-sig")
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
