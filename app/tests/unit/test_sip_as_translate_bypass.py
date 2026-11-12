"""translate AS без перевода: прозрачный прокси с причиной в журнале, без 503 звонящему."""

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
    response,
    sdp,
)

load_sip_as()
from ims_sip.core import b2bua, dialogs

SAME_LANGUAGE = ENV["UE1_MSISDN"]  # ru, как у SIPUE1


class Bypass(SipCase):
    def call(self, target, call_id, **options):
        self.route_request(invite(target, call_id, route_host="translate.as", **options), SCSCF)

    def assert_bypassed(self, call_id, reason):
        [forwarded] = self.requests("INVITE")
        self.assertIn("branch=z9hG4bK-as-", forwarded)
        self.assertIsNone(b2bua.find(call_id))
        self.assertEqual(self.statuses(), [])
        self.assertIn(f"AS translate bypass call_id={call_id} reason={reason}", self.log())
        return forwarded

    def test_same_language_is_proxied(self):
        self.call(SAME_LANGUAGE, "by-1")
        forwarded = self.assert_bypassed("by-1", "same_language")
        self.assertRegex(forwarded, r"(?m)^Route: <sip:iscmark@")

    def test_service_number_passes_unchanged(self):
        self.call(ENV["VOICE_TRANSLATOR_MSISDN"], "by-2")
        forwarded = self.assert_bypassed("by-2", "service_number")
        self.assertTrue(forwarded.startswith(f"INVITE sip:{ENV['VOICE_TRANSLATOR_MSISDN']}@"))

    def test_unknown_callee(self):
        self.call("5550000", "by-3")
        self.assert_bypassed("by-3", "unknown_callee")

    def test_own_leg_passes(self):
        call_id = dialogs.new_call_id()
        self.call(CALLEE, call_id)
        self.assert_bypassed(call_id, "own_leg")

    def test_unanchored_media(self):
        self.call(CALLEE, "by-5", ip="198.51.100.7")
        self.assert_bypassed("by-5", "media")

    def test_no_free_mrf_slots(self):
        max_calls = int(ENV["VOICE_AGENT_MAX_CALLS"])
        self.http.voice_calls = {f"c{index}": {} for index in range(max_calls - 1)}
        self.call(CALLEE, "by-6")
        self.assert_bypassed("by-6", "no_mrf")

    def test_voice_status_down_counts_as_no_mrf(self):
        self.http.fail.add("voice.test/status")
        self.call(CALLEE, "by-7")
        self.assert_bypassed("by-7", "no_mrf")

    def test_star_bypass_strips_prefix(self):
        self.call(f"*{SAME_LANGUAGE}", "by-8")
        forwarded = self.assert_bypassed("by-8", "same_language")
        self.assertTrue(forwarded.startswith(f"INVITE sip:{SAME_LANGUAGE}@{DOMAIN} SIP/2.0"))

    def test_star_from_subscriber_without_translate(self):
        self.call(f"*{CALLER}", "by-9", caller=ENV["SIPUE2_MSISDN"])
        [leg_b] = self.requests("INVITE")
        self.assertTrue(leg_b.startswith(f"INVITE sip:{CALLER}@{DOMAIN} SIP/2.0"))
        answer = response(
            leg_b,
            200,
            "OK",
            to_tag="tb1",
            body=sdp(RTP_IP, RTP_B),
            contact=f"<sip:{CALLER}@192.0.2.20:5060>",
        )
        self.route_response(answer)
        self.assertRegex(
            self.log(), r"AS translate answered call_id=by-9 leg_b=b2b-[0-9a-f]+ languages=en-ru"
        )


if __name__ == "__main__":
    unittest.main()
