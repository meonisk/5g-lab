"""Проверка стенда: разбор регистрации, фильтр секретов и подсказки без Docker."""

import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
CHECK = importlib.import_module("stand_check")


class StandCheck(unittest.TestCase):
    def setUp(self):
        CHECK.results.clear()
        self.sims = [{"IMSI": "999990000000601", "MSISDN": "2601"}]

    def test_registration_is_read_from_valid_scscf_contact(self):
        logs = "x 999990000000601@192.0.2.44:5060 ... Contact valid\nother line\n"
        with patch.object(CHECK, "docker", return_value=(0, logs)):
            self.assertEqual(CHECK.registered({}, self.sims), {"999990000000601": "192.0.2.44"})
        with patch.object(CHECK, "docker", return_value=(0, "999990000000601 expired")):
            self.assertEqual(CHECK.registered({}, self.sims), {})

    def test_secret_lines_are_dropped(self):
        for line in ('Authorization: Digest nonce="abc"', "ck=00 ik=11", "AuC opc set", "RAND x"):
            self.assertTrue(CHECK.SECRET.search(line), line)
        for line in ("SIP/2.0 200 OK", "AS terminated INVITE", "operand random"):
            self.assertFalse(CHECK.SECRET.search(line), line)

    def test_stale_services_are_reported_with_rebuild_hint(self):
        with patch.object(CHECK, "docker", return_value=(1, "")):
            CHECK.check_versions()
        self.assertEqual(CHECK.results, ["FAIL", "FAIL"])

    def test_current_services_pass(self):
        rtp = 'is_in_profile("as", "$fU") ... ^(1003|agent)(;.*)?$'
        with patch.object(CHECK, "docker", side_effect=[(0, ""), (0, rtp)]):
            CHECK.check_versions()
        self.assertEqual(CHECK.results, ["PASS", "PASS"])


if __name__ == "__main__":
    unittest.main()
