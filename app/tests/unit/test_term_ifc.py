"""term_ifc.py: временная услуга вызываемого не меняет остальные правила SIPUE2."""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/tests/integration"))
sys.path.insert(0, str(ROOT / "scripts"))

import provision  # noqa: E402
import term_ifc  # noqa: E402


class TermIfc(unittest.TestCase):
    def setUp(self):
        self.settings = provision.read_env()

    def test_restore_is_the_lab_env_profile(self):
        entry = next(e for e in provision.subscribers(self.settings) if e["name"] == "SIPUE2")
        expected = provision.ifc_xml(self.settings, entry["services"])
        self.assertEqual(term_ifc.ifc(self.settings, with_term=False), expected)

    def test_install_adds_one_terminating_rule_last(self):
        plain = term_ifc.ifc(self.settings, with_term=False)
        with_term = term_ifc.ifc(self.settings, with_term=True)
        self.assertTrue(with_term.startswith(plain.replace(provision.IFC_TAIL, "")))
        self.assertEqual(with_term.count("<SessionCase>1</SessionCase>"), 1)
        self.assertEqual(plain.count("<SessionCase>1</SessionCase>"), 0)
        priorities = [int(p) for p in re.findall(r"<Priority>(\d+)</Priority>", with_term)]
        self.assertEqual(max(priorities), term_ifc.TERM_PRIORITY)
        self.assertIn(provision.as_server(self.settings, provision.NUMBERS_HOST), with_term)


if __name__ == "__main__":
    unittest.main()
