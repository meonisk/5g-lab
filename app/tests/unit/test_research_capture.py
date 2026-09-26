"""Fault-injection tests for evidence persistence and exclusive execution."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/research/tools"))

from ims_research.capture import collect
from ims_research.common import load_json, sha256_file, write_json
from ims_research.execution import StandLock, run_gate


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root / "local/evidence/runs/test-run"
        self.run.mkdir(parents=True)
        self.design_path = self.root / "design.json"
        design = json.loads(
            (ROOT / "app/research/designs/local-instrumentation-smoke-v1.json").read_text()
        )
        design["capture"]["containers"] = []
        design["capture"]["gates"] = [
            {"id": name, "command": [sys.executable, "-c", "print('ok')"]}
            for name in ("first", "second")
        ]
        write_json(self.design_path, design)
        write_json(
            self.run / "manifest.json",
            {
                "collection_status": "PREPARED",
                "design": {"sha256": sha256_file(self.design_path)},
            },
        )
        key = self.root / "key"
        key.write_bytes(b"x" * 32)
        for name, value in (
            ("private_key_path", key),
            ("sensitive_values", ({}, [])),
            ("parse_env", {"RESEARCH_GATE_TIMEOUT_SECONDS": "3"}),
            ("docker_records", ([], [])),
        ):
            patcher = patch(f"ims_research.capture.{name}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def manifest(self):
        return load_json(self.run / "manifest.json")

    def test_success_is_sealed_against_recollection(self):
        collect(self.root, self.design_path, "test-run")
        before = (self.run / "manifest.json").read_bytes()
        self.assertEqual(self.manifest()["collection_status"], "COLLECTED")
        with self.assertRaisesRegex(ValueError, "already started"):
            collect(self.root, self.design_path, "test-run")
        self.assertEqual(before, (self.run / "manifest.json").read_bytes())

    def test_failure_preserves_prior_gate_and_stops_following_stimulus(self):
        outputs = [({"id": "first", "status": "COMPLETED", "returncode": 4}, "failed")]
        with patch("ims_research.capture.run_gate", side_effect=outputs) as runner:
            with self.assertRaises(RuntimeError):
                collect(self.root, self.design_path, "test-run")
        self.assertEqual(runner.call_count, 1)
        manifest = self.manifest()
        self.assertEqual(manifest["collection_status"], "FAILED")
        self.assertEqual(manifest["capture"]["gates"][0]["returncode"], 4)
        self.assertEqual(manifest["capture"]["gates"][1]["status"], "NOT_TESTED")
        self.assertTrue((self.run / "shareable/containers.json").exists())
        self.assertTrue((self.run / "checksums.sha256").exists())

    def test_interrupt_after_first_result_retains_it(self):
        outputs = [
            ({"id": "first", "status": "COMPLETED", "returncode": 0}, "ok"),
            KeyboardInterrupt(),
        ]
        with patch("ims_research.capture.run_gate", side_effect=outputs):
            with self.assertRaises(KeyboardInterrupt):
                collect(self.root, self.design_path, "test-run")
        manifest = self.manifest()
        self.assertEqual(manifest["collection_status"], "FAILED")
        self.assertEqual(manifest["capture"]["gates"][0]["returncode"], 0)

    def test_timeout_preserves_partial_output(self):
        gate = {
            "id": "slow",
            "command": [
                sys.executable,
                "-u",
                "-c",
                "import time; print('partial', flush=True); time.sleep(30)",
            ],
        }
        result, output = run_gate(self.root, gate, 0.5)
        self.assertEqual(result["status"], "TIMEOUT")
        self.assertIn("partial", output)
        self.assertNotEqual(result["returncode"], 0)

    def test_exclusive_lock_and_release(self):
        code = (
            "from pathlib import Path; from ims_research.execution import StandLock; "
            f"lock=StandLock(Path({str(self.root)!r})); lock.__enter__()"
        )
        import os

        environment = dict(os.environ, PYTHONPATH=str(ROOT / "app/research/tools"))
        with StandLock(self.root):
            result = subprocess.run(
                [sys.executable, "-c", code], env=environment, capture_output=True
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"owned by another", result.stderr)
        with StandLock(self.root):
            pass

    def test_atomic_write_failure_preserves_previous_json(self):
        path = self.root / "atomic.json"
        write_json(path, {"before": True})
        with patch("ims_research.common.os.replace", side_effect=OSError("simulated")):
            with self.assertRaises(OSError):
                write_json(path, {"after": True})
        self.assertEqual(load_json(path), {"before": True})


if __name__ == "__main__":
    unittest.main()
