"""numbers AS как UAS штатной звонилки: 100rel, QoS preconditions, UPDATE, CANCEL, повторы.

Таймеры uas.later перехватываются и запускаются тестом вручную.
"""

import unittest
from unittest.mock import patch

from sip_fakes import (
    CALLEE,
    CALLER,
    DOMAIN,
    ENV,
    RTP_A,
    RTP_IP,
    SCSCF,
    SipCase,
    invite,
    isc_route,
    load_sip_as,
)

load_sip_as()
from ims_sip.core import preconditions, uas
from ims_sip.core.sip import local_tag
from ims_sip.services import numbers

NUMBER = ENV["VOICE_TRANSLATOR_MSISDN"]
AGENT = ENV["VOICE_AGENT_SIP_USER"]
CALL = "pre-1"
QOS = (
    "a=curr:qos local {local}\r\na=curr:qos remote none\r\n"
    "a=des:qos mandatory local sendrecv\r\na=des:qos none remote sendrecv\r\n"
)


def offer(local="none", port=RTP_A, ip=RTP_IP, qos=True):
    return (
        f"v=0\r\no=- 1 1 IN IP4 {ip}\r\ns=-\r\nc=IN IP4 {ip}\r\nt=0 0\r\n"
        f"m=audio {port} RTP/AVP 0 96\r\na=rtpmap:0 PCMU/8000\r\na=rtpmap:96 AMR/8000\r\n"
        + (QOS.format(local=local) if qos else "")
        + "a=sendrecv\r\n"
    )


def message(method, cseq, body="", extra=(), uri=None):
    initial = method == "INVITE" and cseq == 1
    if uri is None:
        uri = f"sip:{NUMBER}@{DOMAIN};user=phone"
        if not initial:
            uri = f"sip:{AGENT}@{ENV['SIP_AS_IP']}:{ENV['SIP_AS_PORT']}"
    lines = [f"{method} {uri} SIP/2.0", f"Via: SIP/2.0/UDP {SCSCF[0]}:{SCSCF[1]};branch=z9b{cseq}"]
    if initial:
        lines.append(isc_route("as"))
    to_tag = "" if initial or method == "CANCEL" else f";tag={local_tag(CALL)}"
    lines += [
        f"From: <sip:{CALLER}@{DOMAIN}>;tag=fa1",
        f"To: <sip:{NUMBER}@{DOMAIN}>{to_tag}",
        f"Call-ID: {CALL}",
        f"CSeq: {cseq} {method}",
        *extra,
    ]
    if body:
        lines.append("Content-Type: application/sdp")
    lines.append(f"Content-Length: {len(body.encode())}")
    return "\r\n".join(lines) + "\r\n\r\n" + body


SUPPORTS = ("Supported: 100rel, precondition, timer",)
PRACK = ("RAck: 1 1 INVITE",)


class Preconditions(SipCase):
    def setUp(self):
        super().setUp()
        self.timers = []
        timer = patch.object(uas, "later", lambda delay, *call: self.timers.append(call))
        timer.start()
        self.addCleanup(timer.stop)

    def send(self, msg):
        self.runtime.sock.reset_mock()
        self.route_request(msg, SCSCF)
        return [m for m, _ in self.sent()]

    def fire(self):
        pending, self.timers = self.timers, []
        for function, *args in pending:
            function(*args)

    def voice_posts(self):
        return self.http.posted("voice.test/calls")

    def answered_early(self, local="none"):
        sent = self.send(message("INVITE", 1, offer(local), SUPPORTS))
        self.send(message("PRACK", 2, extra=PRACK))
        return sent

    def test_answer_mirrors_segments_and_requests_confirmation(self):
        lines = preconditions.answer_lines(offer())
        self.assertIn("a=curr:qos local sendrecv", lines)
        self.assertIn("a=des:qos mandatory remote sendrecv", lines)
        self.assertIn("a=conf:qos remote sendrecv", lines)
        self.assertFalse(preconditions.offerer_ready(offer()))
        self.assertTrue(preconditions.offerer_ready(offer("sendrecv")))
        self.assertNotIn(
            "a=conf:qos remote sendrecv", preconditions.answer_lines(offer("sendrecv"))
        )
        self.assertEqual(preconditions.answer_lines(offer(qos=False)), [])

    def test_native_dialer_flow_183_prack_update_then_200(self):
        sent = self.send(message("INVITE", 1, offer(), SUPPORTS))
        self.assertEqual([m.split(" ", 2)[1] for m in sent], ["100", "183"])
        for text in ("Require: 100rel, precondition", "RSeq: 1", "a=conf:qos remote sendrecv"):
            self.assertIn(text, sent[1])
        self.assertIn(f"Contact: <sip:{AGENT}@{ENV['SIP_AS_IP']}:", sent[1])
        sent = self.send(message("PRACK", 2, extra=PRACK))
        self.assertEqual([m.split("\r\n")[0] for m in sent], ["SIP/2.0 200 OK"])
        self.assertEqual(self.voice_posts(), [])
        update, final = self.send(message("UPDATE", 3, offer("sendrecv")))
        self.assertIn("CSeq: 3 UPDATE", update)
        self.assertIn("a=curr:qos remote sendrecv", update)
        self.assertTrue(final.startswith("SIP/2.0 200 OK"))
        self.assertIn("CSeq: 1 INVITE", final)
        self.assertIn("Content-Length: 0", final)
        [post] = self.voice_posts()
        self.assertEqual((post["remote_ip"], post["remote_port"]), (RTP_IP, RTP_A))

    def test_ready_phone_is_answered_right_after_prack(self):
        self.send(message("INVITE", 1, offer("sendrecv"), ("Supported: 100rel,precondition",)))
        sent = self.send(message("PRACK", 2, extra=PRACK))
        self.assertEqual(len(sent), 2)
        self.assertIn("CSeq: 1 INVITE", sent[1])

    def test_softphone_without_extensions_keeps_immediate_200(self):
        sent = self.send(message("INVITE", 1, offer("sendrecv", qos=False)))
        self.assertTrue(sent[1].startswith("SIP/2.0 200 OK"))
        self.assertIn(f"m=audio {ENV['VOICE_AGENT_RTP_PORT']} RTP/AVP 0", sent[1])
        self.assertNotIn("a=curr:qos", sent[1])

    def test_tel_uri_from_s_cscf_reaches_service(self):
        uri = f"tel:{NUMBER};phone-context={DOMAIN}"
        sent = self.send(message("INVITE", 1, offer("sendrecv", qos=False), uri=uri))
        self.assertTrue(sent[-1].startswith("SIP/2.0 200 OK"))
        self.assertEqual(numbers.request_target(f"INVITE {uri} SIP/2.0"), NUMBER)
        dialed = f"INVITE sip:{NUMBER};phone-context={DOMAIN}@{DOMAIN};user=phone SIP/2.0"
        self.assertEqual(numbers.request_target(dialed), NUMBER)

    def test_cancel_in_early_dialog_terminates_invite(self):
        self.send(message("INVITE", 1, offer(), ("Require: 100rel", "Supported: precondition")))
        ok, final = self.send(message("CANCEL", 1))
        self.assertTrue(ok.startswith("SIP/2.0 200 OK"))
        self.assertTrue(final.startswith("SIP/2.0 487"))
        self.assertIn("CSeq: 1 INVITE", final)
        self.assertEqual(self.voice_posts(), [])
        self.send(message("ACK", 1))
        self.assertEqual(self.runtime.agent_calls, {})

    def test_bye_in_early_dialog_terminates_invite(self):
        self.send(message("INVITE", 1, offer(), SUPPORTS))
        ok, final = self.send(message("BYE", 2))
        self.assertTrue(ok.startswith("SIP/2.0 200 OK"))
        self.assertTrue(final.startswith("SIP/2.0 487"))

    def test_unknown_required_extension_gets_420(self):
        sent = self.send(message("INVITE", 1, offer(), ("Require: 100rel, foo",)))
        self.assertTrue(sent[1].startswith("SIP/2.0 420"))
        self.assertIn("Unsupported: foo", sent[1])

    def test_unanchored_update_does_not_move_media(self):
        self.answered_early()
        self.send(message("UPDATE", 3, offer("sendrecv", port=4000, ip="198.51.100.9")))
        self.send(message("UPDATE", 4, offer("sendrecv")))
        self.assertEqual([p["remote_port"] for p in self.voice_posts()], [RTP_A])

    def test_changed_answer_increments_sdp_version(self):
        early = self.answered_early()[1]
        self.assertIn("o=voice-agent 1 1 ", early)
        update = self.send(message("UPDATE", 3, offer("sendrecv")))[0]
        self.assertIn("o=voice-agent 1 2 ", update)
        again = self.send(message("UPDATE", 4, offer("sendrecv")))[0]
        self.assertIn("o=voice-agent 1 2 ", again)

    def test_preconditions_need_uac_support(self):
        sent = self.send(message("INVITE", 1, offer(), ("Supported: 100rel",)))
        self.assertTrue(sent[1].startswith("SIP/2.0 200 OK"))
        self.assertNotIn("Require:", sent[1])
        self.assertNotIn("a=curr:qos", sent[1])

    def test_mismatched_rack_is_rejected(self):
        self.send(message("INVITE", 1, offer(), SUPPORTS))
        sent = self.send(message("PRACK", 2, extra=("RAck: 1 7 INVITE",)))
        self.assertTrue(sent[0].startswith("SIP/2.0 481"))

    def test_precondition_timeout_answers_anyway(self):
        self.answered_early()
        self.timers = [t for t in self.timers if t[0] is numbers.finalize]
        self.runtime.sock.reset_mock()
        self.fire()
        self.assertTrue(self.sent()[0][0].startswith("SIP/2.0 200 OK"))
        self.assertIn("AS precondition wait expired", self.log())

    def test_missing_prack_gets_504(self):
        with patch.object(self.runtime, "sip_t1", 0.0):
            self.send(message("INVITE", 1, offer(), SUPPORTS))
            self.runtime.sock.reset_mock()
            self.fire()
        self.assertTrue(self.sent()[0][0].startswith("SIP/2.0 504"))
        self.assertEqual(self.voice_posts(), [])

    def test_final_response_repeats_until_ack(self):
        self.send(message("INVITE", 1, offer("sendrecv", qos=False)))
        self.runtime.sock.reset_mock()
        self.fire()
        self.assertTrue(self.sent()[0][0].startswith("SIP/2.0 200 OK"))
        self.send(message("ACK", 1))
        self.runtime.sock.reset_mock()
        self.fire()
        self.assertEqual(self.sent(), [])
        self.assertIn(CALL, self.runtime.agent_calls)

    def test_unacknowledged_200_ends_call(self):
        with patch.object(self.runtime, "sip_t1", 0.0):
            self.send(message("INVITE", 1, offer("sendrecv", qos=False)))
            self.fire()
        self.assertEqual(self.runtime.agent_calls, {})
        self.assertEqual(len(self.http.deleted(f"voice.test/calls/{CALL}")), 1)

    def test_cancel_while_voice_agent_starts_yields_487(self):
        def cancel_during_start(method, url, **kwargs):
            if method == "POST" and url.endswith("voice.test/calls"):
                self.route_request(message("CANCEL", 1), SCSCF)
            return self.http(method, url, **kwargs)

        with patch("httpx.request", cancel_during_start):
            sent = self.send(message("INVITE", 1, offer("sendrecv", qos=False)))
        finals = [m.split("\r\n")[0] for m in sent if "CSeq: 1 INVITE" in m]
        self.assertEqual(finals[1:], ["SIP/2.0 487 Request Terminated"])
        self.assertEqual(len(self.http.deleted(f"voice.test/calls/{CALL}")), 1)

    def test_media_move_after_answer_reaches_voice_agent(self):
        self.send(message("INVITE", 1, offer("sendrecv", qos=False)))
        self.send(message("ACK", 1))
        reinvite = self.send(message("INVITE", 2, offer("sendrecv", port=RTP_A - 2, qos=False)))
        self.assertTrue(reinvite[0].startswith("SIP/2.0 200 OK"))
        self.assertIn("o=voice-agent 1 1 ", reinvite[0])
        self.assertEqual([p["remote_port"] for p in self.voice_posts()], [RTP_A, RTP_A - 2])

    def test_options_and_unknown_methods_are_answered(self):
        self.send(message("INVITE", 1, offer("sendrecv", qos=False)))
        self.assertTrue(self.send(message("OPTIONS", 2))[0].startswith("SIP/2.0 200"))
        self.assertTrue(self.send(message("MESSAGE", 3))[0].startswith("SIP/2.0 501"))

    def test_translate_still_bypasses_required_extensions(self):
        plain = invite(CALLEE, "pre-t", route_host="translate.as")
        head, body = plain.split("\r\n\r\n", 1)
        self.route_request(f"{head}\r\nRequire: 100rel\r\n\r\n{body}", SCSCF)
        self.assertIn("AS translate bypass call_id=pre-t reason=media", self.log())


if __name__ == "__main__":
    unittest.main()
