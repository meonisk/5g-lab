"""Offline SIPp dialog trace contract after successful AKA registration."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/tests/integration"))
from aka_dialog_trace import extract_remote_media, split_registration, validate_dialog


def packet(
    direction, start, cseq, *, contact="", sdp="", call_id="dialog-one", to_tag="", from_tag="a"
):
    from_uri = f"<sip:alice@example.test>;tag={from_tag}"
    to_uri = "<sip:bob@example.test>" + (f";tag={to_tag}" if to_tag else "")
    headers = [
        f"Call-ID: {call_id}",
        f"CSeq: {cseq}",
        f"From: {from_uri}",
        f"To: {to_uri}",
        "Via: SIP/2.0/UDP 192.0.2.5:5060;branch=one",
    ]
    if contact:
        headers.append(f"Contact: <sip:{contact}>")
    if sdp:
        headers.append("Content-Type: application/sdp")
    headers.append(f"Content-Length: {len(sdp.encode())}")
    return (
        f"-------\nUDP message {direction}\n\n{start}\r\n"
        + "\r\n".join(headers)
        + "\r\n\r\n"
        + sdp
        + "\r\n"
    )


def media(ip, port):
    return f"v=0\r\nc=IN IP4 {ip}\r\nm=audio {port} RTP/AVP 0\r\na=rtpmap:0 PCMU/8000\r\n"


def caller_trace():
    registration = packet(
        "sent", "REGISTER sip:example.test SIP/2.0", "1 REGISTER", call_id="reg-one"
    )
    return registration + "".join(
        (
            packet(
                "sent",
                "INVITE sip:bob@example.test SIP/2.0",
                "1 INVITE",
                contact="alice@192.0.2.5:5060",
                sdp=media("192.0.2.5", 4000),
            ),
            packet("received", "SIP/2.0 100 Trying", "1 INVITE"),
            packet(
                "received",
                "SIP/2.0 200 OK",
                "1 INVITE",
                to_tag="b",
                contact="bob@192.0.2.6:5060",
                sdp=media("192.0.2.6", 4002),
            ),
            packet("sent", "ACK sip:bob@example.test SIP/2.0", "1 ACK", to_tag="b"),
            packet("sent", "BYE sip:bob@example.test SIP/2.0", "2 BYE", to_tag="b"),
            packet("received", "SIP/2.0 200 OK", "2 BYE", to_tag="b"),
        )
    )


def callee_trace():
    registration = packet(
        "sent", "REGISTER sip:example.test SIP/2.0", "1 REGISTER", call_id="reg-two"
    )
    return registration + "".join(
        (
            packet(
                "received",
                "INVITE sip:bob@example.test SIP/2.0",
                "1 INVITE",
                contact="alice@192.0.2.5:5060",
                sdp=media("192.0.2.5", 4000),
            ),
            packet(
                "sent",
                "SIP/2.0 200 OK",
                "1 INVITE",
                to_tag="b",
                contact="bob@192.0.2.6:5060",
                sdp=media("192.0.2.6", 4000),
            ),
            packet("received", "ACK sip:bob@example.test SIP/2.0", "1 ACK", to_tag="b"),
            packet("received", "BYE sip:bob@example.test SIP/2.0", "2 BYE", to_tag="b"),
            packet("sent", "SIP/2.0 200 OK", "2 BYE", to_tag="b"),
        )
    )


class AkaDialogTraceTests(unittest.TestCase):
    def check(self, trace):
        return validate_dialog(
            trace,
            role="caller",
            local_imsi="alice",
            peer_imsi="bob",
            domain="example.test",
            local_ip="192.0.2.5",
            local_port=5060,
            registration_ok=True,
        )

    def test_caller_flow_and_remote_media(self):
        trace = caller_trace()
        prefix, suffix = split_registration(trace)
        self.assertIn("REGISTER", prefix)
        self.assertTrue(suffix.startswith("UDP message sent"))
        self.assertEqual(self.check(trace)["status"], "PASS")
        self.assertEqual(extract_remote_media(suffix, "caller"), ("192.0.2.6", 4002))

    def test_prior_registration_and_dialog_identity_required(self):
        self.assertEqual(
            self.check(caller_trace().replace("reg-one", "dialog-one"))["status"], "FAIL"
        )
        self.assertEqual(
            validate_dialog(
                caller_trace(),
                role="caller",
                local_imsi="alice",
                peer_imsi="bob",
                domain="example.test",
                local_ip="192.0.2.5",
                local_port=5060,
                registration_ok=False,
            )["status"],
            "FAIL",
        )

    def test_wrong_direction_sdp_and_bye_fail(self):
        valid = caller_trace()
        self.assertEqual(
            self.check(valid.replace("m=audio 4002 RTP/AVP 0", "m=audio 4002 RTP/AVP 8"))["status"],
            "FAIL",
        )
        self.assertEqual(self.check(valid.replace("2 BYE", "3 BYE"))["status"], "FAIL")
        self.assertEqual(
            self.check(
                valid.replace(
                    "SIP/2.0 200 OK\r\nCall-ID: dialog-one", "SIP/2.0 200 OK\r\nCall-ID: foreign", 1
                )
            )["status"],
            "FAIL",
        )
        self.assertEqual(
            self.check(
                valid.replace(
                    "To: <sip:bob@example.test>;tag=b", "To: <sip:bob@example.test>;tag=foreign", 1
                )
            )["status"],
            "FAIL",
        )
        self.assertEqual(
            self.check(
                valid.replace(
                    "UDP message received\n\nSIP/2.0 200 OK",
                    "UDP message sent\n\nSIP/2.0 200 OK",
                    1,
                )
            )["status"],
            "FAIL",
        )

    def test_callee_flow_and_remote_offer(self):
        trace = callee_trace()
        result = validate_dialog(
            trace,
            role="callee",
            local_imsi="bob",
            peer_imsi="alice",
            domain="example.test",
            local_ip="192.0.2.6",
            local_port=5060,
            registration_ok=True,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            extract_remote_media(split_registration(trace)[1], "callee"),
            ("192.0.2.5", 4000),
        )

    def test_proxy_via_chain_keeps_request_branch(self):
        valid = caller_trace()
        expanded = valid.replace(
            "Via: SIP/2.0/UDP 192.0.2.5:5060;branch=one\r\nContact: <sip:bob",
            "Via: SIP/2.0/UDP proxy.example;branch=proxy, "
            "SIP/2.0/UDP 192.0.2.5:5060;branch=one\r\nContact: <sip:bob",
            1,
        )
        self.assertEqual(self.check(expanded)["status"], "PASS")
        foreign = expanded.replace(
            "branch=one\r\nContact: <sip:bob", "branch=foreign\r\nContact: <sip:bob", 1
        )
        self.assertEqual(self.check(foreign)["status"], "FAIL")

    def test_branch_prefix_collision_is_rejected(self):
        trace = caller_trace().replace(
            "branch=one\r\nContact: <sip:bob",
            "branch=one-extra\r\nContact: <sip:bob",
            1,
        )
        self.assertEqual(self.check(trace)["status"], "FAIL")

    def test_repeated_via_headers_preserve_owned_branch(self):
        trace = caller_trace().replace(
            "Via: SIP/2.0/UDP 192.0.2.5:5060;branch=one\r\nContact: <sip:bob",
            "Via: SIP/2.0/UDP 192.0.2.5:5060;branch=one\r\n"
            "Via: SIP/2.0/UDP proxy.example;branch=proxy\r\nContact: <sip:bob",
            1,
        )
        self.assertEqual(self.check(trace)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
