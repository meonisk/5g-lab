"""Offline state-machine tests for explicit AKA migration and rollback."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import migrate_subscriber_keys as migration


class FakeBackend:
    def __init__(self):
        self.mongo_rows = {
            imsi: {
                "imsi": imsi,
                "security": {"k": "A" * 32, "opc": "B" * 32, "amf": "8000", "sqn": 17},
            }
            for imsi in ("001", "002")
        }
        self.auc_rows = {
            imsi: {
                "imsi": imsi,
                "auc_id": index,
                "ki": "A" * 32,
                "opc": "B" * 32,
                "amf": "8000",
                "sqn": 96 + index,
            }
            for index, imsi in enumerate(("001", "002"), 1)
        }
        self.fail_on = None
        self.calls = []
        self.stopped_count = 0

    def stopped(self):
        self.stopped_count += 1
        if self.fail_on == "sqn-advance" and self.stopped_count == 2:
            self.auc_rows["001"]["sqn"] += 1
        if self.fail_on == "running" and self.stopped_count > 1:
            raise RuntimeError("container started")

    def mongo(self, operation, payload):
        self.calls.append(("mongo", operation))
        if operation == "read":
            return [
                dict(self.mongo_rows[imsi], security=dict(self.mongo_rows[imsi]["security"]))
                for imsi in reversed(payload["imsis"])
            ]
        imsi = payload["imsi"]
        if operation == "set":
            self.mongo_rows[imsi]["security"].update(payload["security"])
            if self.fail_on == f"mongo-{imsi}":
                raise RuntimeError("injected Mongo fault after write")
        else:
            if self.fail_on == "restore-noop" and imsi == "002":
                return 0
            self.mongo_rows[imsi]["security"] = dict(payload["security"])
        return 1

    def auc(self, imsi, payload=None, auc_id=None):
        self.calls.append(("auc", "read" if payload is None else "patch"))
        if payload is not None:
            self.auc_rows[imsi].update(payload)
            if self.fail_on == "sqn-reset" and payload["ki"] != "A" * 32:
                self.auc_rows[imsi]["sqn"] = 0
            if self.fail_on == "interrupt" and payload["ki"] != "A" * 32:
                raise KeyboardInterrupt
            if self.fail_on == f"auc-{imsi}" and payload["ki"] != "A" * 32:
                raise RuntimeError("injected PyHSS fault after write")
        return dict(self.auc_rows[imsi])

    def auc_inventory(self):
        return [{"imsi": row["imsi"], "auc_id": row["auc_id"]} for row in self.auc_rows.values()]

    def pyhss_rows(self, imsis):
        auc = [dict(self.auc_rows[imsi]) for imsi in imsis]
        return {
            "auc": auc,
            "subscriber": [{"imsi": row["imsi"], "auc_id": row["auc_id"]} for row in auc],
            "ims_subscriber": [{"imsi": row["imsi"]} for row in auc],
        }


class KeyMigration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "app/config").mkdir(parents=True)
        (self.root / "local/secrets").mkdir(parents=True)
        (self.root / "local/private").mkdir(parents=True)
        (self.root / "app/config/lab.env").write_text("UE1_IMSI=001\nUE2_IMSI=002\n")
        self.secret_path = self.root / "local/secrets/ims.env"
        self.original = (
            "IMS_DIGEST_PASSWORD=unchanged\n"
            + "SUBSCRIBER_K="
            + "A" * 32
            + "\n"
            + "SUBSCRIBER_OPC="
            + "B" * 32
            + "\nSUBSCRIBER_AMF=8000\n"
        ).encode()
        self.secret_path.write_bytes(self.original)
        self.backend = FakeBackend()
        self.backup = self.root / "local/private/migration-one"

    def migrate(self, apply=True):
        return migration.migrate(self.backend, self.backup, apply=apply, root=self.root)

    def test_dry_run_changes_nothing(self):
        self.migrate(apply=False)
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.secret_path.read_bytes(), self.original)
        self.assertFalse(
            any(operation != "read" for kind, operation in self.backend.calls if kind == "mongo")
        )

    def test_mongo_key_material_is_only_on_stdin_with_timeout(self):
        output = SimpleNamespace(returncode=0, stdout=migration.MARKER + "1\n")
        with patch.object(migration.subprocess, "run", return_value=output) as run:
            result = migration.Backend("http://localhost").mongo(
                "set", {"imsi": "001", "security": {"k": "secret-example"}}
            )
        self.assertEqual(result, 1)
        args, kwargs = run.call_args
        self.assertNotIn("secret-example", " ".join(args[0]))
        self.assertIn("secret-example", kwargs["input"])
        self.assertEqual(kwargs["timeout"], 30)

    def test_api_omitted_keys_use_consistent_db_row(self):
        backend = migration.Backend("http://localhost")
        backend._db_rows = self.backend.pyhss_rows(["001", "002"])
        api = {"auc_id": 1, "imsi": "001", "amf": "8000", "sqn": 97}
        with patch.object(
            migration.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(api).encode())
        ):
            result = backend.auc("001")
        self.assertEqual(result["ki"], "A" * 32)
        self.assertEqual(result["sqn"], 97)
        api["sqn"] = 0
        with patch.object(
            migration.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(api).encode())
        ):
            with self.assertRaisesRegex(RuntimeError, "PyHSS AuC request failed"):
                backend.auc("001")

    def test_success_backs_up_and_preserves_sqn_and_digest(self):
        self.migrate()
        self.assertEqual((self.backup / "secrets.env").read_bytes(), self.original)
        self.assertEqual(
            json.loads((self.backup / "receipt.json").read_text())["status"], "applied"
        )
        target = migration.env_values(self.secret_path)
        self.assertEqual(target["IMS_DIGEST_PASSWORD"], "unchanged")
        self.assertEqual(
            len({target[f"UE{ue}_{domain}_K"] for ue in (1, 2) for domain in ("5GS", "IMS")}), 4
        )
        self.assertEqual([self.backend.auc_rows[imsi]["sqn"] for imsi in ("001", "002")], [97, 98])
        self.assertEqual(
            [self.backend.mongo_rows[imsi]["security"]["sqn"] for imsi in ("001", "002")], [17, 17]
        )
        with self.assertRaisesRegex(RuntimeError, "destination already configured"):
            self.migrate()

    def test_faults_rollback_both_databases_and_secret_file(self):
        for fault in ("mongo-002", "auc-001", "auc-002", "interrupt"):
            with self.subTest(fault=fault):
                self.setUp()
                self.backend.fail_on = fault
                with self.assertRaisesRegex(RuntimeError, "rolled_back"):
                    self.migrate()
                self.assertEqual(self.secret_path.read_bytes(), self.original)
                self.assertEqual(
                    json.loads((self.backup / "receipt.json").read_text())["status"], "rolled_back"
                )
                for imsi in ("001", "002"):
                    self.assertEqual(self.backend.mongo_rows[imsi]["security"]["k"], "A" * 32)
                    self.assertEqual(self.backend.auc_rows[imsi]["ki"], "A" * 32)

    def test_sqn_change_after_backup_aborts_without_restoring_stale_sqn(self):
        self.backend.fail_on = "sqn-advance"
        with self.assertRaisesRegex(RuntimeError, "aborted_no_changes"):
            self.migrate()
        self.assertEqual(self.backend.auc_rows["001"]["sqn"], 98)
        self.assertEqual(self.secret_path.read_bytes(), self.original)
        self.assertEqual(
            json.loads((self.backup / "receipt.json").read_text())["status"], "aborted_no_changes"
        )

    def test_restore_noop_marks_receipt_incomplete(self):
        self.backend.fail_on = "restore-noop"
        original_auc = self.backend.auc

        def fail_after_first_patch(imsi, payload=None, auc_id=None):
            result = original_auc(imsi, payload, auc_id)
            if payload is not None and payload["ki"] != "A" * 32:
                raise RuntimeError("injected write error")
            return result

        self.backend.auc = fail_after_first_patch
        with self.assertRaisesRegex(RuntimeError, "rollback_incomplete"):
            self.migrate()
        receipt = json.loads((self.backup / "receipt.json").read_text())
        self.assertIn("Open5GS", receipt["rollback_errors"])

    def test_postupdate_sqn_change_rolls_back_before_secret_commit(self):
        self.backend.fail_on = "sqn-reset"
        with self.assertRaisesRegex(RuntimeError, "rolled_back"):
            self.migrate()
        self.assertEqual(self.secret_path.read_bytes(), self.original)
        self.assertEqual([self.backend.auc_rows[imsi]["sqn"] for imsi in ("001", "002")], [97, 98])
        self.assertEqual(
            json.loads((self.backup / "receipt.json").read_text())["status"], "rolled_back"
        )

    def test_source_mismatch_stops_before_backup(self):
        self.backend.auc_rows["001"]["ki"] = "C" * 32
        with self.assertRaisesRegex(RuntimeError, "source mismatch"):
            self.migrate()
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.secret_path.read_bytes(), self.original)

    def test_duplicate_auc_identity_stops_before_backup(self):
        self.backend.auc_inventory = lambda: [
            {"imsi": "001", "auc_id": 1},
            {"imsi": "001", "auc_id": 3},
            {"imsi": "002", "auc_id": 2},
        ]
        with self.assertRaisesRegex(RuntimeError, "exactly one PyHSS"):
            self.migrate()
        self.assertFalse(self.backup.exists())

    def test_shared_auc_link_stops_before_backup(self):
        original = self.backend.pyhss_rows

        def shared(imsis):
            rows = original(imsis)
            rows["subscriber"].append({"imsi": "other", "auc_id": 1})
            return rows

        self.backend.pyhss_rows = shared
        with self.assertRaisesRegex(RuntimeError, "shared by another subscriber"):
            self.migrate()
        self.assertFalse(self.backup.exists())
