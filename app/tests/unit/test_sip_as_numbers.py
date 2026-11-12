"""Характеризация numbers AS: 1003–1006, observe и прокси не меняются при переносе в core/."""

import re
import unittest

from sip_fakes import (
    CALLEE,
    CALLER,
    ENV,
    RTP_A,
    RTP_IP,
    SCSCF,
    SipCase,
    invite,
    request,
    response,
    to_tag_of,
)

OTHER_PEER = ("198.51.100.1", 6060)


class ServiceNumbers(SipCase):
    def test_service_number_terminates_on_voice_agent(self):
        self.route_request(invite(ENV["VOICE_TRANSLATOR_MSISDN"], "num-1"), SCSCF)
        self.assertEqual(self.statuses(), [100, 200])
        answer = self.sent()[-1][0]
        self.assertIn(f"m=audio {ENV['VOICE_AGENT_RTP_PORT']} RTP/AVP 0", answer)
        self.assertIn(f"Contact: <sip:{ENV['VOICE_AGENT_SIP_USER']}@", answer)
        self.assertEqual(
            self.http.posted("voice.test/calls"),
            [
                {
                    "call_id": "num-1",
                    "remote_ip": RTP_IP,
                    "remote_port": RTP_A,
                    "service_mode": "translate",
                }
            ],
        )
        session = self.http.posted("media.test/sessions")[0]
        self.assertEqual((session["service_mode"], session["rtpengine_port"]), ("translate", RTP_A))
        self.assertIn(
            "AS terminated INVITE for voice agent call_id=num-1 service=translate", self.log()
        )

    def test_each_service_number_keeps_its_mode(self):
        cases = {
            "VOICE_TRANSCRIBER_MSISDN": "transcribe",
            "VOICE_INTERPRETER_RU_MSISDN": "interpret_ru",
            "VOICE_INTERPRETER_EN_MSISDN": "interpret_en",
            "VOICE_TRANSCRIBER_SIP_USER": "transcribe",
        }
        for key, mode in cases.items():
            with self.subTest(key=key):
                self.route_request(invite(ENV[key], f"num-{key.lower()}"), SCSCF)
                self.assertEqual(self.http.posted("voice.test/calls")[-1]["service_mode"], mode)

    def test_unanchored_media_is_rejected(self):
        message = invite(ENV["VOICE_TRANSLATOR_MSISDN"], "num-2", ip="198.51.100.7")
        self.route_request(message, SCSCF)
        self.assertEqual(self.statuses(), [100, 488])
        self.assertEqual(self.http.posted("voice.test/calls"), [])
        self.assertIn("AS rejected unanchored media call_id=num-2", self.log())

    def test_voice_agent_down_answers_503(self):
        self.http.fail.add("voice.test")
        self.route_request(invite(ENV["VOICE_TRANSLATOR_MSISDN"], "num-3"), SCSCF)
        self.assertEqual(self.statuses(), [100, 503])
        self.assertIn("AS voice unavailable call_id=num-3", self.log())

    def test_bye_ends_agent_call(self):
        self.route_request(invite(ENV["VOICE_TRANSLATOR_MSISDN"], "num-4"), SCSCF)
        tag = to_tag_of(self.sent()[-1][0])
        user = ENV["VOICE_AGENT_SIP_USER"]
        bye = request(
            "BYE",
            "num-4",
            uri=f"sip:{user}@{ENV['SIP_AS_IP']}:{ENV['SIP_AS_PORT']}",
            from_user=CALLER,
            from_tag="fa1",
            to_user=ENV["VOICE_TRANSLATOR_MSISDN"],
            to_tag=tag,
        )
        self.route_request(bye, SCSCF)
        self.assertEqual(self.statuses()[-1], 200)
        self.assertEqual(len(self.http.deleted("voice.test/calls/num-4")), 1)
        self.assertEqual(len(self.http.deleted("media.test/sessions/num-4")), 1)
        self.assertEqual(self.runtime.agent_calls, {})
        self.assertIn("AS ended voice agent call_id=num-4 method=BYE", self.log())


class ProxiedCalls(SipCase):
    def test_plain_call_is_proxied_and_observed(self):
        self.route_request(invite(CALLEE, "plain-1"), OTHER_PEER)
        [(message, destination)] = self.sent()
        self.assertEqual(destination, SCSCF)
        self.assertTrue(message.startswith(f"INVITE sip:{CALLEE}@"))
        self.assertIn("branch=z9hG4bK-as-z9hG4bK-a1", message)
        route = re.search(r"(?m)^Route: (.+)$", message).group(1)
        self.assertTrue(route.startswith("<sip:iscmark@"))
        self.assertEqual(self.http.posted("media.test/sessions")[0]["service_mode"], "observe")
        self.assertIn("AS observed INVITE call_id=plain-1", self.log())

    def test_response_returns_to_original_peer_without_own_via(self):
        self.route_request(invite(CALLEE, "plain-2"), OTHER_PEER)
        forwarded = self.sent()[0][0]
        self.runtime.sock.reset_mock()
        self.route_response(response(forwarded, 180, "Ringing", to_tag="tb"))
        [(message, destination)] = self.sent()
        self.assertEqual(destination, OTHER_PEER)
        self.assertNotIn("z9hG4bK-as-", message)
        self.assertIn("branch=z9hG4bK-a1", message)

    def test_response_without_own_via_is_dropped(self):
        self.route_response(response(invite(CALLEE, "plain-3"), 200, "OK", to_tag="tb"))
        self.assertEqual(self.sent(), [])
        self.assertIn("AS dropped response without own Via", self.log())

    def test_compact_form_request_is_proxied(self):
        self.route_request(invite(CALLEE, "plain-c", compact=True), OTHER_PEER)
        self.assertEqual(len(self.requests("INVITE")), 1)
        self.assertIn("AS observed INVITE call_id=plain-c", self.log())


if __name__ == "__main__":
    unittest.main()
