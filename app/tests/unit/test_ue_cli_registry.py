"""Synthetic UERANSIM proc-table ownership and quarantine tests."""

import subprocess
import unittest
from unittest.mock import patch

from app.tests.integration.ue_cli_registry import (
    RegistryError,
    classify_registry,
    inspect_registry,
    quarantine_registry,
)

NODE = "imsi-999990000000001"
ACTIVE = "a" * 32
STALE = "b" * 32
HASH = "c" * 64
SNAPSHOT = f"""PROC\t13\t367888\tnr-ue -c ue.yaml\x20
FD\t201452
FD\t201453
UDP\t0100007F:B155\t201452
UDP\t0100007F:D66B\t999999
FILE\t{STALE}\t{HASH}\t3 2 6 13 54891 1 {NODE}
FILE\t{ACTIVE}\t{HASH}\t3 2 6 13 45397 1 {NODE}
"""


class RegistryTests(unittest.TestCase):
    def test_exact_live_port_and_stale_record(self):
        plan = classify_registry(SNAPSHOT, NODE)
        self.assertEqual(plan["pid"], "13")
        self.assertEqual(plan["start_time"], "367888")
        self.assertEqual(plan["active_port"], 45397)
        self.assertEqual([(item["name"], item["port"]) for item in plan["stale"]], [(STALE, 54891)])

    def test_ambiguous_or_mismatched_process_fails_closed(self):
        for altered in (
            SNAPSHOT.replace("PROC\t13\t367888", "PROC\t13\t367888\nPROC\t14\t77"),
            SNAPSHOT.replace("nr-ue -c ue.yaml ", "nr-ue -c other.yaml "),
            SNAPSHOT.replace("FD\t201452", "FD\t888888"),
            SNAPSHOT.replace("UDP\t0100007F:D66B\t999999", "UDP\t0100007F:D66B\t201453"),
            SNAPSHOT.replace(f"3 2 6 13 54891 1 {NODE}", f"3 2 6 99 54891 1 {NODE}"),
            SNAPSHOT.replace(f"FILE\t{STALE}", f"FILE\t{'x' * 32}"),
        ):
            with self.subTest(altered=altered[:50]), self.assertRaises(RegistryError):
                classify_registry(altered, NODE)

    @patch("app.tests.integration.ue_cli_registry.subprocess.run")
    def test_inspection_is_read_only_and_bounded(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, SNAPSHOT, "")
        self.assertEqual(inspect_registry("synthetic-ue", NODE)["active_port"], 45397)
        args, kwargs = run.call_args
        self.assertEqual(args[0][:3], ["docker", "exec", "synthetic-ue"])
        self.assertEqual(kwargs["timeout"], 8)
        self.assertNotIn("nr-cli", args[0])

    @patch("app.tests.integration.ue_cli_registry._docker")
    def test_quarantine_rechecks_and_preserves_receipt(self, docker):
        docker.side_effect = [SNAPSHOT, f"MOVED\t{STALE}\n"]
        plan = classify_registry(SNAPSHOT, NODE)
        receipt = quarantine_registry("synthetic-ue", NODE, plan)
        self.assertEqual(receipt["files"], plan["stale"])
        self.assertIn("proc-table-quarantine", receipt["backup_dir"])
        self.assertEqual(docker.call_count, 2)

    @patch("app.tests.integration.ue_cli_registry._docker")
    def test_changed_plan_never_moves(self, docker):
        docker.return_value = SNAPSHOT.replace("367888", "367889")
        with self.assertRaises(RegistryError):
            quarantine_registry("synthetic-ue", NODE, classify_registry(SNAPSHOT, NODE))
        self.assertEqual(docker.call_count, 1)


if __name__ == "__main__":
    unittest.main()
