"""API MRF: места, привязка ноги, озвучка, распознавание, пара, запись, освобождение."""

import unittest

from sip_fakes import CALLEE, ENV, RTP_A, RTP_IP, SipCase, invite, load_sip_as

load_sip_as()
from ims_sip.core import mrf


class MrfApi(SipCase):
    def test_free_slots_from_voice_status(self):
        self.http.voice_calls = {"c1": {}, "c2": {}}
        self.assertEqual(mrf.free_slots(), int(ENV["VOICE_AGENT_MAX_CALLS"]) - 2)

    def test_free_slots_zero_when_voice_agent_down(self):
        self.http.fail.add("voice.test")
        self.assertEqual(mrf.free_slots(), 0)
        self.assertIn("AS mrf status unavailable", self.log())

    def test_bind_leg_registers_voice_and_adapter(self):
        message = invite(CALLEE, "leg-1")
        self.assertTrue(mrf.bind_leg(message, "leg-1", RTP_IP, RTP_A, "interpret_ru"))
        self.assertEqual(
            self.http.posted("voice.test/calls"),
            [
                {
                    "call_id": "leg-1",
                    "remote_ip": RTP_IP,
                    "remote_port": RTP_A,
                    "service_mode": "interpret_ru",
                }
            ],
        )
        session = self.http.posted("media.test/sessions")[0]
        self.assertEqual(
            (session["call_id"], session["service_mode"], session["rtpengine_port"]),
            ("leg-1", "interpret_ru", RTP_A),
        )

    def test_bind_leg_fails_without_voice_agent(self):
        self.http.fail.add("voice.test")
        message = invite(CALLEE, "leg-2")
        self.assertFalse(mrf.bind_leg(message, "leg-2", RTP_IP, RTP_A, "interpret_en"))
        self.assertEqual(self.http.posted("media.test/sessions"), [])
        self.assertIn("AS voice unavailable call_id=leg-2", self.log())

    def test_release_stops_voice_and_adapter(self):
        mrf.release("leg-3")
        self.assertEqual(len(self.http.deleted("voice.test/calls/leg-3")), 1)
        self.assertEqual(len(self.http.deleted("media.test/sessions/leg-3")), 1)

    def test_stop_recognition_keeps_voice_agent(self):
        mrf.stop_recognition("leg-4")
        self.assertEqual(self.http.deleted("voice.test"), [])
        self.assertEqual(len(self.http.deleted("media.test/sessions/leg-4")), 1)

    def test_play_sends_announcement_reply(self):
        self.assertTrue(mrf.play("leg-5", "Внимание", ENV["TTS_VOICE"]))
        self.assertEqual(
            self.http.posted("voice.test/calls/leg-5/reply"),
            [{"text": "Внимание", "voice": ENV["TTS_VOICE"], "reason": "announcement"}],
        )

    def test_play_reports_failure(self):
        self.http.fail.add("voice.test")
        self.assertFalse(mrf.play("leg-6", "Внимание", ENV["TTS_VOICE"]))
        self.assertIn("AS mrf play failed call_id=leg-6", self.log())

    def test_pair_and_unpair(self):
        mrf.pair(("leg-a", "ru"), ("leg-b", "en"))
        legs = [{"call_id": "leg-a", "language": "ru"}, {"call_id": "leg-b", "language": "en"}]
        self.assertEqual(self.http.posted("ai.test/pairs"), [{"legs": legs}])
        mrf.unpair("leg-a")
        self.assertEqual(len(self.http.deleted("ai.test/pairs/leg-a")), 1)

    def test_record_pair(self):
        mrf.record_pair("leg-a", [("leg-a", "caller"), ("leg-b", "callee")])
        self.assertEqual(
            self.http.posted("ai.test/recordings"),
            [
                {
                    "session_call_id": "leg-a",
                    "legs": [
                        {"call_id": "leg-a", "speaker": "caller"},
                        {"call_id": "leg-b", "speaker": "callee"},
                    ],
                }
            ],
        )

    def test_announce_asks_adapter_to_play_to_each_party(self):
        self.assertTrue(mrf.announce("call-r", [("fa1", "Внимание", ENV["TTS_VOICE"])]))
        self.assertEqual(
            self.http.posted("media.test/sessions/call-r/announce"),
            [{"parties": [{"tag": "fa1", "text": "Внимание", "voice": ENV["TTS_VOICE"]}]}],
        )

    def test_announce_failure_is_false(self):
        self.http.fail.add("/announce")
        self.assertFalse(mrf.announce("call-s", [("fa1", "Внимание", ENV["TTS_VOICE"])]))
        self.assertIn("AS mrf announce failed call_id=call-s", self.log())

    def test_stream_to_recognition_uses_service_mode(self):
        mrf.stream_to_recognition(invite(CALLEE, "rec-1"), "record")
        session = self.http.posted("media.test/sessions")[0]
        self.assertEqual(
            (session["call_id"], session["service_mode"], session["rtpengine_port"]),
            ("rec-1", "record", RTP_A),
        )


if __name__ == "__main__":
    unittest.main()
