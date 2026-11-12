"""B2BUA: BYE с каждой стороны, CANCEL до ответа, re-INVITE/UPDATE на своей ноге."""

import re
import unittest

from sip_fakes import (
    CALLEE,
    CALLER,
    DOMAIN,
    ENV,
    RTP_B,
    RTP_IP,
    SCSCF,
    SipCase,
    invite,
    load_sip_as,
    request,
    response,
    sdp,
    to_tag_of,
)

load_sip_as()
from ims_sip.core import b2bua
from ims_sip.core.sip import local_tag

AS_URI = f"sip:b2bua@{ENV['SIP_AS_IP']}:{ENV['SIP_AS_PORT']}"
CALLEE_CONTACT = f"<sip:{CALLEE}@192.0.2.20:5060>"
TERM_RR = (f"<sip:mt@scscf.{DOMAIN}:{SCSCF[1]};lr>",)


def call_id_of(message):
    return re.search(r"(?m)^Call-ID: (.+)$", message).group(1).strip()


def from_tag_of(message):
    return re.search(r"(?m)^From: .*;tag=([0-9a-f]+)", message).group(1)


class Teardown(SipCase):
    def start_call(self, call_id="tr-1"):
        self.route_request(invite(CALLEE, call_id, route_host="translate.as"), SCSCF)
        return self.requests("INVITE")[-1]

    def reply_b(self, leg_b, status, reason):
        body = sdp(RTP_IP, RTP_B) if status == 200 else ""
        self.route_response(
            response(
                leg_b,
                status,
                reason,
                to_tag="tb1",
                body=body,
                contact=CALLEE_CONTACT,
                record_routes=TERM_RR,
            )
        )

    def establish(self):
        leg_b = self.start_call()
        self.reply_b(leg_b, 200, "OK")
        return leg_b, call_id_of(leg_b), from_tag_of(leg_b)

    def cancel_a(self, call_id="tr-1"):
        return request(
            "CANCEL",
            call_id,
            uri=f"sip:{CALLEE}@{DOMAIN}",
            from_user=CALLER,
            from_tag="fa1",
            to_user=CALLEE,
            cseq=1,
            branch="z9hG4bK-a1",
            route_host="translate.as",
        )

    def test_bye_from_caller_hangs_up_callee(self):
        _, b, _ = self.establish()
        bye = request(
            "BYE",
            "tr-1",
            uri=AS_URI,
            from_user=CALLER,
            from_tag="fa1",
            to_user=CALLEE,
            to_tag=local_tag("tr-1"),
        )
        self.route_request(bye, SCSCF)
        self.assertEqual(self.statuses()[-1], 200)
        [sent_bye] = self.requests("BYE")
        self.assertTrue(sent_bye.startswith(f"BYE sip:{CALLEE}@192.0.2.20:5060 SIP/2.0"))
        self.assertIn(f"Call-ID: {b}", sent_bye)
        self.assertIn("CSeq: 2 BYE", sent_bye)
        self.assertIn(f"Route: {TERM_RR[0]}", sent_bye)
        for call_id in ("tr-1", b):
            self.assertEqual(len(self.http.deleted(f"voice.test/calls/{call_id}")), 1)
        self.assertEqual(len(self.http.deleted("ai.test/pairs/tr-1")), 1)
        self.assertIsNone(b2bua.find("tr-1"))
        self.assertIn("AS b2bua ended call_id=tr-1 by=a", self.log())
        self.assertIn("AS translate ended call_id=tr-1", self.log())

    def test_bye_from_callee_hangs_up_caller(self):
        _, b, b_tag = self.establish()
        bye = request(
            "BYE", b, uri=AS_URI, from_user=CALLEE, from_tag="tb1", to_user=CALLER, to_tag=b_tag
        )
        self.route_request(bye, SCSCF)
        [sent_bye] = self.requests("BYE")
        self.assertTrue(sent_bye.startswith(f"BYE sip:{CALLER}@192.0.2.10:5060 SIP/2.0"))
        self.assertIn("Call-ID: tr-1", sent_bye)
        self.assertIn(f"tag={local_tag('tr-1')}", sent_bye)
        self.assertIn("tag=fa1", sent_bye)
        self.assertIn(f"Route: <sip:mo@scscf.{DOMAIN}", sent_bye)
        self.assertIsNone(b2bua.find(b))
        self.assertIn("AS b2bua ended call_id=tr-1 by=b", self.log())

    def test_cancel_before_answer(self):
        leg_b = self.start_call()
        self.route_response(response(leg_b, 180, "Ringing", to_tag="tb1"))
        self.route_request(self.cancel_a(), SCSCF)
        self.assertEqual(self.statuses(), [100, 180, 200, 487])
        [cancel] = self.requests("CANCEL")
        branch = re.search(r"branch=(z9hG4bK-b2b-[0-9a-f]+)", leg_b).group(1)
        self.assertIn(branch, cancel)
        self.assertIn("CSeq: 1 CANCEL", cancel)
        self.assertIsNone(b2bua.find("tr-1"))
        self.reply_b(leg_b, 487, "Request Terminated")
        self.assertEqual(len(self.requests("ACK")), 1)
        self.assertEqual(self.statuses(), [100, 180, 200, 487])
        self.assertEqual(self.http.posted("voice.test/calls"), [])
        self.assertIn("AS b2bua cancelled call_id=tr-1", self.log())

    def test_answer_after_cancel_is_hung_up(self):
        leg_b = self.start_call()
        self.route_response(response(leg_b, 180, "Ringing", to_tag="tb1"))
        self.route_request(self.cancel_a(), SCSCF)
        self.reply_b(leg_b, 200, "OK")
        self.assertEqual(len(self.requests("ACK")), 1)
        self.assertEqual(len(self.requests("BYE")), 1)
        self.assertEqual(self.statuses(), [100, 180, 200, 487])
        self.assertEqual(self.http.posted("voice.test/calls"), [])

    def test_reinvite_is_answered_locally(self):
        _, b, b_tag = self.establish()
        before = len(self.requests("INVITE"))
        reinvite = request(
            "INVITE",
            b,
            uri=AS_URI,
            from_user=CALLEE,
            from_tag="tb1",
            to_user=CALLER,
            to_tag=b_tag,
            cseq=2,
            branch="z9hG4bK-re1",
            body=sdp(RTP_IP, RTP_B),
        )
        self.route_request(reinvite, SCSCF)
        answer = self.sent()[-1][0]
        self.assertTrue(answer.startswith("SIP/2.0 200 OK"))
        self.assertIn(f"m=audio {ENV['VOICE_AGENT_RTP_PORT']} RTP/AVP 0", answer)
        self.assertIn("Contact: <sip:b2bua@", answer)
        self.assertEqual(len(self.requests("INVITE")), before)
        self.assertEqual(len(self.http.posted("voice.test/calls")), 2)
        self.assertIn(f"AS b2bua refreshed INVITE call_id={b}", self.log())

    def test_update_is_answered_locally(self):
        self.establish()
        update = request(
            "UPDATE",
            "tr-1",
            uri=AS_URI,
            from_user=CALLER,
            from_tag="fa1",
            to_user=CALLEE,
            to_tag=local_tag("tr-1"),
            cseq=3,
            branch="z9hG4bK-up1",
            body=sdp(RTP_IP, 4000),
        )
        self.route_request(update, SCSCF)
        answer = self.sent()[-1][0]
        self.assertTrue(answer.startswith("SIP/2.0 200 OK"))
        self.assertIn("Content-Type: application/sdp", answer)
        self.assertIn("Contact: <sip:b2bua@", answer)
        self.assertEqual(self.requests("UPDATE"), [])

    def test_invite_retransmission_gets_trying(self):
        self.start_call()
        self.route_request(invite(CALLEE, "tr-1", route_host="translate.as"), SCSCF)
        self.assertEqual(self.statuses(), [100, 100])
        self.assertEqual(len(self.requests("INVITE")), 1)

    def test_ack_for_rejected_caller_is_absorbed(self):
        leg_b = self.start_call("tr-ack")
        self.reply_b(leg_b, 486, "Busy Here")
        self.assertEqual(to_tag_of(self.sent()[-1][0]), local_tag("tr-ack"))
        before = len(self.sent())
        ack = request(
            "ACK",
            "tr-ack",
            uri=f"sip:{CALLEE}@{DOMAIN}",
            from_user=CALLER,
            from_tag="fa1",
            to_user=CALLEE,
            to_tag=local_tag("tr-ack"),
            cseq=1,
            branch="z9hG4bK-a1",
            route_host="translate.as",
        )
        self.route_request(ack, SCSCF)
        self.assertEqual(len(self.sent()), before)


if __name__ == "__main__":
    unittest.main()
