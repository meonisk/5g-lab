"""scripts/start.py без Docker: проверка lab.env, разбор Cx-пиров, overlay CPU-режимов."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import start  # noqa: E402
from provision import read_env  # noqa: E402


class Validation(unittest.TestCase):
    def setUp(self):
        self.settings = read_env()

    def test_repository_lab_env_is_consistent(self):
        start.validate(self.settings)

    def test_domain_must_follow_mcc_mnc(self):
        with self.assertRaisesRegex(ValueError, "IMS_DOMAIN"):
            start.validate({**self.settings, "MNC": "02"})

    def test_duplicate_or_foreign_addresses_are_rejected(self):
        for key, value in (
            ("SIP_AS_IP", self.settings["PCSCF_IP"]),
            ("AI_WORKER_IP", "198.51.100.10"),
            ("DNS_IP", self.settings["UPF_IP"]),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                start.validate({**self.settings, key: value})

    def test_ue_pool_must_be_outside_core_network(self):
        with self.assertRaisesRegex(ValueError, "пулы UE"):
            start.validate({**self.settings, "IMS_UE_CIDR": self.settings["LAB_NETWORK_CIDR"]})


class CxPeers(unittest.TestCase):
    def peer(self, state, disabled="False"):
        return (
            "\t\tFQDN: hss.example.test\n"
            f"\t\tDetails: {{\n\t\t\tState: {state}\n"
            f"\t\t\tDisabled: {disabled}\n\t\t\tApplications: 16777216:10415\n"
        )

    def test_open_enabled_peer_is_ready(self):
        self.assertTrue(start.connected_hss_peer(self.peer("I_Open"), "example.test"))

    def test_closed_or_disabled_peer_is_not_ready(self):
        self.assertFalse(start.connected_hss_peer(self.peer("Closed"), "example.test"))
        self.assertFalse(start.connected_hss_peer(self.peer("R_Open", "True"), "example.test"))


class Modes(unittest.TestCase):
    def test_baseline_uses_lab_env_unchanged(self):
        command, values = start.compose_command("baseline")
        self.assertIsNone(values)
        self.assertEqual(command[-1], str(ROOT / "docker-compose.yml"))

    def test_cpu_mode_forces_cpu_and_disables_ollama(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(start, "ROOT", Path(temp)):
            (Path(temp) / "app/config").mkdir(parents=True)
            (Path(temp) / "app/config/ai-profiles.json").write_text(
                (ROOT / "app/config/ai-profiles.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            command, values = start.compose_command("compact")
            overlay = Path(command[-1]).read_text(encoding="utf-8")
        self.assertEqual(values["AI_DEVICE"], "cpu")
        self.assertEqual(values["AI_STREAMING_ENABLED"], "0")
        self.assertEqual(values["AI_TRANSLATION_BACKEND"], "opus-mt")
        self.assertIn("llm-worker:\n    profiles: [unused-llm]", overlay)
        self.assertIn("/translation-models", overlay)


if __name__ == "__main__":
    unittest.main()
