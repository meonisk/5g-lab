"""Regression checks for frozen research gate identity and results."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/research/tools"))

from ims_research.common import checksum_tree
from ims_research.gate_contract import captured_gate_errors, captured_log_errors, expected_gate_ids
from ims_research.integrity import artifact_errors
from ims_research.validation import validate_design


class ResearchGateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = ROOT / "app/research/designs/local-instrumentation-smoke-v1.json"
        cls.design = json.loads(path.read_text(encoding="utf-8"))

    def test_frozen_design_is_valid(self) -> None:
        validate_design(self.design)

    def test_same_count_with_substituted_gate_fails(self) -> None:
        expected = expected_gate_ids(self.design["capture"])
        actual = [{"id": gate_id, "returncode": 0} for gate_id in expected]
        actual[-1]["id"] = "substitute-gate"
        errors = captured_gate_errors(actual, expected)
        self.assertTrue(any("missing" in error for error in errors))
        self.assertTrue(any("unexpected" in error for error in errors))

    def test_duplicate_and_boolean_return_code_fail(self) -> None:
        expected = expected_gate_ids(self.design["capture"])
        actual = [{"id": gate_id, "returncode": 0} for gate_id in expected]
        actual[0]["returncode"] = False
        actual[-1]["id"] = actual[0]["id"]
        errors = captured_gate_errors(actual, expected)
        self.assertTrue(any("duplicate" in error for error in errors))
        self.assertTrue(any("failed" in error for error in errors))

    def test_malformed_design_gate_schema_fails_cleanly(self) -> None:
        for bad_gate in (
            {"id": "../unsafe", "command": ["python", "test.py"]},
            {"id": "safe", "command": []},
            {"id": "safe", "command": "python test.py"},
            {"id": "safe", "command": ["python", 2]},
        ):
            with self.subTest(bad_gate=bad_gate):
                design = copy.deepcopy(self.design)
                design["capture"]["gates"] = [bad_gate]
                with self.assertRaises(ValueError):
                    validate_design(design)

    def test_duplicate_design_gate_id_fails(self) -> None:
        design = copy.deepcopy(self.design)
        design["capture"]["gates"].append(copy.deepcopy(design["capture"]["gates"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_design(design)

    def test_empty_design_gate_inventory_fails(self) -> None:
        design = copy.deepcopy(self.design)
        design["capture"]["gates"] = []
        with self.assertRaisesRegex(ValueError, "nonempty"):
            validate_design(design)

    def test_timeout_cannot_pass_with_zero_return_code(self) -> None:
        expected = expected_gate_ids(self.design["capture"])
        actual = [{"id": gate_id, "returncode": 0} for gate_id in expected]
        actual[0]["status"] = "TIMEOUT"
        self.assertTrue(
            any("did not complete" in error for error in captured_gate_errors(actual, expected))
        )
        actual[0]["status"] = "COMPLETED"
        self.assertEqual(captured_gate_errors(actual, expected), [])

    def test_malformed_captured_gate_fails_cleanly(self) -> None:
        expected = expected_gate_ids(self.design["capture"])
        for actual in (
            None,
            {},
            [None],
            [{"id": expected[0]}],
            [{"id": expected[0], "returncode": "0"}],
        ):
            with self.subTest(actual=actual):
                self.assertTrue(captured_gate_errors(actual, expected))

    def test_malformed_container_capture_fails_cleanly(self) -> None:
        expected = self.design["capture"]["containers"]
        for actual in (None, {}, [["unhashable"]], [None], expected[:-1], expected + expected[:1]):
            with self.subTest(actual=actual):
                self.assertTrue(captured_log_errors(actual, expected))

    def test_artifact_inventory_and_gate_copy(self) -> None:
        design = copy.deepcopy(self.design)
        design["capture"]["gates"] = [{"id": "one", "command": ["true"]}]
        design["capture"]["containers"] = ["lab-one"]
        capture = {"gates": [{"id": "one", "returncode": 0}]}
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "shareable/gates").mkdir(parents=True)
            (run_dir / "shareable/logs").mkdir()
            (run_dir / "manifest.json").write_text("{}")
            (run_dir / "shareable/gates.json").write_text(json.dumps(capture["gates"]))
            (run_dir / "shareable/gates/one.log").write_text("ok")
            (run_dir / "shareable/logs/lab-one.log").write_text("ok")
            checksum_tree(run_dir)
            self.assertEqual(artifact_errors(run_dir, design, capture), [])
            (run_dir / "shareable/gates/one.log").unlink()
            self.assertTrue(
                any(
                    "required artifact missing" in e
                    for e in artifact_errors(run_dir, design, capture)
                )
            )
            (run_dir / "shareable/gates/one.log").write_text("ok")
            (run_dir / "shareable/gates.json").write_text("[]")
            self.assertTrue(any("differs" in e for e in artifact_errors(run_dir, design, capture)))

    def test_checksum_rows_and_unhashed_file_fail(self) -> None:
        design = copy.deepcopy(self.design)
        design["capture"]["gates"] = [{"id": "one", "command": ["true"]}]
        design["capture"]["containers"] = []
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "shareable/gates").mkdir(parents=True)
            (run_dir / "manifest.json").write_text("{}")
            (run_dir / "shareable/gates.json").write_text("[]")
            (run_dir / "shareable/gates/one.log").write_text("ok")
            (run_dir / "checksums.sha256").write_text("", encoding="utf-8")
            errors = artifact_errors(run_dir, design, {"gates": []})
            self.assertTrue(any("not hashed" in e for e in errors))
            (run_dir / "checksums.sha256").write_text(
                "0" * 64 + "  ../escape\n" + "0" * 64 + "  ../escape\n"
            )
            self.assertTrue(
                any("unsafe checksum" in e for e in artifact_errors(run_dir, design, {"gates": []}))
            )


if __name__ == "__main__":
    unittest.main()
