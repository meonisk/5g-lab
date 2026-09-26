"""Safe migration preflight tests; no Docker daemon or database is touched."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "migrate_mysql_storage", ROOT / "scripts/migrate_mysql_storage.py"
)
MIGRATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATE)


class MysqlMigrationTests(unittest.TestCase):
    def test_backup_requires_both_system_and_ims_databases(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / "ibdata1").touch()
            (path / "mysql").mkdir()
            with self.assertRaisesRegex(RuntimeError, "ims_hss_db"):
                MIGRATE.validate_backup(path)
            (path / "ims_hss_db").mkdir()
            self.assertEqual(MIGRATE.validate_backup(path), path.resolve())

    def test_running_container_cannot_be_migrated(self):
        with patch.object(
            MIGRATE,
            "checked",
            return_value=SimpleNamespace(stdout="old-id|running\n"),
        ):
            with self.assertRaisesRegex(RuntimeError, "must be stopped"):
                MIGRATE.stopped_container_id()

    def test_existing_backup_path_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "local/private/mysql-cold").mkdir(parents=True)
            with (
                patch.object(MIGRATE, "ROOT", root),
                patch.object(MIGRATE, "RECEIPT", root / "local/private/receipt.json"),
            ):
                with self.assertRaisesRegex(RuntimeError, "already exists"):
                    MIGRATE.require_new_backup(root / "local/private/mysql-cold")

    def test_existing_volume_cannot_be_overwritten(self):
        with patch.object(
            MIGRATE.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0),
        ):
            with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
                MIGRATE.require_new_volume()


if __name__ == "__main__":
    unittest.main()
