"""Phone offers must not silently negotiate an unoffered AI codec."""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "phone_sdp", ROOT / "app/services/sip-as/ims_sip/sdp.py"
)
SDP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SDP)


def offer(media="m=audio 4000 RTP/AVP 0", extra="", headers=""):
    return (
        "INVITE sip:ai@example.test SIP/2.0\r\n"
        "Content-Type: application/sdp\r\n" + headers + "\r\n"
        "v=0\r\nc=IN IP4 192.0.2.1\r\n" + media + "\r\n" + extra
    )


class PhoneSdp(unittest.TestCase):
    def test_static_and_explicit_pcmu(self):
        for extra in ("", "a=rtpmap:0 PCMU/8000\r\n", "a=rtpmap:0 PCMU/8000/1\r\n"):
            self.assertTrue(SDP.accepts_pcmu(offer(extra=extra)))

    def test_amr_only_and_dynamic_pcmu_need_interworking(self):
        for mapping in ("AMR/8000", "AMR-WB/16000", "PCMU/8000"):
            self.assertFalse(
                SDP.accepts_pcmu(offer("m=audio 4000 RTP/AVP 96", f"a=rtpmap:96 {mapping}\r\n"))
            )

    def test_invalid_media_is_rejected(self):
        for media in (
            "m=audio 0 RTP/AVP 0",
            "m=audio 70000 RTP/AVP 0",
            "m=audio 4000 RTP/SAVP 0",
            "m=video 4000 RTP/AVP 0",
        ):
            self.assertFalse(SDP.accepts_pcmu(offer(media)))
        self.assertFalse(SDP.accepts_pcmu(offer(extra="a=rtpmap:0 AMR/8000\r\n")))
        self.assertFalse(SDP.accepts_pcmu(offer(extra="m=video 4002 RTP/AVP 96\r\n")))

    def test_required_phone_features_are_not_silently_accepted(self):
        for option in ("100rel", "precondition", "timer, precondition"):
            self.assertFalse(SDP.accepts_pcmu(offer(headers=f"Require: {option}\r\n")))
        self.assertFalse(SDP.accepts_pcmu(offer(extra="a=des:qos mandatory local sendrecv\r\n")))
        self.assertFalse(SDP.accepts_pcmu(offer(extra="a=inactive\r\n")))

    def test_header_cannot_smuggle_codec(self):
        self.assertFalse(
            SDP.accepts_pcmu(
                offer("m=audio 4000 RTP/AVP 96", headers="X-Fake: m=audio 4000 RTP/AVP 0\r\n")
            )
        )


if __name__ == "__main__":
    unittest.main()
