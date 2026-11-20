"""Исследовательские SIM: UDR ядра OAI и чистка PyHSS после смены PLMN."""

import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
provision = importlib.import_module("provision")
research_sims = importlib.import_module("research_sims")
core_subscribers = importlib.import_module("core_subscribers")

KI = "0123456789ABCDEF0123456789ABCDEF"
OPC = "FEDCBA9876543210FEDCBA9876543210"


def settings():
    # Файл SIM — локальный файл стенда: в тестах его нет.
    return {**provision.read_env(), "RESEARCH_SIM_FILE": "local/test-absent/sims.csv"}


def plmn_imsi(env, tail):
    return env["MCC"] + env["MNC"] + str(tail).zfill(15 - len(env["MCC"] + env["MNC"]))


class FakeUdr:
    def __init__(self, rows):
        self.rows = rows
        self.sql = []

    def query(self, sql):
        self.sql.append(sql)
        return self.rows


class CoreSubscribers(unittest.TestCase):
    def test_existing_subscribers_are_kept_and_missing_are_planned(self):
        env = settings()
        ue1 = env["UE1_IMSI"]
        rows = [[ue1, env["UE1_IMS_K"].upper(), env["UE1_IMS_OPC"].upper()]]
        wanted, todo = core_subscribers.plan(FakeUdr(rows), env)
        self.assertEqual([entry["name"] for entry in wanted], ["UE1", "UE2"])
        self.assertEqual([entry["name"] for entry in todo], ["UE2"])

    def test_other_keys_for_same_imsi_stop_before_any_write(self):
        env = settings()
        udr = FakeUdr([[env["UE1_IMSI"], KI, OPC]])
        with self.assertRaisesRegex(RuntimeError, "другими ключами"):
            core_subscribers.plan(udr, env)
        self.assertEqual(len(udr.sql), 1)
        self.assertTrue(udr.sql[0].startswith("SELECT"))

    def test_sql_keeps_sqn_and_never_contains_plain_keys(self):
        env = settings()
        entry = {"name": "SIM", "imsi": plmn_imsi(env, 7), "ki": KI, "opc": OPC, "amf": "8000"}
        sql = core_subscribers.statements(env, [entry], ('{"sst": 1}', '{"ims": {}}'))
        self.assertNotIn(KI, sql)
        self.assertNotIn(OPC, sql)
        self.assertEqual(sql.count("ON DUPLICATE KEY UPDATE ueid = ueid"), 2)
        self.assertIn(KI.encode().hex(), sql)

    def test_session_template_drops_static_address(self):
        env = settings()
        dnn = env["IMS_DNN"]
        row = ['{"sst": 1}', '{"%s": {"staticIpAddress": [{"ipv4Addr": "x"}], "a": 1}}' % dnn]
        _, dnns = core_subscribers.session_template(FakeUdr([row]), env)
        self.assertEqual(dnns, '{"%s":{"a":1}}' % dnn)

    def test_subscriber_outside_plmn_is_rejected(self):
        env = settings()
        env["UE2_IMSI"] = "999990000000002"
        with self.assertRaisesRegex(ValueError, "не из PLMN"):
            core_subscribers.entries(env)


class FakeHss:
    def __init__(self, imsis):
        self.imsis = imsis
        self.calls = []

    def call(self, method, path, payload=None):
        self.calls.append((method, path))
        if path.endswith("/list?page=0&page_size=1000"):
            return [{"imsi": imsi} for imsi in self.imsis]
        if path.startswith("/auc/imsi/"):
            return {"auc_id": 5}
        return None

    def find(self, kind, imsi, id_field):
        return {"ims_subscriber": 3, "subscriber": 4}[kind]


class RetireForeignPlmn(unittest.TestCase):
    def test_old_plmn_subscribers_are_deleted_in_reference_order(self):
        env = settings()
        old = "00101" + "0" * 9 + "1"
        hss = FakeHss([plmn_imsi(env, 1), old])
        with patch("builtins.print"):
            research_sims.retire_foreign(hss, env)
        deletes = [path for method, path in hss.calls if method == "DELETE"]
        self.assertEqual(deletes, ["/ims_subscriber/3", "/subscriber/4", "/auc/5"])

    def test_nothing_deleted_when_all_in_plmn(self):
        env = settings()
        hss = FakeHss([plmn_imsi(env, 1)])
        research_sims.retire_foreign(hss, env)
        self.assertFalse([call for call in hss.calls if call[0] == "DELETE"])


if __name__ == "__main__":
    unittest.main()
