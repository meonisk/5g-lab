"""SIP AS как UAS для телефона: 100rel, QoS preconditions, UPDATE и CANCEL.

Runtime подменяется: настоящий модуль открывает UDP-сокет при импорте.
"""

import importlib
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/services/sip-as"))

RTP_IP, VOICE_IP, AS_IP = "192.0.2.10", "192.0.2.20", "192.0.2.30"
PHONE_OFFER = (
    "v=0\r\no=- 1 1 IN IP4 {ip}\r\ns=-\r\nc=IN IP4 {ip}\r\nt=0 0\r\n"
    "m=audio {port} RTP/AVP 0 96\r\na=rtpmap:0 PCMU/8000\r\na=rtpmap:96 AMR/8000\r\n"
    "a=curr:qos local {local}\r\na=curr:qos remote none\r\n"
    "a=des:qos mandatory local sendrecv\r\na=des:qos none remote sendrecv\r\na=sendrecv\r\n"
)


class FakeSocket:
    def __init__(self):
        self.sent = []

    def sendto(self, data, peer):
        self.sent.append(data.decode())


def fake_runtime():
    module = types.ModuleType("ims_sip.runtime")
    module.__dict__.update(
        bind_ip=AS_IP,
        bind_port=5070,
        voice_ip=VOICE_IP,
        voice_rtp_port=41000,
        voice_user="agent",
        rtpengine_ip=RTP_IP,
        rtp_port_min=30000,
        rtp_port_max=30100,
        precondition_timeout=3600.0,
        sip_t1=3600.0,
        sock=FakeSocket(),
        transactions={},
        agent_calls={},
        calls_lock=threading.RLock(),
        service_targets={"1003": "translate", "agent": "translate"},
        service_users={"translate": "agent"},
    )
    return module


def request(method, cseq, body="", extra="", uri="sip:1003@ims.example;user=phone"):
    headers = [
        f"{method} {uri} SIP/2.0",
        "Via: SIP/2.0/UDP 192.0.2.40:6060;branch=z9hG4bK1",
        "From: <sip:2600@ims.example>;tag=phone",
        "To: <sip:1003@ims.example>" + (";tag=x" if method != "INVITE" else ""),
        "Call-ID: call-1",
        f"CSeq: {cseq} {method}",
    ]
    headers += [line for line in extra.split("\r\n") if line]
    if body:
        headers.append("Content-Type: application/sdp")
    headers.append(f"Content-Length: {len(body.encode())}")
    return "\r\n".join(headers) + "\r\n\r\n" + body


class SipAsPreconditions(unittest.TestCase):
    def setUp(self):
        for name in [n for n in sys.modules if n.startswith("ims_sip")]:
            del sys.modules[name]
        self.runtime = fake_runtime()
        sys.modules["ims_sip.runtime"] = self.runtime
        importlib.import_module("ims_sip")
        self.routing = importlib.import_module("ims_sip.routing")
        self.dialog = importlib.import_module("ims_sip.agent_dialog")
        self.pre = importlib.import_module("ims_sip.preconditions")
        self.voice = patch.object(self.dialog, "notify_voice").start()
        patch.object(self.dialog, "notify_adapter").start()
        patch.object(self.dialog, "stop_voice").start()
        patch.object(self.dialog, "stop_adapter").start()
        self.addCleanup(patch.stopall)

    def send(self, message):
        self.runtime.sock.sent.clear()
        self.routing.route_request(message, ("192.0.2.40", 6060))
        return list(self.runtime.sock.sent)

    def offer(self, local="none", port=30010):
        return PHONE_OFFER.format(ip=RTP_IP, port=port, local=local)

    def test_answer_mirrors_segments_and_requests_confirmation(self):
        lines = self.pre.answer_lines(self.offer())
        self.assertIn("a=curr:qos local sendrecv", lines)
        self.assertIn("a=des:qos mandatory remote sendrecv", lines)
        self.assertIn("a=conf:qos remote sendrecv", lines)
        self.assertFalse(self.pre.offerer_ready(self.offer()))
        self.assertTrue(self.pre.offerer_ready(self.offer("sendrecv")))
        self.assertNotIn(
            "a=conf:qos remote sendrecv", self.pre.answer_lines(self.offer("sendrecv"))
        )
        self.assertEqual(self.pre.answer_lines("v=0\r\nm=audio 1 RTP/AVP 0\r\n"), [])

    def test_native_dialer_flow_183_prack_update_then_200(self):
        invite = request("INVITE", 1, self.offer(), "Supported: 100rel, precondition, timer")
        sent = self.send(invite)
        self.assertTrue(sent[0].startswith("SIP/2.0 100"))
        early = sent[1]
        self.assertTrue(early.startswith("SIP/2.0 183"))
        for text in ("Require: 100rel, precondition", "RSeq: 1", "a=conf:qos remote sendrecv"):
            self.assertIn(text, early)
        self.assertIn(f"Contact: <sip:agent@{AS_IP}:5070", early)
        self.voice.assert_not_called()

        sent = self.send(request("PRACK", 2, extra="RAck: 1 1 INVITE"))
        self.assertEqual([m.split("\r\n")[0] for m in sent], ["SIP/2.0 200 OK"])
        self.voice.assert_not_called()

        sent = self.send(request("UPDATE", 3, self.offer("sendrecv")))
        self.assertIn("CSeq: 3 UPDATE", sent[0])
        self.assertIn("a=curr:qos remote sendrecv", sent[0])
        final = sent[1]
        self.assertIn("CSeq: 1 INVITE", final)
        self.assertTrue(final.startswith("SIP/2.0 200 OK"))
        self.assertIn("Content-Length: 0", final)
        self.voice.assert_called_once_with("call-1", RTP_IP, 30010, "translate")

    def test_ready_phone_is_answered_right_after_prack(self):
        self.send(request("INVITE", 1, self.offer("sendrecv"), "Supported: 100rel,precondition"))
        sent = self.send(request("PRACK", 2, extra="RAck: 1 1 INVITE"))
        self.assertEqual(len(sent), 2)
        self.assertIn("CSeq: 1 INVITE", sent[1])

    def test_softphone_without_extensions_keeps_immediate_200(self):
        sent = self.send(request("INVITE", 1, self.offer("sendrecv").replace("a=des", "a=x-des")))
        self.assertTrue(sent[1].startswith("SIP/2.0 200 OK"))
        self.assertIn("m=audio 41000 RTP/AVP 0", sent[1])
        self.assertNotIn("a=curr:qos", sent[1])

    def test_tel_uri_from_s_cscf_reaches_service(self):
        uri = "tel:1003;phone-context=ims.example"
        sent = self.send(request("INVITE", 1, self.offer("sendrecv"), uri=uri))
        self.assertTrue(sent[-1].startswith("SIP/2.0 200 OK"))
        self.assertEqual(self.routing.request_target(f"INVITE {uri} SIP/2.0"), "1003")

    def test_cancel_in_early_dialog_terminates_invite(self):
        self.send(request("INVITE", 1, self.offer(), "Require: 100rel\r\nSupported: precondition"))
        sent = self.send(request("CANCEL", 1))
        self.assertTrue(sent[0].startswith("SIP/2.0 200 OK"))
        self.assertTrue(sent[1].startswith("SIP/2.0 487"))
        self.assertIn("CSeq: 1 INVITE", sent[1])
        self.voice.assert_not_called()

    def test_unknown_required_extension_gets_420(self):
        sent = self.send(request("INVITE", 1, self.offer(), "Require: 100rel, foo"))
        self.assertTrue(sent[1].startswith("SIP/2.0 420"))
        self.assertIn("Unsupported: foo", sent[1])

    def test_unanchored_update_does_not_move_media(self):
        self.send(request("INVITE", 1, self.offer(), "Supported: 100rel, precondition"))
        self.send(request("PRACK", 2, extra="RAck: 1 1 INVITE"))
        moved = PHONE_OFFER.format(ip="198.51.100.9", port=4000, local="sendrecv")
        self.send(request("UPDATE", 3, moved))
        self.voice.assert_called_once_with("call-1", RTP_IP, 30010, "translate")


if __name__ == "__main__":
    unittest.main()
