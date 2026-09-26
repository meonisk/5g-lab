"""Synthetic lifecycle XML checks without IMS or Docker state changes."""

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/tests/integration"))
from aka_lifecycle_scenario import render

SETTINGS = {
    "IMS_DOMAIN": "ims.example.test",
    "UE1_IMSI": "999990000000101",
    "UE1_IMS_K": "00" * 16,
    "UE1_IMS_OPC": "22" * 16,
    "UE1_IMS_AMF": "8000",
}


class LifecycleScenarioTests(unittest.TestCase):
    def test_initial_refresh_dereg_have_ordered_challenges_and_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = render(Path(tmp) / "lifecycle.xml", SETTINGS, 1)
            xml = path.read_text()
            root = ET.parse(path).getroot()
            sends = root.findall("send")
            self.assertEqual(len(sends), 6)
            self.assertEqual(root.findall("recv")[-1].attrib["response"], "200")
            self.assertEqual(
                [int(item.split("CSeq: ")[1].split()[0]) for item in (node.text for node in sends)],
                list(range(1, 7)),
            )
            self.assertEqual(xml.count('response="401" auth="true"'), 3)
            self.assertEqual(xml.count('response="200"'), 3)
            self.assertEqual(xml.count("aka_OPc=0x"), 3)
            self.assertEqual(xml.count("Expires: 300"), 4)
            self.assertEqual(xml.count("Expires: 0"), 2)
            self.assertEqual(
                [node.attrib["milliseconds"] for node in root.findall("pause")],
                ["20000", "20000", "5000"],
            )
            self.assertTrue(all("Call-ID: [call_id]" in node.text for node in sends))
            self.assertTrue(all("@[local_ip]:[local_port]" in node.text for node in sends))

    def test_bounds_and_private_temp_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lifecycle.xml"
            render(path, SETTINGS | {"SIP_AKA_LIFECYCLE_CHECKPOINT_SECONDS": "3"}, 1)
            self.assertFalse(path.with_name(path.name + ".initial.xml").exists())
            self.assertIn('<pause milliseconds="3000"/>', path.read_text())
            with self.assertRaises(ValueError):
                render(path, SETTINGS | {"SIP_AKA_LIFECYCLE_FINAL_SECONDS": "0"}, 1)
            with self.assertRaises(ValueError):
                render(path, SETTINGS, 3)


if __name__ == "__main__":
    unittest.main()
