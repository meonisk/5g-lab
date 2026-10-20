"""OAI and partner boundaries: AKA state, routing, and no partner core dependency."""

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
CONFIG = importlib.import_module("oai_config")
SUBSCRIBERS = importlib.import_module("oai_subscribers")
PARTNER = importlib.import_module("start_partner")
INIT = importlib.import_module("initialize_local")


class OaiIntegration(unittest.TestCase):
    def setUp(self):
        self.env = INIT.read_values(ROOT / "app/config/lab.env")
        self.env["OAI_DB_PASSWORD"] = "a" * 48
        for ue in (1, 2):
            self.env[f"UE{ue}_5GS_K"] = str(ue) * 32
            self.env[f"UE{ue}_5GS_OPC"] = "a" * 32
            self.env[f"UE{ue}_5GS_AMF"] = "8000"

    def test_private_render_routes_both_dnns_without_blanket_nat(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            CONFIG.render(root, self.env)
            for nf in CONFIG.NFS:
                config = json.loads((root / "local/oai" / f"{nf}.yaml").read_text())
                self.assertEqual(
                    config["database"]["password"], "a" * 48
                ) if nf == "udr" else self.assertNotIn("database", config)
                self.assertFalse(config["upf"]["support_features"]["enable_snat"])
                self.assertEqual([d["dnn"] for d in config["dnns"]], ["internet", "ims"])
                self.assertFalse(config["smf"]["support_features"]["use_local_subscription_info"])

    def test_auth_insert_never_updates_existing_sqn_or_keys(self):
        imsi, keys = SUBSCRIBERS.profiles(self.env)[0]
        statements = SUBSCRIBERS.statements(self.env, imsi, keys)
        update = statements[0].split("ON DUPLICATE KEY UPDATE", 1)[1]
        self.assertEqual(update.strip(), "ueid=ueid;")
        self.assertIn(SUBSCRIBERS.sql_value({"sst": 1, "sd": "FFFFFF"}), statements[2])

    def test_changed_authentication_key_blocks_all_writes(self):
        with (
            patch.object(SUBSCRIBERS, "read_values", return_value=self.env),
            patch.object(SUBSCRIBERS, "query", return_value="wrong\tkey\t8000") as query,
        ):
            with self.assertRaisesRegex(RuntimeError, "Ключи OAI AKA не совпадают"):
                SUBSCRIBERS.main()
            self.assertEqual(query.call_count, 1)
            self.assertTrue(query.call_args.args[0].startswith("SELECT"))

    def test_partner_requires_routable_non_overlapping_lan(self):
        self.env["IMS_PARENT_INTERFACE"] = "eth1"
        self.env["IMS_ROUTE_GATEWAY"] = self.env["UPF_IP"]
        PARTNER.validate(self.env)
        self.env["IMS_UE_CIDR"] = self.env["LAB_NETWORK_CIDR"]
        with self.assertRaisesRegex(ValueError, "пересекаться"):
            PARTNER.validate(self.env)

    def test_partner_rejects_missing_gateway_and_custom_domain(self):
        self.env["IMS_PARENT_INTERFACE"] = "eth1"
        self.env["IMS_ROUTE_GATEWAY"] = ""
        with self.assertRaisesRegex(ValueError, "IMS_ROUTE_GATEWAY"):
            PARTNER.validate(self.env)
        self.env["IMS_ROUTE_GATEWAY"] = self.env["UPF_IP"]
        self.env["IMS_DOMAIN"] = "ims.partner.example"
        with self.assertRaisesRegex(ValueError, "ims.mnc001.mcc001"):
            PARTNER.validate(self.env)

    def test_ims_only_initialization_does_not_need_5gs_keys_or_core(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(INIT, "ROOT", root),
                patch.object(INIT, "SECRET_PATH", root / "local/secrets/ims.env"),
            ):
                INIT.main(ims_only=True)
                values = INIT.read_values(INIT.SECRET_PATH)
                self.assertIn("UE1_IMS_K", values)
                self.assertNotIn("UE1_5GS_K", values)
                self.assertNotIn("OAI_DB_PASSWORD", values)
                self.assertFalse((root / "local/oai").exists())


if __name__ == "__main__":
    unittest.main()
