"""scripts/profile/cpu_sampler.py: занятые ядра из счётчиков cgroup и /proc без стенда."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts/lib"), str(ROOT / "scripts/profile")]
import cpu_sampler  # noqa: E402

PROC_STAT = "cpu  100 0 50 800 50 0 0 0 0 0\ncpu0 1 2 3\n"
PID_STAT = "4242 (nr-uesoftmodem) S 1 4242 4242 0 -1 4194560 10 0 0 0 250 150 0 0 20 0 9 0\n"


class Counters(unittest.TestCase):
    def test_cgroup_v2_cpu_stat_in_seconds(self):
        text = "usage_usec 2500000\nuser_usec 2000000\nsystem_usec 500000\n"
        self.assertEqual(cpu_sampler.parse_cpu_stat(text), 2.5)

    def test_cgroup_v1_cpuacct_in_seconds(self):
        self.assertEqual(cpu_sampler.parse_cpuacct("1500000000\n"), 1.5)

    def test_counter_path_from_proc_cgroup(self):
        v2 = "0::/system.slice/docker-abc.scope\n"
        self.assertEqual(
            cpu_sampler.cgroup_counter(v2, "/sys/fs/cgroup"),
            ("/sys/fs/cgroup/system.slice/docker-abc.scope/cpu.stat", "v2"),
        )
        v1 = "5:memory:/docker/abc\n4:cpu,cpuacct:/docker/abc\n1:name=systemd:/docker/abc\n"
        self.assertEqual(
            cpu_sampler.cgroup_counter(v1, "/sys/fs/cgroup"),
            ("/sys/fs/cgroup/cpu,cpuacct/docker/abc/cpuacct.usage", "v1"),
        )
        self.assertIsNone(cpu_sampler.cgroup_counter("", "/sys/fs/cgroup"))

    def test_cpu_max_limit_in_cores(self):
        self.assertEqual(cpu_sampler.parse_cpu_max("200000 100000\n"), 2.0)
        self.assertIsNone(cpu_sampler.parse_cpu_max("max 100000\n"))

    def test_process_stat_utime_plus_stime(self):
        self.assertEqual(cpu_sampler.parse_pid_stat(PID_STAT, 100), ("nr-uesoftmodem", 4.0))
        # Имя процесса может содержать пробелы и скобки: поля считаются после последней «)».
        odd = PID_STAT.replace("(nr-uesoftmodem)", "(a (b) c)")
        self.assertEqual(cpu_sampler.parse_pid_stat(odd, 100), ("a (b) c", 4.0))

    def test_host_busy_and_total_ticks(self):
        # busy = всё, кроме idle и iowait; гостевое время уже входит в user.
        self.assertEqual(cpu_sampler.parse_proc_stat(PROC_STAT), (150, 1000))


class Cores(unittest.TestCase):
    def sample(self, t, nodes, host):
        return {"t": t, "nodes": nodes, "host": host, "ncpu": 12}

    def test_cores_between_two_samples(self):
        a = self.sample(10.0, {"lab-ai-worker": 1.0, "rfsim-ue:1": 5.0, "gone": 1.0}, (100, 1000))
        b = self.sample(10.5, {"lab-ai-worker": 1.5, "rfsim-ue:1": 5.25, "rfsim-ue:2": 0.0,
                               "new": 3.0}, (400, 1600))  # fmt: skip
        cores = cpu_sampler.cores_between(a, b)
        self.assertEqual(cores["lab-ai-worker"], 1.0)
        # Процессы одного узла (два UE) складываются; новые и исчезнувшие — без дельты.
        self.assertEqual(cores["rfsim-ue"], 0.5)
        self.assertNotIn("gone", cores)
        self.assertNotIn("new", cores)
        self.assertEqual(cores["host"], 6.0)

    def test_counter_reset_is_not_negative(self):
        a = self.sample(0.0, {"lab-sipue1": 9.0}, (0, 100))
        b = self.sample(1.0, {"lab-sipue1": 0.2}, (0, 200))
        self.assertNotIn("lab-sipue1", cpu_sampler.cores_between(a, b))

    def test_summarize_per_node(self):
        rows = [{"host": 1.0, "a": 0.5}, {"host": 3.0}, {"host": 2.0, "a": 1.5}]
        result = cpu_sampler.summarize(rows)
        self.assertEqual(result["host"]["mean"], 2.0)
        self.assertEqual(result["a"], {"n": 2, "mean": 1.0, "p95": 1.45, "max": 1.5})


if __name__ == "__main__":
    unittest.main()
