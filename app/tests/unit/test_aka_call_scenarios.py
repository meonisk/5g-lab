"""Synthetic, offline checks for continuous SIPp client templates."""

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/tests/integration"))
from aka_call_scenarios import render_pair

SETTINGS = {
    "IMS_DOMAIN": "ims.example.test",
    "UE1_IMSI": "999990000000101",
    "UE2_IMSI": "999990000000102",
    "UE1_IMS_K": "00" * 16,
    "UE2_IMS_K": "11" * 16,
    "UE1_IMS_OPC": "22" * 16,
    "UE2_IMS_OPC": "33" * 16,
    "UE1_IMS_AMF": "8000",
    "UE2_IMS_AMF": "8000",
}


class ContinuousScenarioTests(unittest.TestCase):
    def test_pair_has_separate_register_and_call_contexts(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = render_pair(Path(tmp), SETTINGS)
            caller = paths["caller"].read_text()
            callee = paths["callee"].read_text()
            ooc = paths["callee_ooc"].read_text()
            for path in paths.values():
                ET.parse(path)

            self.assertEqual(caller.count("REGISTER sip:"), 2)
            self.assertEqual(callee.count("REGISTER sip:"), 2)
            self.assertIn("aka_OPc=0x", caller)
            self.assertIn('<User variables="registered,service_route"/>', caller)
            self.assertIn('<nop next="2" test="registered"/>', caller)
            self.assertIn(f"INVITE sip:{SETTINGS['UE2_IMSI']}@{SETTINGS['IMS_DOMAIN']}", caller)
            self.assertIn("Route: [$service_route]", caller)
            self.assertIn("[routes]", caller)
            self.assertIn("PCMU/8000", caller)
            self.assertNotIn("INVITE sip:", callee)
            self.assertIn('<recv request="INVITE" rrs="true"/>', ooc)
            self.assertIn('<recv request="ACK"/>', ooc)
            self.assertIn('<recv request="BYE"', ooc)
            self.assertIn("[last_Record-Route:]", ooc)
            self.assertNotIn("aka_K", ooc)

    def test_reverse_direction_and_config_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = render_pair(Path(tmp), SETTINGS, caller_ue=2)
            self.assertIn(
                f"INVITE sip:{SETTINGS['UE1_IMSI']}@{SETTINGS['IMS_DOMAIN']}",
                paths["caller"].read_text(),
            )
            with self.assertRaises(ValueError):
                render_pair(Path(tmp), SETTINGS | {"SIP_AKA_CALL_SECONDS": "0"})
            with self.assertRaises(ValueError):
                render_pair(Path(tmp), SETTINGS, caller_ue=3)


if __name__ == "__main__":
    unittest.main()
