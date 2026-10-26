"""Offline-проверки перед коммитом: Git, размер и синтаксис, ссылки, топология, ruff, unit."""

import ast
import io
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MAX_LOGICAL_LINES = 300
SOURCE_SUFFIXES = {".py", ".sh", ".yml", ".yaml"}
PRIVATE_SUFFIXES = {".wav", ".flac", ".mp3", ".ogg", ".pcap", ".pcapng", ".pem", ".key", ".zip"}
SIGNATURE = re.compile(
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}"
)
# Адреса, IMSI и домен живут только в lab.env; код получает их из окружения.
TOPOLOGY = (
    re.compile(r"\b(?:192\.168\.70|12\.1\.1)\.\d{1,3}(?:/\d+)?\b"),
    re.compile(r"\b0010100000001?0[0-9]\b"),
    re.compile(r"\bims\.mnc001\.mcc001\.3gppnetwork\.org\b"),
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(<?([^\s)>]+)>?(?:\s+\"[^\"]*\")?\)")


def tracked_files():
    """Индекс и новые неигнорируемые файлы; local/, записи и кэш сюда не попадают."""
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
    )
    names = sorted(set(output.decode().split("\0")) - {""})
    return [name for name in names if (ROOT / name).is_file()]


def check_git_index():
    errors = []
    records = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=ROOT)
    for record in filter(None, records.decode().split("\0")):
        metadata, name = record.split("\t", 1)
        mode, _, stage = metadata.split()
        path = PurePosixPath(name)
        if stage != "0":
            errors.append(f"{name}: неразрешённый merge")
        if name.endswith(".sh") and mode != "100755":
            errors.append(f"{name}: shell-файл без права исполнения в Git")
        if "local" in path.parts or path.suffix.lower() in PRIVATE_SUFFIXES:
            errors.append(f"{name}: приватный или сгенерированный файл в индексе")
        if SIGNATURE.search((ROOT / name).read_bytes() if (ROOT / name).is_file() else b""):
            errors.append(f"{name}: похоже на ключ или токен (значение скрыто)")
    return errors


def logical_lines(path, text):
    if path.suffix == ".py":
        # Считаем завершённые операторы Python, а не визуальные переносы строк.
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        return sum(token.type == tokenize.NEWLINE for token in tokens)
    lines = (line.strip() for line in text.splitlines())
    return sum(bool(line) and not line.startswith("#") for line in lines)


def check_sources(names):
    errors = []
    for name in names:
        path = ROOT / name
        if name.startswith("app/infrastructure/vendor/") or path.suffix not in SOURCE_SUFFIXES:
            continue
        data = path.read_bytes()
        # Скрипты монтируются в Linux-контейнеры как есть: CR ломает shebang.
        if name.endswith(".sh") and b"\r" in data:
            errors.append(f"{name}: CR в shell-скрипте; нужны окончания строк LF")
        text = data.decode("utf-8-sig")
        count = logical_lines(path, text)
        if count > MAX_LOGICAL_LINES:
            errors.append(f"{name}: {count} логических строк > {MAX_LOGICAL_LINES}")
        if path.suffix == ".py":
            try:
                ast.parse(text, filename=name)
            except SyntaxError as error:
                errors.append(str(error))
        if name != "app/config/lab.env" and name != "scripts/check.py":
            for number, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if any(pattern.search(stripped) for pattern in TOPOLOGY):
                    errors.append(f"{name}:{number}: адрес/IMSI/домен вне app/config/lab.env")
    return errors


def check_markdown_links(names):
    errors = []
    for name in names:
        if not name.endswith(".md") or name.startswith("app/infrastructure/vendor/"):
            continue
        path = ROOT / name
        text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
        for match in MARKDOWN_LINK.finditer(text):
            target = urlsplit(match.group(1))
            if target.scheme or target.netloc or not target.path:
                continue
            destination = (path.parent / unquote(target.path)).resolve()
            if not destination.is_relative_to(ROOT) or not destination.exists():
                errors.append(f"{name}: битая локальная ссылка {target.path}")
    return errors


def main():
    names = tracked_files()
    errors = check_git_index() + check_sources(names) + check_markdown_links(names)
    if errors:
        raise SystemExit("\n".join(sorted(set(errors))))
    print(f"FILES: PASS — {len(names)} файлов: Git, размер, синтаксис, ссылки, топология")

    folders = ["app/services", "scripts", "app/tests"]
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "app/services"))
    for command in (
        [sys.executable, "-m", "ruff", "check", *folders],
        [sys.executable, "-m", "ruff", "format", "--check", *folders],
        [sys.executable, "-m", "unittest", "discover", "-s", "app/tests/unit"],
    ):
        subprocess.run(command, cwd=ROOT, env=environment, check=True)
    print("OFFLINE CHECKS: PASS — стенд не запускался, вызовы не проверены")


if __name__ == "__main__":
    main()
