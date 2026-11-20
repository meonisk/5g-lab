"""Вызовы docker CLI: панель работает от пользователя в группе docker."""

import ctypes
import json
import re
import signal
import subprocess
import sys

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def run(*arguments: str, timeout: float = 20) -> str:
    """Вывод команды; при ошибке или таймауте — пустая строка (панель не падает)."""
    try:
        result = subprocess.run(
            ["docker", *arguments],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def json_lines(text: str) -> list[dict]:
    """`--format '{{json .}}'` печатает по объекту JSON на строку."""
    items = []
    for line in text.splitlines():
        try:
            items.append(json.loads(line))
        except ValueError:
            continue
    return items


def containers() -> list[dict]:
    return json_lines(run("ps", "-a", "--no-trunc", "--format", "{{json .}}"))


def addresses() -> dict[str, str]:
    """IP-адрес -> имя запущенного контейнера (для подписей SIP-диаграммы)."""
    names = [item["Names"] for item in json_lines(run("ps", "--format", "{{json .}}"))]
    if not names:
        return {}
    template = "{{.Name}}{{range .NetworkSettings.Networks}} {{.IPAddress}}{{end}}"
    result = {}
    for line in run("inspect", "-f", template, *names).splitlines():
        name, *ips = line.split()
        for ip in ips:
            result[ip] = name.lstrip("/")
    return result


def _die_with_parent() -> None:
    # PR_SET_PDEATHSIG = 1: процесс получает SIGTERM, когда умирает сервер панели.
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)


def follower_options() -> dict:
    """Для долгих `docker logs -f` / `tail -F`: служба перезапускается с
    KillMode=process (ради заданий), и без этого читатели журналов оставались бы сиротами."""
    return {"preexec_fn": _die_with_parent} if sys.platform == "linux" else {}


def valid_name(value: str) -> bool:
    return bool(NAME.fullmatch(value or ""))
