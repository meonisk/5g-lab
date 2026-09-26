"""Shareable evidence must not expose protocol payload or authentication data."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/research/tools"))

from ims_research.privacy import Pseudonymizer


class ProtocolPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.redactor = Pseudonymizer(b"x" * 32, {})

    def test_folded_sip_auth_and_sdp_are_removed(self):
        raw = (
            "INFO service ready\nREGISTER sip:example.test SIP/2.0\n"
            "Authorization: Digest username=alice, response=abcdef123456\n"
            "  opaque=supersecret\nContent-Type: application/sdp\n"
            "m=audio 49170 RTP/AVP 0\na=rtpmap:0 PCMU/8000\n"
            "INFO service remains ready\n"
        )
        result = self.redactor.shareable_log(raw)
        self.assertIn("PROTOCOL_CONTENT_REMOVED", result)
        self.assertIn("sip_register: 1", result)
        for secret in ("alice", "abcdef123456", "supersecret", "49170", "PCMU/8000"):
            self.assertNotIn(secret, result)

    def test_diameter_vectors_and_hex_dump_are_removed(self):
        raw = "Diameter auth vector RAND=0123456789 XRES=deadbeef\nhex dump: 00 aa bb\n"
        result = self.redactor.shareable_log(raw)
        self.assertIn("diameter_mention: 1", result)
        self.assertNotIn("deadbeef", result)
        self.assertNotIn("00 aa bb", result)

    def test_protocol_source_is_reduced_even_without_recognized_marker(self):
        raw = "unknown wire payload\n  folded secret key=badvalue\n"
        result = self.redactor.shareable_log(raw, source="lab-scscf")
        self.assertIn("PROTOCOL_CONTENT_REMOVED", result)
        self.assertNotIn("badvalue", result)

    def test_non_protocol_event_still_pseudonymized(self):
        raw = "PDU Session establishment is successful for imsi-999990000000001"
        result = self.redactor.shareable_log(raw, source="lab-ue1")
        self.assertIn("PDU Session establishment is successful", result)
        self.assertNotIn("999990000000001", result)


if __name__ == "__main__":
    unittest.main()
