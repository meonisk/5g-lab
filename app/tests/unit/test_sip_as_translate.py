"""translate AS: нога B через S-CSCF, 180 до ответа UE2, ответ UE1 после 200 UE2, пара в AI."""

import re
import unittest

from sip_fakes import (
    CALLEE,
    CALLER,
    DOMAIN,
    ENV,
    RTP_A,
    RTP_B,
    RTP_IP,
    SCSCF,
    SipCase,
    invite,
    load_sip_as,
    response,
    sdp,
)

load_sip_as()
from ims_sip.core import b2bua

CALLEE_CONTACT = f"<sip:{CALLEE}@192.0.2.20:5060>"
TERM_RR = (f"<sip:mt@scscf.{DOMAIN}:{SCSCF[1]};lr>",)


def call_id_of(message):
    return re.search(r"(?m)^Call-ID: (.+)$", message).group(1).strip()


class TranslateCase(SipCase):
    def start_call(self, call_id="tr-1", target=CALLEE, caller=CALLER):
        message = invite(target, call_id, route_host="translate.as", caller=caller)
        self.route_request(message, SCSCF)
        return self.requests("INVITE")[-1]

    def answer(self, leg_b, status=200, reason="OK", ip=RTP_IP):
        body = sdp(ip, RTP_B) if status == 200 else ""
        message = response(
            leg_b,
            status,
            reason,
            to_tag="tb1",
            body=body,
            contact=CALLEE_CONTACT,
            record_routes=TERM_RR,
        )
        self.route_response(message)


class LegB(TranslateCase):
    def test_caller_gets_trying_and_leg_b_goes_to_scscf(self):
        self.start_call()
        self.assertEqual(self.statuses(), [100])
        [(message, destination)] = [(m, d) for m, d in self.sent() if m.startswith("INVITE ")]
        self.assertEqual(destination, SCSCF)
        self.assertTrue(message.startswith(f"INVITE sip:{CALLEE}@{DOMAIN} SIP/2.0"))

    def test_leg_b_has_new_call_id_and_from_tag(self):
        leg_b = self.start_call()
        self.assertRegex(call_id_of(leg_b), r"^b2b-[0-9a-f]{24}$")
        from_value = re.search(r"(?m)^From: (.+)$", leg_b).group(1)
        self.assertIn(f"<sip:{CALLER}@{DOMAIN}>", from_value)
        self.assertNotIn("tag=fa1", from_value)

    def test_leg_b_returns_to_scscf_with_isc_route(self):
        leg_b = self.start_call()
        self.assertRegex(leg_b, r"(?m)^Route: <sip:iscmark@scscf\.")
        self.assertNotIn("translate.as.", leg_b)
        self.assertIn(f"P-Asserted-Identity: <sip:{CALLER}@{DOMAIN}>", leg_b)

    def test_leg_b_offers_voice_agent_media(self):
        leg_b = self.start_call()
        self.assertIn(f"m=audio {ENV['VOICE_AGENT_RTP_PORT']} RTP/AVP 0", leg_b)
        self.assertIn(f"c=IN IP4 {ENV['VOICE_AGENT_IP']}", leg_b)

    def test_ringing_is_sent_once(self):
        leg_b = self.start_call()
        for status, reason in ((180, "Ringing"), (180, "Ringing"), (183, "Session Progress")):
            self.route_response(response(leg_b, status, reason, to_tag="tb1"))
        self.assertEqual(self.statuses(), [100, 180])
        self.assertEqual(self.http.posted("voice.test/calls"), [])

    def test_star_prefix_is_stripped_for_leg_b(self):
        leg_b = self.start_call("tr-star", target=f"*{CALLEE}")
        self.assertTrue(leg_b.startswith(f"INVITE sip:{CALLEE}@{DOMAIN} SIP/2.0"))
        self.assertIn(f"To: <sip:{CALLEE}@{DOMAIN}>", leg_b)


class Answer(TranslateCase):
    def test_answer_acks_leg_b_and_answers_caller(self):
        self.answer(self.start_call())
        ack = self.requests("ACK")[-1]
        self.assertTrue(ack.startswith(f"ACK sip:{CALLEE}@192.0.2.20:5060 SIP/2.0"))
        self.assertIn("tag=tb1", ack)
        self.assertIn("CSeq: 1 ACK", ack)
        self.assertIn(f"Route: {TERM_RR[0]}", ack)
        final = [m for m, _ in self.sent() if m.startswith("SIP/2.0 200")][-1]
        self.assertIn("Call-ID: tr-1", final)
        self.assertIn(f"m=audio {ENV['VOICE_AGENT_RTP_PORT']} RTP/AVP 0", final)
        self.assertIn("Contact: <sip:b2bua@", final)

    def test_answer_binds_both_legs_with_languages(self):
        leg_b = self.start_call()
        self.answer(leg_b)
        b = call_id_of(leg_b)
        self.assertEqual(
            self.http.posted("voice.test/calls"),
            [
                {
                    "call_id": "tr-1",
                    "remote_ip": RTP_IP,
                    "remote_port": RTP_A,
                    "service_mode": "interpret_ru",
                },
                {
                    "call_id": b,
                    "remote_ip": RTP_IP,
                    "remote_port": RTP_B,
                    "service_mode": "interpret_en",
                },
            ],
        )
        legs = [{"call_id": "tr-1", "language": "ru"}, {"call_id": b, "language": "en"}]
        self.assertEqual(self.http.posted("ai.test/pairs"), [{"legs": legs}])
        self.assertIn(f"AS translate answered call_id=tr-1 leg_b={b} languages=ru-en", self.log())

    def test_caller_is_answered_only_after_callee(self):
        leg_b = self.start_call()
        self.assertNotIn(200, self.statuses())
        self.answer(leg_b)
        self.assertEqual(self.statuses().count(200), 1)

    def test_repeated_200_is_acked_again(self):
        leg_b = self.start_call()
        self.answer(leg_b)
        self.answer(leg_b)
        self.assertEqual(len(self.requests("ACK")), 2)
        self.assertEqual(self.statuses().count(200), 1)

    def test_voice_agent_failure_hangs_up_leg_b_and_rejects_caller(self):
        leg_b = self.start_call()
        self.http.fail.add("voice.test/calls")
        self.answer(leg_b)
        self.assertEqual(len(self.requests("BYE")), 1)
        self.assertEqual(self.statuses()[-1], 500)
        self.assertIsNone(b2bua.find("tr-1"))
        self.assertIn("AS b2bua answer failed call_id=tr-1", self.log())

    def test_unanchored_answer_is_rejected(self):
        leg_b = self.start_call()
        self.answer(leg_b, ip="198.51.100.9")
        self.assertEqual(len(self.requests("BYE")), 1)
        self.assertEqual(self.statuses()[-1], 500)
        self.assertEqual(self.http.posted("voice.test/calls"), [])


class FailedLegB(TranslateCase):
    def test_final_failure_is_relayed_to_caller(self):
        failures = ((486, "Busy Here"), (480, "Temporarily Unavailable"), (408, "Request Timeout"))
        for status, reason in failures:
            with self.subTest(status=status):
                self.runtime.sock.reset_mock()
                leg_b = self.start_call(f"tr-{status}")
                self.answer(leg_b, status, reason)
                ack = self.requests("ACK")[-1]
                branch = re.search(r"branch=(z9hG4bK-b2b-[0-9a-f]+)", leg_b).group(1)
                self.assertIn(branch, ack)
                self.assertIn("CSeq: 1 ACK", ack)
                self.assertIn("tag=tb1", ack)
                self.assertEqual(self.statuses()[-1], status)
                self.assertIn(f"SIP/2.0 {status} {reason}", self.sent()[-2][0] + self.sent()[-1][0])
                self.assertIsNone(b2bua.find(f"tr-{status}"))
                self.assertEqual(self.http.posted("voice.test/calls"), [])


if __name__ == "__main__":
    unittest.main()
