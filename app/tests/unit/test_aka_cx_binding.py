"""SIP challenges must map one-to-one to same-user MAA sessions."""

import base64
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/tests/integration"))
import aka_cx_binding as binding


class BindingTests(unittest.TestCase):
    def attempt(
        self,
        wrong_owner=False,
        cx_status="PASS",
        count=1,
        reuse_challenge=False,
        missing_maa=False,
        reuse_session=False,
    ):
        settings = {
            "UE1_IMSI": "111",
            "UE2_IMSI": "222",
            "IMS_DOMAIN": "ims.test",
            "PYHSS_BIND_PORT": "3868",
        }
        key = b"synthetic-key"
        counts = {ue: count if isinstance(count, int) else count[ue] for ue in (1, 2)}
        challenges = {
            ue: [
                bytes((n + ue * 40 + round_index) % 256 for n in range(32))
                for round_index in range(counts[ue])
            ]
            for ue in (1, 2)
        }
        if reuse_challenge:
            challenges[1][-1] = challenges[1][0]
        transactions = [
            {
                "user": binding.identity_pseudonym(settings[f"UE{ue}_IMSI"] + "@ims.test", key),
                "command": "MAR",
                "session": f"session-{ue}-{0 if reuse_session else round_index}",
                "challenge_fingerprints": [
                    binding.challenge_fingerprint(challenges[ue][round_index], key)
                ],
            }
            for ue in (1, 2)
            for round_index in range(counts[ue])
        ]
        if wrong_owner:
            transactions[0]["user"] = transactions[-1]["user"]
        if missing_maa:
            transactions.pop(0)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for ue in (1, 2):
                traces = []
                for challenge in challenges[ue]:
                    nonce = base64.b64encode(challenge).decode()
                    traces.append(
                        f'SIP/2.0 401 Unauthorized\nWWW-Authenticate: Digest nonce="{nonce}"\n\n'
                    )
                (directory / f"ue{ue}-messages.log").write_text("".join(traces))
            with (
                patch.object(binding.secrets, "token_bytes", return_value=key),
                patch.object(
                    binding,
                    "summarize_pcap",
                    return_value={"status": cx_status, "transactions": transactions},
                ),
            ):
                return binding.assess(directory, settings, expected_challenges=count)

    def test_same_user_challenges_pass(self):
        result = self.attempt()
        self.assertEqual(result["status"], "PASS")
        self.assertIn("challenge", result["sip_maa_bindings"][0])

    def test_other_users_vector_cannot_pass(self):
        self.assertEqual(self.attempt(wrong_owner=True)["status"], "FAIL")

    def test_binding_does_not_override_incomplete_cx(self):
        self.assertEqual(self.attempt(cx_status="INCOMPLETE")["status"], "INCOMPLETE")

    def test_three_distinct_challenges_and_sessions_pass(self):
        result = self.attempt(count=3)
        self.assertEqual(result["status"], "PASS")
        for entry in result["sip_maa_bindings"]:
            self.assertEqual(len(entry["challenges"]), 3)
            self.assertEqual(len(set(entry["sessions"])), 3)

    def test_per_ue_challenge_counts(self):
        result = self.attempt(count={1: 1, 2: 3})
        self.assertEqual(result["status"], "PASS")
        self.assertIn("challenge", result["sip_maa_bindings"][0])
        self.assertEqual(len(result["sip_maa_bindings"][1]["challenges"]), 3)

    def test_multiple_challenge_reuse_missing_or_wrong_owner_fail(self):
        self.assertEqual(self.attempt(count=3, reuse_challenge=True)["status"], "FAIL")
        self.assertEqual(self.attempt(count=3, missing_maa=True)["status"], "FAIL")
        self.assertEqual(self.attempt(count=3, wrong_owner=True)["status"], "FAIL")
        self.assertEqual(self.attempt(count=3, reuse_session=True)["status"], "FAIL")
