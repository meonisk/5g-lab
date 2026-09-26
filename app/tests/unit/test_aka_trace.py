"""SIPp AKA trace assessment rejects incomplete or substituted transactions."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/tests/integration"))
from aka_trace import assess, validate_registration


def trying(cseq=1, call_id="call-secret"):
    return (
        "SIP/2.0 100 Trying\r\n"
        f"Call-ID: {call_id}\r\nCSeq: {cseq} REGISTER\r\n"
        "From: <sip:alice@example.test>\r\nTo: <sip:alice@example.test>\r\n"
        "Via: SIP/2.0/UDP 192.0.2.5:5060;branch=one\r\n"
        "Content-Length: 0\r\n\r\n"
    )


def exchange(
    *,
    final=200,
    second_contact="192.0.2.5:5060",
    second_id="call-secret",
    auth=True,
    provisional=False,
):
    first = (
        "REGISTER sip:example.test SIP/2.0\r\n"
        "Via: SIP/2.0/UDP 192.0.2.5:5060;branch=one\r\n"
        "From: <sip:alice@example.test>\r\nTo: <sip:alice@example.test>\r\n"
        "Contact: <sip:alice@192.0.2.5:5060>\r\nCall-ID: call-secret\r\n"
        'Authorization: Digest username="", realm="", nonce="", response="", algorithm=AKAv1-MD5\r\n'
        "CSeq: 1 REGISTER\r\nContent-Length: 0\r\n\r\n"
    )
    challenge = (
        "SIP/2.0 401 Unauthorized\r\nCall-ID: call-secret\r\nCSeq: 1 REGISTER\r\n"
        'WWW-Authenticate: Digest realm="secret", nonce="nonce-secret",\r\n'
        " algorithm=AKAv1-MD5\r\nContent-Length: 0\r\n\r\n"
    )
    second = (
        "REGISTER sip:example.test SIP/2.0\r\n"
        "Via: SIP/2.0/UDP 192.0.2.5:5060;branch=one\r\n"
        "From: <sip:alice@example.test>\r\nTo: <sip:alice@example.test>\r\n"
        f"Contact: <sip:alice@{second_contact}>\r\nCall-ID: {second_id}\r\n"
        "CSeq: 2 REGISTER\r\n"
        + (
            'Authorization: Digest username="alice", realm="example.test", '
            'uri="sip:example.test", algorithm=AKAv1-MD5, '
            'nonce="nonce-secret", response="response-secret"\r\n'
            if auth
            else ""
        )
        + "Content-Length: 0\r\n\r\n"
    )
    response = (
        f"SIP/2.0 {final} Result\r\nCall-ID: call-secret\r\nCSeq: 2 REGISTER\r\n"
        + ("Contact: <sip:alice@192.0.2.5:5060>;expires=270\r\n" if final == 200 else "")
        + "Content-Length: 0\r\n\r\n"
    )
    first_trying = trying() * 2 if provisional else ""
    second_trying = trying(cseq=2) * 2 if provisional else ""
    return (
        "2026-09-22 Sending\n"
        + first
        + first_trying
        + challenge
        + second
        + second_trying
        + response
    )


class AkaTraceTests(unittest.TestCase):
    def test_positive_sequence_passes_without_raw_values_in_metadata(self):
        result = assess(exchange())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["cseqs"], [1, 1, 2, 2])
        self.assertEqual(result["response_statuses"], [401, 200])
        self.assertNotIn("secret", str(result))
        self.assertNotIn("alice", str(result))

    def test_wrong_key_rejects_and_never_accepts_200(self):
        self.assertEqual(assess(exchange(final=403), wrong_key=True)["status"], "PASS")
        self.assertEqual(assess(exchange(final=200), wrong_key=True)["status"], "FAIL")

    def test_identity_contact_and_authorization_required(self):
        for trace in (
            exchange(second_contact="192.0.2.6:5060"),
            exchange(second_id="other-call"),
            exchange(auth=False),
        ):
            with self.subTest(trace=trace[-60:]):
                self.assertEqual(assess(trace)["status"], "FAIL")

    def test_authorized_digest_must_bind_realm_uri_and_algorithm(self):
        valid = exchange()
        for old, new in (
            ('realm="example.test"', 'realm="other.test"'),
            ('uri="sip:example.test"', 'uri="sip:192.0.2.5:5060"'),
            ("algorithm=AKAv1-MD5, nonce", "algorithm=MD5, nonce"),
        ):
            with self.subTest(field=old):
                self.assertEqual(assess(valid.replace(old, new))["status"], "FAIL")

    def test_missing_challenge_and_wrong_cseq_fail(self):
        self.assertEqual(assess(exchange().replace("AKAv1-MD5", "MD5"))["status"], "FAIL")
        self.assertEqual(
            assess(exchange().replace("CSeq: 2 REGISTER", "CSeq: 4 REGISTER"))["status"], "FAIL"
        )

    def test_fixture_identity_and_contact_are_bound(self):
        self.assertEqual(
            validate_registration(exchange(), "alice", "example.test", "192.0.2.5", 5060)["status"],
            "PASS",
        )
        self.assertEqual(
            validate_registration(exchange(), "bob", "example.test", "192.0.2.5", 5060)["status"],
            "FAIL",
        )
        self.assertEqual(
            validate_registration(exchange(), "alice", "example.test", "192.0.2.9", 5060)["status"],
            "FAIL",
        )

    def test_final_200_must_confirm_current_contact(self):
        self.assertEqual(
            assess(
                exchange().replace(
                    "Contact: <sip:alice@192.0.2.5:5060>;expires=270\r\nContent-Length: 0\r\n\r\n",
                    "Content-Length: 0\r\n\r\n",
                )
            )["status"],
            "FAIL",
        )

    def test_transaction_bound_provisional_100s_pass(self):
        result = assess(exchange(provisional=True))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["message_count"], 8)
        self.assertEqual(result["provisional_100_count"], 4)

    def test_foreign_or_wrong_cseq_100_fails(self):
        valid = exchange(provisional=True)
        self.assertEqual(
            assess(
                valid.replace(
                    "Call-ID: call-secret\r\nCSeq: 1 REGISTER\r\nFrom:",
                    "Call-ID: foreign\r\nCSeq: 1 REGISTER\r\nFrom:",
                    1,
                )
            )["status"],
            "FAIL",
        )
        self.assertEqual(
            assess(
                valid.replace(
                    "SIP/2.0 100 Trying\r\nCall-ID: call-secret\r\nCSeq: 1",
                    "SIP/2.0 100 Trying\r\nCall-ID: call-secret\r\nCSeq: 9",
                    1,
                )
            )["status"],
            "FAIL",
        )

    def test_100_after_final_fails(self):
        self.assertEqual(assess(exchange(provisional=True) + trying(cseq=2))["status"], "FAIL")

    def test_wrong_final_contact_fails(self):
        self.assertEqual(
            assess(
                exchange().replace(
                    "Contact: <sip:alice@192.0.2.5:5060>;expires=270\r\nContent-Length: 0\r\n\r\n",
                    "Contact: <sip:alice@192.0.2.9:5060>;expires=270\r\nContent-Length: 0\r\n\r\n",
                )
            )["status"],
            "FAIL",
        )

    def test_positive_requires_nonzero_registration_expiry(self):
        valid = exchange()
        self.assertEqual(assess(valid)["status"], "PASS")
        self.assertEqual(assess(valid.replace(";expires=270", ";expires=0"))["status"], "FAIL")
        self.assertEqual(assess(valid.replace(";expires=270", ";expires=bad"))["status"], "FAIL")
        fallback = valid.replace(";expires=270", "").replace(
            "Contact: <sip:alice@192.0.2.5:5060>\r\nContent-Length: 0\r\n\r\n",
            "Contact: <sip:alice@192.0.2.5:5060>\r\nExpires: 270\r\nContent-Length: 0\r\n\r\n",
        )
        self.assertEqual(assess(fallback)["status"], "PASS")
        self.assertEqual(assess(fallback.replace("Expires: 270", "Expires: 0"))["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
