"""Offline checks for the launcher's base and full startup boundaries."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("start_lab", ROOT / "scripts/start_lab.py")
START = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(START)


class StartLabTests(unittest.TestCase):
    def launch(self, *arguments):
        commands = []
        gates = []
        outputs = []
        stages = []

        def fake_run(command, _message, **_kwargs):
            commands.append(command)
            if "{{.State.Health.Status}}" in command:
                return SimpleNamespace(stdout="healthy")
            return SimpleNamespace(stdout="0")

        with (
            patch.object(sys, "argv", ["start_lab.py", *arguments]),
            patch.object(START.shutil, "which", return_value="docker"),
            patch.object(START, "bash_command", return_value="bash"),
            patch.object(START, "prepare_sctp"),
            patch.object(START, "guard_mysql_storage"),
            patch.object(START, "generate_dialogues") as dialogues,
            patch.object(START, "wait_for_pyhss"),
            patch.object(START, "wait_for_pyhss_cx", side_effect=lambda _: stages.append("cx")),
            patch.object(
                START, "public_environment", return_value={"LLM_WARMUP_TIMEOUT_SECONDS": "1"}
            ),
            patch.object(
                START, "provision_subscribers", side_effect=lambda _: stages.append("provision")
            ),
            patch.object(START, "restart_ims_chain", side_effect=lambda: stages.append("ims")),
            patch.object(START, "wait_ims_peers", side_effect=lambda _: stages.append("peer")),
            patch.object(
                START, "restart_registration_chain", side_effect=lambda: stages.append("ue")
            ),
            patch.object(
                START, "run_gates", side_effect=lambda _bash, selected: gates.extend(selected)
            ),
            patch.object(START, "run", side_effect=fake_run),
            patch("builtins.print", side_effect=lambda message: outputs.append(message)),
        ):
            START.main()

        self.assertEqual(stages, ["provision", "cx", "ims", "peer", "ue"])
        return commands, gates, outputs, dialogues

    def test_base_mode_selects_only_base_services_and_mandatory_gates(self):
        commands, gates, outputs, dialogues = self.launch("--base-only", "--skip-verify")
        compose_up = [c for c in commands if c[: len(START.COMPOSE)] == START.COMPOSE]
        self.assertEqual(len(compose_up), 2)
        self.assertEqual(compose_up[0], START.COMPOSE + ["up", "-d", "--wait", "oai-db"])
        self.assertEqual(
            compose_up[1],
            START.COMPOSE + ["up", "-d", "--build", *START.BASE_SERVICES],
        )
        self.assertFalse(
            set(START.BASE_SERVICES)
            & {
                "ai-worker",
                "llm-worker",
                "llm-model-init",
                "voice-agent",
                "sip-as",
                "media-adapter",
            }
        )
        self.assertEqual(gates, list(START.BASE_GATES))
        self.assertNotIn(["docker", "wait", "lab-llm-model-init"], commands)
        dialogues.assert_not_called()
        self.assertIn("BASE: READY", outputs[-1])

    def test_full_skip_verify_cannot_claim_ready(self):
        commands, gates, outputs, dialogues = self.launch("--skip-verify")
        self.assertIn(["docker", "wait", "lab-llm-model-init"], commands)
        dialogues.assert_called_once()
        self.assertEqual(gates, [])
        self.assertIn("STARTED/UNVERIFIED", outputs[-1])

    def test_full_start_runs_base_then_service_gates(self):
        _, gates, outputs, _ = self.launch()
        self.assertEqual(gates, list(START.BASE_GATES + START.SERVICE_GATES))
        self.assertIn("LAB: READY", outputs[-1])

    def test_legacy_mysql_writable_layer_blocks_compose(self):
        with patch.object(
            START.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="old-id|exited|[]"),
        ):
            with self.assertRaisesRegex(RuntimeError, "migrate its stopped datadir"):
                START.guard_mysql_storage()

    def test_mounted_mysql_volume_allows_compose(self):
        mounts = '[{"Type":"volume","Destination":"/var/lib/mysql","Name":"lab-docker_mysql-data"}]'
        with patch.object(
            START.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout=f"new-id|running|{mounts}"),
        ):
            START.guard_mysql_storage()

    def test_cx_timeout_blocks_ims_restart(self):
        with (
            patch.object(START.subprocess, "run", return_value=SimpleNamespace(returncode=1)),
            patch.object(START.time, "sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Cx listener"):
                START.wait_for_pyhss_cx({"PYHSS_IP": "127.0.0.1", "PYHSS_BIND_PORT": "3868"})

    def test_migration_receipt_allows_only_matching_stopped_container(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backup = root / "local/private/mysql-cold"
            (backup / "ims_hss_db").mkdir(parents=True)
            (backup / "ibdata1").touch()
            receipt = {
                "source_container_id": "old-id",
                "volume": "lab-docker_mysql-data",
                "backup_dir": str(backup),
                "rollback_image": "rollback:test",
                "rollback_image_id": "sha256:abc",
            }
            (root / "local/private/mysql-storage-migration.json").write_text(
                json.dumps(receipt), encoding="utf-8"
            )
            responses = [
                SimpleNamespace(returncode=0, stdout="old-id|exited|[]"),
                SimpleNamespace(returncode=0),
                SimpleNamespace(returncode=0, stdout="sha256:abc\n"),
            ]
            with (
                patch.object(START, "ROOT", root),
                patch.object(START.subprocess, "run", side_effect=responses),
            ):
                START.guard_mysql_storage()
            with (
                patch.object(START, "ROOT", root),
                patch.object(
                    START.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0, stdout="different-id|exited|[]"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "rollback receipt"):
                    START.guard_mysql_storage()


if __name__ == "__main__":
    unittest.main()
