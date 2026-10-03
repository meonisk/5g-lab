"""Проверка локальных Markdown-ссылок в существующих и новых документах."""

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"!?\[[^\]]*\]\(<?([^\s)>]+)>?(?:\s+\"[^\"]*\")?\)")


def main():
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
    )
    errors = []
    checked = 0
    documents = 0
    for name in sorted(set(output.decode().split("\0"))):
        if not name.endswith(".md") or name.startswith("app/infrastructure/vendor/"):
            continue
        path = ROOT / name
        if not path.is_file():
            continue
        documents += 1
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        for match in LINK.finditer(text):
            target = urlsplit(match.group(1))
            if target.scheme or target.netloc or not target.path:
                continue
            checked += 1
            destination = (path.parent / unquote(target.path)).resolve()
            if not destination.is_relative_to(ROOT) or not destination.exists():
                errors.append(
                    f"{name}: ссылка не существует или выходит за репозиторий: {target.path}"
                )
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"DOCUMENTATION LINKS: PASS — документов: {documents}, локальных ссылок: {checked}")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "scripts"))
    from script_console import configure_output

    configure_output()
    main()
