"""Offline UERANSIM PDU metadata parsing tests."""

import unittest

from app.tests.integration.ue_pdu_state import PduStateError, parse_ps_list, parse_status

PS_LIST = """PDU Session1:
 state: PS-ACTIVE
 session-type: IPv4
 apn: internet
 s-nssai:
  sst: 0x01
  sd: null
 emergency: false
 address: 198.51.100.6
 ambr: up[1000000Kb/s] down[1000000Kb/s]
 data-pending: false
PDU Session2:
 state: PS-ACTIVE
 session-type: IPv4
 apn: ims
 s-nssai:
  sst: 0x01
  sd: null
 emergency: false
 address: 192.0.2.6
 ambr: up[1000000Kb/s] down[1000000Kb/s]
 data-pending: false
"""


class PduStateTests(unittest.TestCase):
    def test_ims_selected_by_dnn_not_order(self):
        parsed = parse_ps_list(PS_LIST, "ims", "192.0.2.0/24")
        self.assertEqual(
            parsed["ims"],
            {"session_id": 2, "state": "PS-ACTIVE", "type": "IPv4", "address": "192.0.2.6"},
        )
        self.assertEqual(parsed["sessions"][1]["dnn"], "internet")

    def test_missing_duplicate_and_invalid_address_fail(self):
        with self.assertRaises(PduStateError):
            parse_ps_list(PS_LIST.replace("apn: ims", "apn: internet"), "ims", "192.0.2.0/24")
        with self.assertRaises(PduStateError):
            parse_ps_list(
                PS_LIST + PS_LIST.split("PDU Session2:")[1].join(["PDU Session3:", ""]),
                "ims",
                "192.0.2.0/24",
            )
        with self.assertRaises(PduStateError):
            parse_ps_list(PS_LIST.replace("192.0.2.6", "203.0.113.6"), "ims", "192.0.2.0/24")
        with self.assertRaises(PduStateError):
            parse_ps_list(
                PS_LIST.replace("address: 192.0.2.6", "address: null"), "ims", "192.0.2.0/24"
            )

    def test_pending_and_absent_are_explicit(self):
        pending = PS_LIST.replace(
            "state: PS-ACTIVE\n session-type: IPv4\n apn: ims",
            "state: PS-ACTIVE-PENDING\n session-type: IPv4\n apn: ims",
        )
        pending = pending.replace("address: 192.0.2.6", "address: null")
        self.assertEqual(
            parse_ps_list(pending, "ims", "192.0.2.0/24", False)["ims"]["address"], None
        )
        with self.assertRaises(PduStateError):
            parse_ps_list(pending, "ims", "192.0.2.0/24")
        self.assertIsNone(parse_ps_list("", "ims", "192.0.2.0/24", False)["ims"])

    def test_status_requires_registration_fields(self):
        self.assertEqual(
            parse_status(
                "cm-state: CM-CONNECTED\nrm-state: RM-REGISTERED\n"
                "mm-state: MM-REGISTERED/NORMAL-SERVICE\n"
            ),
            {
                "cm-state": "CM-CONNECTED",
                "rm-state": "RM-REGISTERED",
                "mm-state": "MM-REGISTERED/NORMAL-SERVICE",
            },
        )
        with self.assertRaises(PduStateError):
            parse_status("cm-state: CM-CONNECTED\n")
