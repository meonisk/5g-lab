"""Synthetic rejected-INVITE transaction checks without private SIP traces."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/tests/integration"))
from aka_rejection_trace import validate_inactive_callee, validate_rejection
from test_aka_lifecycle_trace import CONTACT, authorization
from test_aka_lifecycle_trace import packet as lifecycle_packet
from test_aka_trace import exchange


def packet(direction, start, method, *, call_id="dialog", branch="z9hG4bK-one", to_tag=""):
    to = "<sip:bob@example.test>" + (f";tag={to_tag}" if to_tag else "")
    contact = "Contact: <sip:alice@192.0.2.5:5060>\r\n" if method == "INVITE" else ""
    return (
        f"-------\nUDP message {direction}\n\n{start}\r\n"
        "Via: SIP/2.0/UDP 192.0.2.5:5060;branch="
        f"{branch}\r\nFrom: <sip:alice@example.test>;tag=from-one\r\n"
        f"To: {to}\r\nCall-ID: {call_id}\r\nCSeq: 1 {method}\r\n"
        f"{contact}Content-Length: 0\r\n\r\n"
    )


def trace(*, status=404, provisional=True):
    return exchange() + "".join(
        (
            packet("sent", "INVITE sip:bob@example.test SIP/2.0", "INVITE"),
            packet("received", "SIP/2.0 100 Trying", "INVITE") if provisional else "",
            packet("received", f"SIP/2.0 {status} Rejected", "INVITE", to_tag="to-one"),
            packet("sent", "ACK sip:bob@example.test SIP/2.0", "ACK", to_tag="to-one"),
        )
    )


def check(value, expected_status=404):
    return validate_rejection(
        value,
        expected_status=expected_status,
        local_imsi="alice",
        peer_imsi="bob",
        domain="example.test",
        local_ip="192.0.2.5",
        local_port=5060,
    )


def inactive_trace(*, deregister=False, expiry=30):
    packets = [
        lifecycle_packet(
            "REGISTER sip:example.test SIP/2.0",
            1,
            contact=CONTACT,
            expires=str(expiry),
            auth=authorization("", ""),
        ),
        lifecycle_packet(
            "SIP/2.0 401 Unauthorized",
            1,
            direction="received",
            challenge='Digest nonce="n1", algorithm=AKAv1-MD5',
        ),
        lifecycle_packet(
            "REGISTER sip:example.test SIP/2.0",
            2,
            contact=CONTACT,
            expires=str(expiry),
            auth=authorization("n1", "r1"),
        ),
        lifecycle_packet(
            "SIP/2.0 200 OK",
            2,
            direction="received",
            contact=CONTACT + f";expires={expiry}",
        ),
    ]
    if deregister:
        packets.extend(
            (
                lifecycle_packet(
                    "REGISTER sip:example.test SIP/2.0",
                    3,
                    contact=CONTACT,
                    expires="0",
                    auth=authorization("", ""),
                ),
                lifecycle_packet(
                    "SIP/2.0 401 Unauthorized",
                    3,
                    direction="received",
                    challenge='Digest nonce="n2", algorithm=AKAv1-MD5',
                ),
                lifecycle_packet(
                    "REGISTER sip:example.test SIP/2.0",
                    4,
                    contact=CONTACT,
                    expires="0",
                    auth=authorization("n2", "r2"),
                ),
                lifecycle_packet(
                    "SIP/2.0 200 OK",
                    4,
                    direction="received",
                    contact=CONTACT + ";expires=0",
                ),
            )
        )
    return "".join(packets)


def check_inactive(value, mode):
    return validate_inactive_callee(
        value,
        mode=mode,
        local_imsi="alice",
        domain="example.test",
        local_ip="192.0.2.5",
        local_port=5060,
    )


class RejectionTraceTests(unittest.TestCase):
    def test_inactive_callee_deregistration_and_passive_expiry(self):
        self.assertEqual(check_inactive(inactive_trace(), "expire")["status"], "PASS")
        self.assertEqual(
            check_inactive(inactive_trace(deregister=True), "deregister")["status"], "PASS"
        )

    def test_inactive_callee_rejects_invite_or_stale_binding(self):
        valid = inactive_trace(deregister=True)
        self.assertEqual(
            check_inactive(
                valid + packet("received", "INVITE sip:alice@example.test SIP/2.0", "INVITE"),
                "deregister",
            )["status"],
            "FAIL",
        )
        self.assertEqual(check_inactive(inactive_trace(expiry=300), "expire")["status"], "FAIL")
        self.assertEqual(
            check_inactive(valid.replace(";expires=0", ";expires=30"), "deregister")["status"],
            "FAIL",
        )
        self.assertEqual(
            check_inactive(
                valid.replace('nonce="n2", response="r2"', 'nonce="n1", response="r2"'),
                "deregister",
            )["status"],
            "FAIL",
        )

    def test_bound_rejection_with_or_without_trying(self):
        for provisional in (False, True):
            with self.subTest(provisional=provisional):
                result = check(trace(provisional=provisional))
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(result["provisional_100_count"], int(provisional))
                self.assertNotIn("alice", str(result))

    def test_wrong_final_or_missing_ack_fails(self):
        self.assertEqual(check(trace(status=480))["status"], "FAIL")
        self.assertEqual(check(trace(status=480), expected_status=480)["status"], "PASS")
        self.assertEqual(
            check(trace().split("-------\nUDP message sent\n\nACK")[0])["status"], "FAIL"
        )
        self.assertEqual(
            check(trace().replace("ACK sip:bob@example.test", "ACK sip:other@example.test"))[
                "status"
            ],
            "FAIL",
        )

    def test_transaction_and_identity_substitutions_fail(self):
        valid = trace()
        for old, new in (
            ("CSeq: 1 ACK", "CSeq: 2 ACK"),
            (";tag=to-one", ";tag=other"),
            ("branch=z9hG4bK-one", "branch=z9hG4bK-other"),
            ("Call-ID: dialog", "Call-ID: foreign"),
            ("Contact: <sip:alice@192.0.2.5:5060>", "Contact: <sip:alice@192.0.2.6:5060>"),
        ):
            with self.subTest(field=old):
                if "to-one" in old or "branch=" in old or "Call-ID" in old:
                    changed = valid[::-1].replace(old[::-1], new[::-1], 1)[::-1]
                else:
                    changed = valid.replace(old, new, 1)
                self.assertEqual(check(changed)["status"], "FAIL")

    def test_no_extra_invite_200_or_bye(self):
        self.assertEqual(
            check(trace() + packet("sent", "BYE sip:bob@example.test SIP/2.0", "BYE"))["status"],
            "FAIL",
        )
        self.assertEqual(
            check(trace() + packet("received", "SIP/2.0 200 OK", "INVITE"))["status"], "FAIL"
        )
        self.assertEqual(
            check(trace().replace("Call-ID: dialog", "Call-ID: call-secret"))["status"], "FAIL"
        )


if __name__ == "__main__":
    unittest.main()
