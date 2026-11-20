"""Метрики в памяти за 24 ч: ресурсы контейнеров и хоста, SIP, задержки AI.

Опрос каждые SAMPLE_SECONDS: `docker stats` и /proc. Счётчики SIP пополняются из
новых сообщений захвата, события AI — из журналов lab-ai-worker и lab-voice-agent
(строки «AI <событие> ... llm_ms=...»). Ряды — пары (время, значение).
"""

import collections
import re
import subprocess
import threading
import time

from . import docker, status

SAMPLE_SECONDS = 10
KEEP_SECONDS = 24 * 3600
EVENT = re.compile(r"\b(AI|LLM|VOICE) ([a-z_]+)\b(.*)")
FIELD = re.compile(r"\b([a-z_]+_(?:ms|seconds))=([0-9]+(?:\.[0-9]+)?)")
SIZE = re.compile(r"([0-9.]+)\s*([KMGT]?i?B)")
UNITS = {"B": 1 / 2**20, "KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "TiB": 2**20}
UNITS |= {"kB": 1 / 1024, "KB": 1 / 1024, "MB": 1, "GB": 1024}
SOURCES = ("lab-ai-worker", "lab-voice-agent")


def mebibytes(text: str) -> float | None:
    match = SIZE.search(text)
    if not match:
        return None
    return float(match.group(1)) * UNITS.get(match.group(2), 1)


def parse_stats(item: dict) -> tuple[str, float | None, float | None]:
    """Строка `docker stats --format json` -> (контейнер, CPU %, память MiB)."""
    try:
        cpu = float(item.get("CPUPerc", "").rstrip("%"))
    except ValueError:
        cpu = None
    memory = mebibytes(item.get("MemUsage", "").split("/")[0])
    return item.get("Name", ""), cpu, memory


def parse_event(line: str) -> list[tuple[str, float]]:
    """Строка журнала AI -> [(ряд, значение)], например ai:reply_delivered:llm_ms."""
    match = EVENT.search(line)
    if not match:
        return []
    prefix = f"{match.group(1).lower()}:{match.group(2)}"
    return [(f"{prefix}:{name}", float(value)) for name, value in FIELD.findall(match.group(3))]


class Metrics:
    def __init__(self):
        self.series: dict[str, collections.deque] = {}
        self.lock = threading.Lock()
        self.sip = collections.Counter()

    def add(self, name: str, value: float, when: float | None = None) -> None:
        when = time.time() if when is None else when
        with self.lock:
            points = self.series.setdefault(name, collections.deque())
            points.append((round(when, 1), value))
            while points and points[0][0] < when - KEEP_SECONDS:
                points.popleft()

    def query(self, names: list[str], since: float) -> dict:
        with self.lock:
            return {name: [p for p in self.series.get(name, ()) if p[0] >= since] for name in names}

    def names(self) -> list[str]:
        with self.lock:
            return sorted(self.series)

    def on_sip(self, messages: list[dict]) -> None:
        """Слушатель Calls: счёт запросов и отказов до следующего опроса."""
        for message in messages:
            line = message["text"].split("\n", 1)[0]
            if line.startswith("SIP/2.0 "):
                code = int(line[8:11])
                if code >= 400 and code not in (401, 407, 487):
                    self.sip["fail"] += 1
            else:
                method = line.split(" ", 1)[0]
                if method in ("REGISTER", "INVITE", "BYE"):
                    self.sip[method.lower()] += 1

    def sample(self) -> None:
        now = time.time()
        output = docker.run("stats", "--no-stream", "--format", "{{json .}}", timeout=30)
        for item in docker.json_lines(output):
            name, cpu, memory = parse_stats(item)
            if cpu is not None:
                self.add(f"cpu:{name}", cpu, now)
            if memory is not None:
                self.add(f"mem:{name}", round(memory, 1), now)
        host = status.host()
        if host["load"] is not None:
            self.add("host:load1", round(host["load"], 2), now)
        if host["mem_used_mib"] is not None:
            self.add("host:mem_used_mib", host["mem_used_mib"], now)
        counts, self.sip = self.sip, collections.Counter()
        for key in ("register", "invite", "bye", "fail"):
            self.add(f"sip:{key}", counts[key], now)

    def sample_forever(self) -> None:
        while True:
            started = time.monotonic()
            try:
                self.sample()
            except Exception:  # noqa: BLE001 — сбой одного опроса не останавливает метрики
                pass
            time.sleep(max(1.0, SAMPLE_SECONDS - (time.monotonic() - started)))

    def follow_events(self, container: str) -> None:
        """Журнал контейнера с текущего момента; при остановке — повтор через 10 с."""
        while True:
            try:
                process = subprocess.Popen(
                    ["docker", "logs", "-f", "--since", "1s", container],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    **docker.follower_options(),
                )
                for line in process.stdout:
                    for name, value in parse_event(line):
                        self.add(name, value)
                process.wait()
            except OSError:
                pass
            time.sleep(10)

    def start(self) -> None:
        threading.Thread(target=self.sample_forever, daemon=True).start()
        for container in SOURCES:
            threading.Thread(target=self.follow_events, args=(container,), daemon=True).start()
