"""CPU узлов стенда без новых зависимостей: отсчёт раз в 0,5 с, занятые ядра за сценарий.

Контейнеры (стенд и ядро OAI) — счётчик cgroup v2 cpu.stat (usage_usec), путь из
/proc/<pid>/cgroup главного процесса контейнера (docker inspect); cgroup v1 —
cpuacct.usage. Процессы rfsim — utime + stime из /proc/<pid>/stat (весь процесс со
всеми потоками). Хост — /proc/stat. 1,0 ядра = одно ядро целиком за интервал.
"""

import os
import subprocess
import threading
import time
from pathlib import Path

from latency import describe

CGROUP_ROOT = "/sys/fs/cgroup"
# Имя процесса (comm) -> узел отчёта; несколько процессов одного узла складываются.
RFSIM_NODES = {"nr-softmodem": "rfsim-gnb", "nr-uesoftmodem": "rfsim-ue"}


def parse_cpu_stat(text):
    for line in text.splitlines():
        key, _, value = line.partition(" ")
        if key == "usage_usec":
            return int(value) / 1e6
    raise ValueError("нет usage_usec в cpu.stat")


def parse_cpuacct(text):
    return int(text.strip()) / 1e9


def cgroup_counter(proc_cgroup, root=CGROUP_ROOT):
    """(путь счётчика CPU, "v2"|"v1") по содержимому /proc/<pid>/cgroup."""
    for line in proc_cgroup.splitlines():
        _, controllers, path = line.split(":", 2)
        if "cpuacct" in controllers.split(","):
            return f"{root}/{controllers}{path}/cpuacct.usage", "v1"
    for line in proc_cgroup.splitlines():
        hierarchy, controllers, path = line.split(":", 2)
        if hierarchy == "0" and controllers == "":
            return f"{root}{path.rstrip('/')}/cpu.stat", "v2"
    return None


def parse_cpu_max(text):
    """Лимит CPU cgroup v2 в ядрах; "max" — без лимита."""
    quota, period = text.split()[:2]
    return None if quota == "max" else int(quota) / int(period)


def parse_pid_stat(text, clk_tck):
    """(comm, utime + stime в секундах); поля считаются после последней «)»."""
    comm = text[text.index("(") + 1 : text.rindex(")")]
    fields = text[text.rindex(")") + 2 :].split()
    return comm, (int(fields[11]) + int(fields[12])) / clk_tck


def parse_proc_stat(text):
    """(занято, всего) в тиках из строки cpu; idle и iowait — простой."""
    values = [int(v) for v in text.splitlines()[0].split()[1:9]]
    idle = values[3] + values[4]
    return sum(values) - idle, sum(values)


def cores_between(a, b):
    """Занятые ядра каждого узла между отсчётами a и b; ключ «узел:pid» сводится к узлу."""
    elapsed = b["t"] - a["t"]
    cores = {}
    for key, value in b["nodes"].items():
        delta = value - a["nodes"].get(key, value)
        if key not in a["nodes"] or delta < 0 or elapsed <= 0:
            continue
        node = key.split(":", 1)[0]
        cores[node] = round(cores.get(node, 0) + delta / elapsed, 3)
    busy, total = b["host"][0] - a["host"][0], b["host"][1] - a["host"][1]
    if total > 0:
        cores["host"] = round(busy / total * b["ncpu"], 3)
    return cores


def summarize(rows):
    """Ряды занятых ядер за сценарий -> {узел: среднее, p95, максимум}."""
    nodes = sorted({node for row in rows for node in row})
    return {node: describe([row.get(node) for row in rows]) for node in nodes}


def read(path):
    try:
        return Path(path).read_text(encoding="ascii", errors="replace")
    except OSError:
        return None


class Sampler(threading.Thread):
    """Фоновый отсчёт CPU; список контейнеров обновляется: клиенты появляются по ходу."""

    def __init__(self, interval=0.5, refresh=5.0):
        super().__init__(daemon=True)
        self.interval, self.refresh = interval, refresh
        self.rows, self.limits, self.counters = [], {}, {}
        self.cgroup_version = None
        self.clk_tck = os.sysconf("SC_CLK_TCK")
        self.ncpu = os.cpu_count()
        self._halt = threading.Event()

    def discover(self):
        names = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True,
                               text=True, check=False).stdout.split()  # fmt: skip
        counters = {}
        for name in names:
            pid = subprocess.run(["docker", "inspect", "-f", "{{.State.Pid}}", name],
                                 capture_output=True, text=True, check=False).stdout.strip()  # fmt: skip
            found = cgroup_counter(read(f"/proc/{pid}/cgroup") or "") if pid.isdigit() else None
            if found:
                counters[name] = found
                self.cgroup_version = found[1]
                limit = read(str(Path(found[0]).with_name("cpu.max")))
                self.limits[name] = parse_cpu_max(limit) if limit and found[1] == "v2" else None
        self.counters = counters

    def snapshot(self):
        nodes = {}
        for name, (path, version) in self.counters.items():
            text = read(path)
            if text:
                nodes[name] = parse_cpu_stat(text) if version == "v2" else parse_cpuacct(text)
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            text = read(entry / "stat")
            if text and text[text.index("(") + 1 : text.rindex(")")] in RFSIM_NODES:
                comm, seconds = parse_pid_stat(text, self.clk_tck)
                nodes[f"{RFSIM_NODES[comm]}:{entry.name}"] = seconds
        host = parse_proc_stat(read("/proc/stat"))
        return {"t": time.monotonic(), "nodes": nodes, "host": host, "ncpu": self.ncpu}

    def run(self):
        self.discover()
        previous, discovered = self.snapshot(), time.monotonic()
        while not self._halt.wait(self.interval):
            if time.monotonic() - discovered >= self.refresh:
                self.discover()
                discovered = time.monotonic()
            current = self.snapshot()
            self.rows.append(cores_between(previous, current))
            previous = current

    def stop(self):
        self._halt.set()
        self.join(timeout=30)
        return {
            "interval_s": self.interval,
            "samples": len(self.rows),
            "ncpu": self.ncpu,
            "cgroup": self.cgroup_version,
            "limits": {k: v for k, v in self.limits.items() if v},
            "nodes": summarize(self.rows),
        }
