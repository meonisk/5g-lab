"""Перенос локальных правок lab.env стенда в версию ветки."""

import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
MERGE = importlib.import_module("lab_env_merge")

BASE = "# PLMN\nMCC=001\nMNC=01\nIMS_PARENT_INTERFACE=\nPCSCF_IP=pcscf-a\nOLD=1\n"
THEIRS = "# PLMN\nMCC=901\nMNC=70\nIMS_PARENT_INTERFACE=\nPCSCF_IP=pcscf-a\nNEW=2\n"


class LabEnvMerge(unittest.TestCase):
    def test_local_values_survive_and_branch_keeps_its_changes(self):
        mine = BASE.replace("IMS_PARENT_INTERFACE=", "IMS_PARENT_INTERFACE=eno1").replace(
            "PCSCF_IP=pcscf-a", "PCSCF_IP=pcscf-b"
        )
        text, carried, conflicts = MERGE.merge(BASE, mine + "EXTRA=x\n", THEIRS)
        values = MERGE.parse(text)
        self.assertEqual(values["IMS_PARENT_INTERFACE"], "eno1")
        self.assertEqual(values["PCSCF_IP"], "pcscf-b")
        self.assertEqual((values["MCC"], values["NEW"], values["EXTRA"]), ("901", "2", "x"))
        self.assertNotIn("OLD", values)
        self.assertEqual(conflicts, [])
        self.assertEqual(sorted(carried), ["EXTRA", "IMS_PARENT_INTERFACE", "PCSCF_IP"])
        self.assertTrue(text.startswith("# PLMN\n"))

    def test_both_sides_changed_keeps_branch_value(self):
        text, _, conflicts = MERGE.merge(BASE, BASE.replace("MCC=001", "MCC=250"), THEIRS)
        self.assertEqual(MERGE.parse(text)["MCC"], "901")
        self.assertEqual(conflicts, ["MCC"])

    def test_rerun_after_merge_changes_nothing(self):
        mine = THEIRS.replace("IMS_PARENT_INTERFACE=", "IMS_PARENT_INTERFACE=eno1")
        text, carried, conflicts = MERGE.merge(THEIRS, mine, mine)
        self.assertEqual((text, carried, conflicts), (mine, [], []))


if __name__ == "__main__":
    unittest.main()
