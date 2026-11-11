"""scripts/bench_5g.py без стенда: разбор ping и сводка медиан."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import bench_5g  # noqa: E402

PING = """30 packets transmitted, 30 received, 0% packet loss, time 5800ms
rtt min/avg/max/mdev = 4.101/7.532/15.020/2.110 ms
"""


class Parsing(unittest.TestCase):
    def test_ping_summary_is_parsed(self):
        with patch.object(bench_5g, "sh", return_value=PING):
            row = bench_5g.ping(["ping", "-c", "30", "target"])
        self.assertEqual(row["loss_pct"], 0.0)
        self.assertEqual((row["min_ms"], row["avg_ms"], row["max_ms"]), (4.101, 7.532, 15.02))

    def test_unanswered_ping_is_an_error(self):
        with patch.object(bench_5g, "sh", return_value="100% packet loss"):
            with self.assertRaises(RuntimeError):
                bench_5g.ping(["ping", "target"])

    def test_summary_skips_missing_values(self):
        self.assertEqual(
            bench_5g.summary([300.0, None, 100.0, 200.0]),
            {"n": 3, "median": 200.0, "min": 100.0, "max": 300.0},
        )
        self.assertIsNone(bench_5g.summary([None]))


if __name__ == "__main__":
    unittest.main()
