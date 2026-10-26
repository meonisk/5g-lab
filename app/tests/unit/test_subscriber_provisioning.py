"""scripts/provision.py без PyHSS: проверка ключей до записи и сохранение существующего AuC."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import provision  # noqa: E402

KEYS = {"ki": "A" * 32, "opc": "B" * 32, "amf": "8000"}
ENTRY = {"name": "UE1", "imsi": "001", "msisdn": "1001", **KEYS}


class FakeHss:
    """Запоминает запросы; GET /auc/imsi отдаёт записи по очереди (последняя повторяется)."""

    def __init__(self, *auc):
        self.auc = list(auc)
        self.calls = []

    def call(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if path.startswith("/auc/imsi/"):
            return self.auc.pop(0) if len(self.auc) > 1 else self.auc[0]
        return None


class Subscribers(unittest.TestCase):
    def test_repository_lab_env_defines_four_valid_subscribers(self):
        entries = provision.subscribers(provision.read_env())
        self.assertEqual([e["name"] for e in entries], ["UE1", "UE2", "SIPUE1", "SIPUE2"])

    def test_bad_key_is_rejected_before_any_request(self):
        settings = {**provision.read_env(), "SIPUE2_IMS_OPC": "not-hex"}
        with self.assertRaisesRegex(ValueError, "SIPUE2: opc"):
            provision.subscribers(settings)

    def test_phone_and_test_client_cannot_share_imsi(self):
        settings = provision.read_env()
        with self.assertRaisesRegex(ValueError, "различаться"):
            provision.subscribers({**settings, "SIPUE1_IMSI": settings["UE1_IMSI"]})


class ExistingAuc(unittest.TestCase):
    def test_missing_auc_is_created_with_initial_sqn(self):
        hss = FakeHss(None, {"auc_id": 7})
        self.assertEqual(provision.ensure_auc(hss, ENTRY, False), 7)
        self.assertEqual(hss.calls[1][:2], ("PUT", "/auc/"))
        self.assertEqual(hss.calls[1][2]["sqn"], 96)

    def test_matching_keys_are_preserved_without_patch(self):
        hss = FakeHss({"auc_id": 11})
        with patch.object(provision, "stored_keys", return_value={"auc_id": 11, **KEYS}) as stored:
            self.assertEqual(provision.ensure_auc(hss, ENTRY, False), 11)
        stored.assert_called_once_with("001")
        self.assertEqual(hss.calls, [("GET", "/auc/imsi/001", None)])

    def test_mismatch_stops_unless_replacement_is_explicit(self):
        hss = FakeHss({"auc_id": 11, **KEYS, "ki": "C" * 32})
        with self.assertRaisesRegex(RuntimeError, "--replace-keys"):
            provision.ensure_auc(hss, ENTRY, False)
        self.assertEqual(provision.ensure_auc(hss, ENTRY, True), 11)
        self.assertIn(("PATCH", "/auc/11"), [call[:2] for call in hss.calls])


if __name__ == "__main__":
    unittest.main()
