"""Registration refresh and deregistration trace checkpoints."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/tests/integration"))
from aka_lifecycle_trace import checkpoint, validate_lifecycle

CONTACT = "<sip:alice@192.0.2.5:5060>"


def authorization(nonce, response):
    return (
        f'Digest username="alice@example.test", realm="example.test", '
        f'uri="sip:example.test", nonce="{nonce}", response="{response}", algorithm=AKAv1-MD5'
    )


def packet(
    start,
    cseq,
    *,
    direction="sent",
    call_id="lifecycle",
    contact="",
    expires="",
    auth="",
    challenge="",
):
    headers = [
        f"Call-ID: {call_id}",
        f"CSeq: {cseq} REGISTER",
        "From: <sip:alice@example.test>;tag=one",
        "To: <sip:alice@example.test>",
        "Via: SIP/2.0/UDP 192.0.2.5:5060;branch=one",
    ]
    if contact:
        headers.append(f"Contact: {contact}")
    if expires:
        headers.append(f"Expires: {expires}")
    if auth:
        headers.append(f"Authorization: {auth}")
    if challenge:
        headers.append(f"WWW-Authenticate: {challenge}")
    headers.append("Content-Length: 0")
    return f"------\nUDP message {direction}\n\n{start}\r\n" + "\r\n".join(headers) + "\r\n\r\n"


def exchange(
    *, refresh_challenge=False, dereg_challenge=False, dereg_expiry="0", call_id="lifecycle"
):
    initial = packet(
        "REGISTER sip:example.test SIP/2.0",
        1,
        contact=CONTACT,
        expires="300",
        call_id=call_id,
        auth=authorization("", ""),
    )
    initial += packet(
        "SIP/2.0 401 Unauthorized",
        1,
        direction="received",
        challenge='Digest nonce="n1", algorithm=AKAv1-MD5',
        call_id=call_id,
    )
    initial += packet(
        "REGISTER sip:example.test SIP/2.0",
        2,
        contact=CONTACT,
        expires="300",
        auth=authorization("n1", "r1"),
        call_id=call_id,
    )
    initial += packet(
        "SIP/2.0 200 OK", 2, direction="received", contact=CONTACT + ";expires=270", call_id=call_id
    )
    refresh = packet(
        "REGISTER sip:example.test SIP/2.0",
        3,
        contact=CONTACT,
        expires="300",
        auth=(authorization("", "") if refresh_challenge else authorization("n1", "r2")),
        call_id=call_id,
    )
    if refresh_challenge:
        refresh += packet(
            "SIP/2.0 401 Unauthorized",
            3,
            direction="received",
            challenge='Digest nonce="n2", algorithm=AKAv1-MD5',
            call_id=call_id,
        )
        refresh += packet(
            "REGISTER sip:example.test SIP/2.0",
            4,
            contact=CONTACT,
            expires="300",
            auth=authorization("n2", "r3"),
            call_id=call_id,
        )
        refresh_cseq = 4
    else:
        refresh_cseq = 3
    refresh += packet(
        "SIP/2.0 200 OK",
        refresh_cseq,
        direction="received",
        contact=CONTACT + ";expires=250",
        call_id=call_id,
    )
    dereg = packet(
        "REGISTER sip:example.test SIP/2.0",
        refresh_cseq + 1,
        contact=CONTACT,
        expires=dereg_expiry,
        auth=(authorization("", "") if dereg_challenge else authorization("n2", "r4")),
        call_id=call_id,
    )
    if dereg_challenge:
        dereg += packet(
            "SIP/2.0 401 Unauthorized",
            refresh_cseq + 1,
            direction="received",
            challenge='Digest nonce="n3", algorithm=AKAv1-MD5',
            call_id=call_id,
        )
        dereg += packet(
            "REGISTER sip:example.test SIP/2.0",
            refresh_cseq + 2,
            contact=CONTACT,
            expires=dereg_expiry,
            auth=authorization("n3", "r5"),
            call_id=call_id,
        )
        dereg_cseq = refresh_cseq + 2
    else:
        dereg_cseq = refresh_cseq + 1
    dereg += packet(
        "SIP/2.0 200 OK",
        dereg_cseq,
        direction="received",
        contact=CONTACT + ";expires=0",
        call_id=call_id,
    )
    return initial, refresh, dereg


class AkaLifecycleTraceTests(unittest.TestCase):
    def check(self, trace):
        return checkpoint(trace, "alice", "example.test", "192.0.2.5", 5060)

    def test_checkpoints_and_direct_refresh(self):
        initial, refresh, dereg = exchange()
        self.assertEqual(self.check(initial)["initial"], "PASS")
        self.assertEqual(self.check(initial)["refresh"], "PENDING")
        self.assertEqual(self.check(initial + refresh)["refresh"], "PASS")
        result = validate_lifecycle(
            initial + refresh + dereg, "alice", "example.test", "192.0.2.5", 5060
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["cseqs"], [1, 2, 3, 4])

    def test_challenged_refresh(self):
        initial, refresh, dereg = exchange(refresh_challenge=True)
        result = self.check(initial + refresh + dereg)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["response_statuses"], [401, 200, 401, 200, 200])

    def test_challenged_deregistration(self):
        initial, refresh, dereg = exchange(refresh_challenge=True, dereg_challenge=True)
        result = self.check(initial + refresh + dereg)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["response_statuses"], [401, 200, 401, 200, 401, 200])

    def test_zero_expiry_and_binding_substitution_fail(self):
        initial, refresh, dereg = exchange()
        self.assertEqual(
            self.check(initial + refresh + dereg.replace("Expires: 0", "Expires: 300"))["status"],
            "FAIL",
        )
        self.assertEqual(
            self.check(
                initial + refresh.replace("Call-ID: lifecycle", "Call-ID: foreign", 1) + dereg
            )["status"],
            "FAIL",
        )
        self.assertEqual(
            self.check(
                initial
                + refresh.replace(
                    "Contact: <sip:alice@192.0.2.5:5060>", "Contact: <sip:alice@192.0.2.9:5060>", 1
                )
                + dereg
            )["status"],
            "FAIL",
        )

    def test_missing_aka_and_nonincreasing_cseq_fail(self):
        initial, refresh, dereg = exchange()
        self.assertEqual(
            self.check(initial.replace("AKAv1-MD5", "MD5") + refresh + dereg)["status"], "FAIL"
        )
        self.assertEqual(
            self.check(initial + refresh.replace("CSeq: 3", "CSeq: 2") + dereg)["status"], "FAIL"
        )

    def test_authorization_identity_and_refresh_expiry_bound(self):
        initial, refresh, dereg = exchange(refresh_challenge=True)
        for before, after in (
            ('username="alice@example.test"', 'username="other@example.test"'),
            ('realm="example.test"', 'realm="foreign.test"'),
            ('uri="sip:example.test"', 'uri="sip:foreign.test"'),
        ):
            with self.subTest(field=before):
                self.assertEqual(
                    self.check(initial + refresh.replace(before, after, 1) + dereg)["status"],
                    "FAIL",
                )
        before, after = refresh.rsplit("Expires: 300", 1)
        changed = before + "Expires: 0" + after
        self.assertEqual(self.check(initial + changed + dereg)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
