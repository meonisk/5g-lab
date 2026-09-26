"""Synthetic SIPp unregistered-callee templates, without a live IMS stand."""

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/tests/integration"))

from aka_unregistered_scenarios import render_callee, render_caller

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


class UnregisteredScenarioTests(unittest.TestCase):
    def test_dereg_and_expiry_keep_callee_process_alive(self):
        with tempfile.TemporaryDirectory() as tmp:
            dereg = render_callee(Path(tmp) / "dereg.xml", SETTINGS, 2, "deregister")
            expired = render_callee(Path(tmp) / "expire.xml", SETTINGS, 2, "expire")
            dereg_tree = ET.parse(dereg).getroot()
            expiry_tree = ET.parse(expired).getroot()
            self.assertEqual(len(dereg_tree.findall("send")), 4)
            self.assertEqual(len(expiry_tree.findall("send")), 2)
            self.assertEqual(dereg.read_text().count("Expires: 0"), 2)
            self.assertEqual(
                [p.attrib["milliseconds"] for p in dereg_tree.findall("pause")], ["5000", "420000"]
            )
            self.assertEqual(expired.read_text().count("Expires: 30"), 2)
            self.assertNotIn("Expires: 300", expired.read_text())
            self.assertEqual(expiry_tree.findall("pause")[-1].attrib["milliseconds"], "420000")
            self.assertTrue(all("Call-ID: [call_id]" in s.text for s in dereg_tree.findall("send")))

    def test_caller_uses_fresh_call_and_transaction_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = render_caller(Path(tmp), SETTINGS, 1)
            root = ET.parse(path).getroot()
            xml = path.read_text()
            invite, ack = [node.text for node in root.findall("send")][-2:]
            self.assertIn(f"INVITE sip:{SETTINGS['UE2_IMSI']}@{SETTINGS['IMS_DOMAIN']}", invite)
            self.assertIn(f"ACK sip:{SETTINGS['UE2_IMSI']}@{SETTINGS['IMS_DOMAIN']}", ack)
            branch = "branch=z9hG4bK-[pid]-[call_number]-invite"
            self.assertIn(branch, invite)
            self.assertIn(branch, ack)
            self.assertIn("CSeq: 1 ACK", ack)
            self.assertIn("[peer_tag_param]", ack)
            self.assertIn('response="404"', xml)
            self.assertIn('milliseconds="5000"', xml)
            self.assertIn('<nop next="2" test="registered"/>', xml)

    def test_status_and_duration_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = render_caller(Path(tmp), SETTINGS, 2, 480)
            self.assertIn('response="480"', path.read_text())
            with self.assertRaises(ValueError):
                render_caller(Path(tmp), SETTINGS, 1, 503)
            with self.assertRaises(ValueError):
                render_callee(Path(tmp) / "x.xml", SETTINGS, 1, "unknown")
            with self.assertRaises(ValueError):
                render_callee(
                    Path(tmp) / "x.xml", SETTINGS | {"SIP_AKA_EXPIRY_SECONDS": "0"}, 1, "expire"
                )


if __name__ == "__main__":
    unittest.main()
