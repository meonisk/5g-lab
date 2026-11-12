"""record AS: пометка звонка, Record-Route, уведомление, поток в AI, запись пары перевода."""

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
)

load_sip_as()
from ims_sip.core import dialogs

AS_PORT = ENV["SIP_AS_PORT"]
OTHER_PEER = ("198.51.100.1", 6060)
RECORD_RR = f"Record-Route: <sip:record.as.{DOMAIN}:{AS_PORT};transport=udp;lr>"
RU = (ENV["RECORDING_ANNOUNCEMENT_RU"], ENV["TTS_VOICE"])
EN = (ENV["RECORDING_ANNOUNCEMENT_EN"], ENV["TTS_TRANSLATION_VOICE"])


def call_id_of(message):
    return re.search(r"(?m)^Call-ID: (.+)$", message).group(1).strip()


class RecordProxy(SipCase):
    def forward_call(self, call_id, target=CALLEE):
        self.route_request(invite(target, call_id, route_host="record.as"), OTHER_PEER)
        return self.requests("INVITE")[-1]

    def answer(self, forwarded, status=200, reason="OK"):
        body = sdp(RTP_IP, RTP_B) if status == 200 else ""
        self.route_response(response(forwarded, status, reason, to_tag="tb1", body=body))

    def sessions(self):
        return [p for p in self.http.posted("media.test/sessions") if "service_mode" in p]

    def test_marks_call_and_adds_record_route(self):
        forwarded = self.forward_call("rec-1")
        self.assertIn(RECORD_RR, forwarded)
        self.assertLess(forwarded.index(RECORD_RR), forwarded.index("Record-Route: <sip:mo@"))
        self.assertRegex(forwarded, r"(?m)^Route: <sip:iscmark@")
        self.assertTrue(dialogs.is_marked_record("rec-1"))
        self.assertEqual(self.sessions(), [])
        self.assertIn("AS record marked call_id=rec-1", self.log())

    def test_answer_announces_then_streams(self):
        self.answer(self.forward_call("rec-2"))
        self.assertEqual(self.sent()[-1][1], OTHER_PEER)
        parties = [
            {"tag": "fa1", "text": RU[0], "voice": RU[1]},
            {"tag": "tb1", "text": EN[0], "voice": EN[1]},
        ]
        self.assertEqual(self.http.posted("/announce"), [{"parties": parties}])
        [session] = self.sessions()
        self.assertEqual((session["call_id"], session["service_mode"]), ("rec-2", "record"))
        urls = [url for _, url, _ in self.http.calls]
        announce = next(i for i, url in enumerate(urls) if url.endswith("/announce"))
        self.assertLess(announce, urls.index("http://media.test/sessions"))
        self.assertIn("AS record started call_id=rec-2", self.log())

    def test_failed_announcement_skips_recording(self):
        self.http.fail.add("/announce")
        self.answer(self.forward_call("rec-3"))
        self.assertEqual(self.sessions(), [])
        self.assertIn("AS record skipped call_id=rec-3 reason=announcement", self.log())

    def test_rejected_call_is_not_recorded(self):
        self.answer(self.forward_call("rec-r"), 486, "Busy Here")
        self.assertEqual(self.http.posted("/announce"), [])
        self.assertEqual(self.runtime.record_invites, {})

    def test_bye_stops_recording(self):
        self.answer(self.forward_call("rec-4"))
        bye = request(
            "BYE",
            "rec-4",
            uri=f"sip:{CALLEE}@192.0.2.20:5060",
            from_user=CALLER,
            from_tag="fa1",
            to_user=CALLEE,
            to_tag="tb1",
            route_host="record.as",
        )
        self.route_request(bye, SCSCF)
        [forwarded_bye] = self.requests("BYE")
        self.assertNotIn(f"record.as.{DOMAIN}", forwarded_bye)
        self.assertEqual(len(self.http.deleted("media.test/sessions/rec-4")), 1)
        self.assertFalse(dialogs.is_marked_record("rec-4"))
        self.assertIn("AS record ended call_id=rec-4", self.log())

    def test_service_number_passes_unchanged(self):
        forwarded = self.forward_call("rec-5", target=ENV["VOICE_TRANSCRIBER_MSISDN"])
        self.assertNotIn(RECORD_RR, forwarded)
        self.assertFalse(dialogs.is_marked_record("rec-5"))
        self.assertNotIn("AS record marked", self.log())

    def test_translate_leg_is_marked_without_own_recording(self):
        call_id = dialogs.new_call_id()
        forwarded = self.forward_call(call_id)
        self.assertNotIn(RECORD_RR, forwarded)
        self.assertTrue(dialogs.is_marked_record(call_id))
        self.assertEqual(self.runtime.record_invites, {})
        self.assertIn(f"AS record marked call_id={call_id} via=translate", self.log())

    def test_numbers_skips_marked_call(self):
        dialogs.mark_record("rec-n")
        self.route_request(invite(CALLEE, "rec-n"), SCSCF)
        self.assertNotIn("AS observed INVITE", self.log())


class TranslatedRecording(SipCase):
    def translated_call(self):
        self.route_request(invite(CALLEE, "tr-r", route_host="translate.as"), SCSCF)
        leg_b = self.requests("INVITE")[-1]
        via_record = f"Route: <sip:record.as.{DOMAIN}:{AS_PORT};transport=udp;lr>, <sip:iscmark@"
        self.route_request(leg_b.replace("Route: <sip:iscmark@", via_record), SCSCF)
        answer = response(
            leg_b,
            200,
            "OK",
            to_tag="tb1",
            body=sdp(RTP_IP, RTP_B),
            contact=f"<sip:{CALLEE}@192.0.2.20:5060>",
        )
        return call_id_of(leg_b), answer

    def test_translated_call_records_both_legs_after_announcement(self):
        b, answer = self.translated_call()
        self.route_response(answer)
        self.assertEqual(
            self.http.posted("/reply"),
            [
                {"text": RU[0], "voice": RU[1], "reason": "announcement"},
                {"text": EN[0], "voice": EN[1], "reason": "announcement"},
            ],
        )
        legs = [{"call_id": "tr-r", "speaker": "caller"}, {"call_id": b, "speaker": "callee"}]
        expected = [{"session_call_id": "tr-r", "legs": legs}]
        self.assertEqual(self.http.posted("ai.test/recordings"), expected)
        self.assertIn("AS record started call_id=tr-r legs=2", self.log())

    def test_play_failure_skips_pair_recording(self):
        _, answer = self.translated_call()
        self.http.fail.add("/reply")
        self.route_response(answer)
        self.assertEqual(self.http.posted("ai.test/recordings"), [])
        self.assertIn("AS record skipped call_id=tr-r reason=announcement", self.log())


if __name__ == "__main__":
    unittest.main()
