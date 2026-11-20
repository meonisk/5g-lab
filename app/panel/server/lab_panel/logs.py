"""Живые журналы: контейнеры (`docker logs -f`) и файлы радио (`tail -F`) в одном потоке.

Каждый источник читает свой процесс; строки сливаются в очередь. Когда браузер
закрывает поток, процессы завершаются. Строки, похожие на ключи, скрываются.
"""

import queue
import subprocess
import threading
from pathlib import Path

from . import docker, redact

# Файлы радио: имя источника -> путь относительно корня репозитория.
FILES = {
    "gnb": "local/gnb/gnb.log",
    "rfsim-gnb": "local/rfsim/gnb.log",
    "rfsim-ue1": "local/rfsim/ue1.log",
    "rfsim-ue2": "local/rfsim/ue2.log",
}
MAX_SOURCES = 12


def sources() -> list[dict]:
    names = [item["Names"] for item in docker.containers() if item.get("Names")]
    items = [{"name": name, "kind": "container"} for name in sorted(names)]
    return items + [{"name": name, "kind": "file", "path": path} for name, path in FILES.items()]


def command_for(name: str, root: Path, tail: int) -> list[str] | None:
    if name in FILES:
        return ["tail", "-n", str(tail), "-F", str(root / FILES[name])]
    if docker.valid_name(name):
        return ["docker", "logs", "-f", "--timestamps", "--tail", str(tail), name]
    return None


class Stream:
    """Поток строк (источник, строка) из нескольких процессов."""

    def __init__(self, names: list[str], root: Path, tail: int):
        self.lines: queue.Queue = queue.Queue(maxsize=10000)
        self.processes: list[subprocess.Popen] = []
        for name in names[:MAX_SOURCES]:
            command = command_for(name, root, tail)
            if command is None:
                continue
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    **docker.follower_options(),
                )
            except OSError:
                continue
            self.processes.append(process)
            threading.Thread(target=self._read, args=(name, process), daemon=True).start()

    def _read(self, name: str, process: subprocess.Popen) -> None:
        for line in process.stdout:
            try:
                self.lines.put((name, redact.log_line(line.rstrip("\n"))), timeout=5)
            except queue.Full:
                continue  # браузер не успевает: строки отбрасываются, панель не растёт

    def items(self, heartbeat: float = 10):
        """Строки по мере поступления; None — давно ничего не было."""
        while True:
            try:
                yield self.lines.get(timeout=heartbeat)
            except queue.Empty:
                yield None

    def close(self) -> None:
        for process in self.processes:
            process.kill()
            process.wait(timeout=5)
