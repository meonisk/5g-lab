"""Нога B идёт через record AS (тот же процесс): его ответы — прокси, не B2BUA."""

import re
import unittest

from sip_fakes import CALLEE, SCSCF, SipCase, invite, isc_route, load_sip_as, response

load_sip_as()


def via_hop(message, branch, route_host):
    """S-CSCF добавил свой Via и ISC Route и отправил запрос логическому AS."""
    line, rest = message.split("\r\n", 1)
    rest = re.sub(r"(?im)^Route\s*:[^\r\n]*\r\n", "", rest)
    via = f"Via: SIP/2.0/UDP {SCSCF[0]}:{SCSCF[1]};branch={branch}\r\n"
    return f"{line}\r\n{via}{isc_route(route_host)}\r\n{rest}"


class LegBThroughRecord(SipCase):
    def test_response_below_record_via_is_relayed_to_scscf(self):
        self.route_request(invite(CALLEE, "ch-1", route_host="translate.as"), SCSCF)
        leg_b = self.requests("INVITE")[-1]
        self.route_request(via_hop(leg_b, "z9hG4bK-sc2", "record.as"), SCSCF)
        forwarded = self.requests("INVITE")[-1]
        self.assertTrue(forwarded.startswith("INVITE "))
        before = len(self.sent())

        self.route_response(response(forwarded, 180, "Ringing", to_tag="tb1"))

        relayed = [m for m, peer in self.sent()[before:] if m.startswith("SIP/2.0 180")]
        self.assertEqual(len(relayed), 1, self.log())
        top_via = re.search(r"(?im)^Via\s*:[^\r\n]*", relayed[0]).group(0)
        self.assertIn("branch=z9hG4bK-sc2", top_via)
        self.assertNotIn("dropped response", self.log())


if __name__ == "__main__":
    unittest.main()
