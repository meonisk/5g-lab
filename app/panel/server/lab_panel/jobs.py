"""Задания панели: только команды из белого списка, вывод — в память и local/panel/jobs.

Изменяющие стенд задания выполняются строго по одному (они делят один стенд, как
интеграционные проверки). Задание живёт в своей группе процессов: перезапуск
панели его не прерывает (KillMode=process в службе).
"""

import itertools
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from . import docker

MAX_LINES = 5000
# Имя -> (команда относительно корня репозитория, меняет ли стенд).
ACTIONS = {
    "stand-up": (["scripts/stand.sh", "up"], True),
    "stand-down": (["scripts/stand.sh", "down"], True),
    "gnb-up": (["scripts/gnb.sh", "up"], True),
    "gnb-down": (["scripts/gnb.sh", "down"], True),
    "rfsim-up": (["scripts/rfsim.sh", "up"], True),
    "rfsim-down": (["scripts/rfsim.sh", "down"], True),
    "stand-check": (["python3", "scripts/stand_check.py"], True),
    "verify-all": (["scripts/verify-all.sh"], True),
    "collect": (["python3", "scripts/stand_check.py", "collect"], False),
    "phones": (["python3", "scripts/stand_check.py", "phones"], False),
    "sims": (["python3", "scripts/research_sims.py", "status"], False),
    "core-check": (["scripts/core-setup.sh", "check"], False),
}
# Отдельные интеграционные проверки (звонят через стенд — изменяющие).
VERIFY = ("verify-ims", "verify-ims-call", "verify-voice-agent", "verify-translation")
VERIFY += ("verify-transcription",)
RESTARTABLE = re.compile(r"^(lab-[a-z0-9-]+|oai-[a-z0-9-]+|mysql)$")
# Действия, для которых нужен sudo без пароля.
NEEDS_SUDO = {"stand-up", "stand-down", "gnb-up", "gnb-down", "rfsim-up", "rfsim-down"}


def catalog() -> list[dict]:
    items = [
        {"name": name, "changes": changes, "sudo": name in NEEDS_SUDO}
        for name, (_, changes) in ACTIONS.items()
    ]
    items += [{"name": f"verify:{name}", "changes": True, "sudo": False} for name in VERIFY]
    return items


def resolve(name: str, running: set[str]) -> tuple[list[str], bool] | None:
    """Имя действия -> (команда, меняет ли стенд) или None, если не разрешено."""
    if name in ACTIONS:
        return ACTIONS[name]
    kind, _, target = name.partition(":")
    if kind == "verify" and target in VERIFY:
        return ["bash", f"app/tests/integration/{target}.sh"], True
    if kind == "restart" and RESTARTABLE.fullmatch(target) and target in running:
        return ["docker", "restart", target], True
    return None


class Job:
    def __init__(self, number: int, name: str, command: list[str], changes: bool, folder: Path):
        self.id = f"{time.strftime('%Y%m%d-%H%M%S')}-{number}"
        self.name, self.command, self.changes = name, command, changes
        self.started, self.ended, self.code = time.time(), None, None
        self.lines: list[str] = []
        self.dropped = 0
        self.changed = threading.Condition()
        self.path = folder / f"{self.id}-{name.replace(':', '-')}.log"

    def add(self, line: str) -> None:
        with self.changed:
            self.lines.append(line)
            if len(self.lines) > MAX_LINES:
                del self.lines[0]
                self.dropped += 1
            self.changed.notify_all()

    def finish(self, code: int) -> None:
        with self.changed:
            self.code, self.ended = code, time.time()
            self.changed.notify_all()

    def info(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "command": " ".join(self.command),
            "changes": self.changes,
            "started": self.started,
            "ended": self.ended,
            "code": self.code,
            "log": str(self.path),
        }

    def follow(self, heartbeat: float = 15):
        """Строки задания с начала; None — нет новых строк за heartbeat секунд."""
        position = 0
        while True:
            with self.changed:
                if position - self.dropped >= len(self.lines) and self.ended is None:
                    self.changed.wait(heartbeat)
                start = max(position - self.dropped, 0)
                fresh = self.lines[start:]
                position = self.dropped + len(self.lines)
                done = self.ended is not None
            if fresh:
                yield from fresh
            elif not done:
                yield None
            if done and position - self.dropped >= len(self.lines):
                return


class Runner:
    def __init__(self, root: Path, history: int = 50):
        self.root = root
        self.folder = root / "local/panel/jobs"
        self.jobs: list[Job] = []
        self.history = history
        self.lock = threading.Lock()
        self.numbers = itertools.count(1)

    def environment(self) -> dict:
        # Обёртка sudo первой в PATH: sudo -n вместо запроса пароля без терминала.
        path = f"{self.root}/app/panel/bin:{os.environ.get('PATH', '')}"
        return dict(os.environ, PATH=path, PYTHONUNBUFFERED="1", LAB_PANEL="1")

    def current(self) -> dict | None:
        with self.lock:
            active = [job for job in self.jobs if job.ended is None and job.changes]
        return active[-1].info() if active else None

    def start(self, name: str) -> Job | str:
        """Новое задание или текст отказа."""
        running = {item["Names"] for item in docker.containers() if item.get("State") == "running"}
        resolved = resolve(name, running)
        if resolved is None:
            return "unknown"
        command, changes = resolved
        with self.lock:
            if changes and any(job.ended is None and job.changes for job in self.jobs):
                return "busy"
            job = Job(next(self.numbers), name, command, changes, self.folder)
            self.jobs = (self.jobs + [job])[-self.history :]
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            return next((job for job in self.jobs if job.id == job_id), None)

    def list(self) -> list[dict]:
        with self.lock:
            return [job.info() for job in reversed(self.jobs)]

    def _run(self, job: Job) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        with job.path.open("w", encoding="utf-8") as log:
            try:
                process = subprocess.Popen(
                    job.command,
                    cwd=self.root,
                    env=self.environment(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    start_new_session=True,
                )
            except OSError as error:
                job.add(f"ERROR: не запустилось: {error}")
                job.finish(127)
                return
            for line in process.stdout:
                line = line.rstrip("\n")
                log.write(line + "\n")
                log.flush()
                job.add(line)
            job.finish(process.wait())
