"""Сводка для верхней строки и вкладки «Обзор»: контейнеры, радио, sudo, хост."""

import os
import subprocess
import time
from pathlib import Path

from . import docker

AI = {"lab-media-adapter", "lab-ai-worker", "lab-voice-agent", "lab-llm-worker"}
# Одноразовые контейнеры подготовки: «Exited (0)» для них — норма.
INIT = {"lab-stand-init", "lab-llm-model-init"}
_sudo_cache = {"checked": 0.0, "ok": False}


def group_of(name: str) -> str | None:
    if name.startswith("oai-") or name == "mysql":
        return "core"
    if name.startswith("lab-panel"):
        return "panel"
    if name in AI:
        return "ai"
    if name in INIT:
        return "init"
    if name.startswith("lab-"):
        return "ims"
    return None


def container_state(item: dict) -> dict:
    """Строка `docker ps` -> состояние карточки (health берётся из текста Status)."""
    status = item.get("Status", "")
    health = ""
    for word in ("healthy", "unhealthy", "starting"):
        if f"({word})" in status or f"(health: {word})" in status:
            health = word
            break
    return {
        "name": item.get("Names", ""),
        "group": group_of(item.get("Names", "")),
        "state": item.get("State", ""),
        "status": status,
        "health": health,
        "image": item.get("Image", ""),
    }


def containers() -> list[dict]:
    states = [container_state(item) for item in docker.containers()]
    return sorted((s for s in states if s["group"]), key=lambda s: (s["group"], s["name"]))


def radio(root: Path) -> list[dict]:
    """Процессы OAI: наш gNB (local/gnb), rfsim (local/rfsim) или чужой gNB."""
    try:
        output = subprocess.run(
            ["pgrep", "-af", "[n]r-(ue)?softmodem"], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    processes = []
    for line in output.splitlines():
        pid, _, command = line.partition(" ")
        if "sudo " in command.split("softmodem")[0]:
            continue  # обёртка sudo — тот же процесс
        if f"{root}/local/gnb/" in command:
            kind = "gnb"
        elif f"{root}/local/rfsim/" in command:
            kind = "rfsim-ue" if "uesoftmodem" in command else "rfsim-gnb"
        else:
            kind = "foreign"
        processes.append({"pid": int(pid), "kind": kind})
    return processes


def sudo_ready() -> bool:
    """Есть ли sudo без пароля; проверка раз в минуту, без терминала."""
    now = time.monotonic()
    if now - _sudo_cache["checked"] > 60:
        try:
            code = subprocess.run(
                ["sudo", "-n", "true"], capture_output=True, timeout=5, stdin=subprocess.DEVNULL
            ).returncode
        except (OSError, subprocess.TimeoutExpired):
            code = 1
        _sudo_cache.update(checked=now, ok=code == 0)
    return _sudo_cache["ok"]


def host() -> dict:
    info = {"load": None, "mem_used_mib": None, "mem_total_mib": None}
    try:
        info["load"] = os.getloadavg()[0]
        values = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            values[key] = int(rest.split()[0]) / 1024
        info["mem_total_mib"] = round(values["MemTotal"])
        info["mem_used_mib"] = round(values["MemTotal"] - values["MemAvailable"])
    except (OSError, KeyError, ValueError):
        pass
    return info


def summary(root: Path, job) -> dict:
    return {
        "plmn": f"{os.environ.get('MCC', '?')}/{os.environ.get('MNC', '?')}",
        "ims_domain": os.environ.get("IMS_DOMAIN", ""),
        "containers": containers(),
        "radio": radio(root),
        "sudo": sudo_ready(),
        "job": job,
        "host": host(),
        "time": time.time(),
    }
