"""Synthetic S-CSCF registrar RPC readback checks."""

import unittest
from unittest.mock import patch

from app.tests.integration.aka_registrar import (
    RegistrarError,
    parse_showimpu,
    read_registration,
    require_contact,
    require_contact_inventory,
    require_inactive_contact,
)

IMPU = "sip:ue@example.test"
CONTACT = "sip:ue@10.0.0.7:5060;alias=10.0.0.7~5060~1;ob"
RESPONSE = """{
\timpu: sip:ue@example.test
\tstate: registered
\tsubscription: {
\t\timpi: private@example.test
\t}
\tcontacts: {
\t\tsip:ue@10.0.0.7:5060;alias=10.0.0.7~5060~1;ob: {
\t\t\texpires: 3479
\t\t\tclient: SIP UA
\t\t}
\t}
}
"""


class RegistrarTests(unittest.TestCase):
    def test_exact_inventory_two_positive_then_old_inactive(self):
        old = "sip:ue@10.0.0.7:5060"
        new = "sip:ue@10.0.0.8:5060"
        state = {
            "state": "registered",
            "contacts": [
                {"uri": old + ";alias=a", "expires": 300},
                {"uri": new + ";alias=b", "expires": 290},
            ],
        }
        inventory = require_contact_inventory(state, [old, new])
        self.assertEqual(inventory["positive_expiries"], [300, 290])
        self.assertNotIn("10.0.0", str(inventory))
        state["contacts"][0]["expires"] = 0
        self.assertEqual(
            require_contact_inventory(state, [new], [old])["inactive_present_count"], 1
        )
        state["contacts"].pop(0)
        self.assertEqual(require_contact_inventory(state, [new], [old])["inactive_absent_count"], 1)

    def test_inventory_rejects_extra_duplicate_prefix_and_state(self):
        old = "sip:ue@10.0.0.7:5060"
        state = {"state": "registered", "contacts": [{"uri": old, "expires": 300}]}
        self.assertEqual(require_contact_inventory(state, [old])["positive_count"], 1)
        for changed in (
            {
                "state": "registered",
                "contacts": state["contacts"] + [{"uri": old + ";ob", "expires": 1}],
            },
            {
                "state": "registered",
                "contacts": state["contacts"] + [{"uri": "sip:extra@example.test", "expires": 1}],
            },
            {"state": "registered", "contacts": [{"uri": old + "1", "expires": 1}]},
            {"state": "unregistered", "contacts": state["contacts"]},
            {"state": "registered", "contacts": [{"uri": old, "expires": 0}]},
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(RegistrarError):
                    require_contact_inventory(changed, [old])
        with self.assertRaises(RegistrarError):
            require_contact_inventory(state, [old, old])
        with self.assertRaises(RegistrarError):
            require_contact_inventory(state, [old], [old])

    def test_expired_contact_is_inactive_but_not_physically_absent(self):
        state = parse_showimpu(RESPONSE.replace("expires: 3479", "expires: -2"), IMPU)
        self.assertFalse(
            require_inactive_contact(state, "sip:ue@10.0.0.7:5060")["physically_absent"]
        )
        with self.assertRaises(RegistrarError):
            require_contact(state, "sip:ue@10.0.0.7:5060", False)
        with self.assertRaises(RegistrarError):
            require_contact(state, "sip:ue@10.0.0.7:5060", True)
        with self.assertRaises(RegistrarError):
            require_inactive_contact(parse_showimpu(RESPONSE, IMPU), "sip:ue@10.0.0.7:5060")

    def test_contact_present_and_deleted(self):
        state = parse_showimpu(RESPONSE, IMPU)
        self.assertEqual(require_contact(state, "sip:ue@10.0.0.7:5060", True)["expiry"], 3479)
        with self.assertRaises(RegistrarError):
            require_contact(state, "sip:ue@10.0.0.7:5060", False)
        self.assertEqual(
            require_contact(
                {"state": "unregistered", "contacts": []}, "sip:ue@10.0.0.7:5060", False
            )["matching_contacts"],
            0,
        )
        self.assertEqual(parse_showimpu("", IMPU)["state"], "absent")

    def test_mismatched_identity_and_incomplete_contact_fail_closed(self):
        with self.assertRaises(RegistrarError):
            parse_showimpu(RESPONSE, "sip:other@example.test")
        with self.assertRaises(RegistrarError):
            parse_showimpu(RESPONSE.replace("expires: 3479", "missing: 3479"), IMPU)
        with self.assertRaises(RegistrarError):
            require_contact({"state": "registered", "contacts": []}, CONTACT, True)

    def test_prefix_collision_and_truncated_dump_fail(self):
        state = parse_showimpu(RESPONSE.replace(":5060;", ":50601;"), IMPU)
        with self.assertRaises(RegistrarError):
            require_contact(state, "sip:ue@10.0.0.7:5060", True)
        with self.assertRaises(RegistrarError):
            parse_showimpu(RESPONSE.rsplit("\t}", 1)[0], IMPU)
        with self.assertRaises(RegistrarError):
            parse_showimpu(RESPONSE.replace("\t\tsip:ue", "  sip:ue"), IMPU)

    @patch("app.tests.integration.aka_registrar.subprocess.run")
    def test_rpc_invocation_is_read_only(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = RESPONSE
        self.assertEqual(read_registration(IMPU)["contacts"][0]["expires"], 3479)
        self.assertEqual(
            run.call_args.args[0],
            ["docker", "exec", "lab-scscf", "kamcmd", "ulscscf.showimpu", IMPU],
        )
