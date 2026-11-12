"""Выбор логического AS по Route, языки абонентов, снятие своего Route, свои диалоги."""

import unittest

from lab_common.http import valid_call_id
from sip_fakes import CALLEE, CALLER, DOMAIN, ENV, SCSCF, SipCase, invite, load_sip_as

load_sip_as()
from ims_sip.core import dialogs, subscribers
from ims_sip.core.proxy import build_forwarded_request
from ims_sip.core.sip import top_route_host

AS_PORT = ENV["SIP_AS_PORT"]


class RouteHost(unittest.TestCase):
    def test_top_route_host_names_logical_as(self):
        message = invite(CALLEE, route_host="translate.as")
        self.assertEqual(top_route_host(message), f"translate.as.{DOMAIN}".lower())

    def test_no_route_means_no_host(self):
        self.assertEqual(top_route_host(invite(CALLEE, route_host=None)), "")


class Languages(unittest.TestCase):
    def test_table_maps_msisdn_and_imsi(self):
        table = subscribers.language_table(ENV)
        self.assertEqual(table[ENV["SIPUE1_MSISDN"]], "ru")
        self.assertEqual(table[ENV["SIPUE1_IMSI"]], "ru")
        self.assertEqual(table[ENV["SIPUE2_MSISDN"]], "en")
        self.assertEqual(table[ENV["UE2_IMSI"]], "en")

    def test_missing_language_uses_default(self):
        env = {key: value for key, value in ENV.items() if key != "SIPUE2_LANGUAGE"}
        table = subscribers.language_table(env)
        self.assertEqual(table[ENV["SIPUE2_MSISDN"]], ENV["DEFAULT_LANGUAGE"])

    def test_unsupported_language_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "UE1_LANGUAGE=de"):
            subscribers.language_table({**ENV, "UE1_LANGUAGE": "de"})

    def test_served_user_prefers_p_served_user(self):
        message = invite(CALLEE, served=ENV["SIPUE1_IMSI"])
        self.assertEqual(subscribers.served_user(message), ENV["SIPUE1_IMSI"])

    def test_served_user_falls_back_to_from(self):
        message = invite(CALLEE).replace("P-Served-User:", "X-Removed:")
        self.assertEqual(subscribers.served_user(message), CALLER)

    def test_target_user_keeps_star_prefix(self):
        self.assertEqual(subscribers.target_user(invite(f"*{CALLEE}")), f"*{CALLEE}")


class OwnRoute(unittest.TestCase):
    def test_strips_logical_as_route_in_comma_form(self):
        forwarded = build_forwarded_request(invite(CALLEE, route_host="translate.as"), "b1")
        self.assertRegex(forwarded, r"(?m)^Route: <sip:iscmark@")
        self.assertNotIn("translate.as.", forwarded)

    def test_strips_route_on_its_own_line(self):
        message = invite(CALLEE, route_host="record.as").replace(
            ">, <sip:iscmark@", ">\r\nRoute: <sip:iscmark@"
        )
        forwarded = build_forwarded_request(message, "b2")
        self.assertNotIn("record.as.", forwarded)
        self.assertRegex(forwarded, r"(?m)^Route: <sip:iscmark@")

    def test_record_route_is_not_touched(self):
        record_route = f"Record-Route: <sip:record.as.{DOMAIN}:{AS_PORT};lr>, <sip:mo@"
        message = invite(CALLEE).replace("Record-Route: <sip:mo@", record_route)
        self.assertIn(record_route, build_forwarded_request(message, "b3"))


class OwnDialogs(SipCase):
    def test_new_call_id_is_valid_and_own(self):
        call_id = dialogs.new_call_id()
        self.assertRegex(call_id, r"^b2b-[0-9a-f]{24}$")
        self.assertTrue(valid_call_id(call_id))
        self.assertTrue(dialogs.is_own(call_id))
        dialogs.forget(call_id)
        self.assertFalse(dialogs.is_own(call_id))

    def test_numbers_does_not_observe_own_leg(self):
        call_id = dialogs.new_call_id()
        self.route_request(invite(CALLEE, call_id), SCSCF)
        self.assertEqual(len(self.requests("INVITE")), 1)
        self.assertEqual(self.http.posted("media.test/sessions"), [])
        self.assertNotIn("AS observed INVITE", self.log())

    def test_unknown_route_host_falls_back_to_numbers(self):
        self.route_request(invite(CALLEE, "plain-x", route_host="unknown.as"), SCSCF)
        self.assertIn("AS observed INVITE call_id=plain-x", self.log())


if __name__ == "__main__":
    unittest.main()
