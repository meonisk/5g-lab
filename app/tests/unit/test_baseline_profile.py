"""Offline HTTP-mocked checks for temporary plain-call iFC selection."""

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "baseline_profile", ROOT / "app/tests/integration/baseline_profile.py"
)
PROFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILE)


class HttpReply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class BaselineProfileTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"imsi": "first", "ims_subscriber_id": 11, "ifc_path": "first.xml"},
            {"imsi": "second", "ims_subscriber_id": 22, "ifc_path": "second.xml"},
        ]
        self.patches = []
        self.fail_second_once = False
        self.fail_restore = False

    def http(self, request, timeout):
        self.assertEqual(timeout, 5)
        path = request.full_url.split("http://hss", 1)[1]
        if request.get_method() == "GET":
            self.assertIn("/ims_subscriber/list", path)
            return HttpReply(json.dumps(self.rows).encode())
        self.assertEqual(request.get_method(), "PATCH")
        payload = json.loads(request.data)
        self.assertEqual(set(payload), {"ifc_path"})
        subscriber_id = int(path.rsplit("/", 1)[1])
        self.patches.append((subscriber_id, payload["ifc_path"]))
        if self.fail_second_once and subscriber_id == 22 and payload["ifc_path"] == PROFILE.PROFILE:
            self.fail_second_once = False
            raise OSError("injected patch failure")
        if self.fail_restore and subscriber_id == 22 and payload["ifc_path"] == "second.xml":
            raise OSError("injected restore failure")
        next(row for row in self.rows if row["ims_subscriber_id"] == subscriber_id)["ifc_path"] = (
            payload["ifc_path"]
        )
        return HttpReply(b"{}")

    def settings(self):
        return {"UE1_IMSI": "first", "UE2_IMSI": "second", "PYHSS_API_BASE": "http://hss"}

    def test_template_has_three_identities_and_no_as_trigger(self):
        PROFILE.check_template()

    def test_peer_parser_requires_correct_hss_open_state_and_cx(self):
        output = (
            "\tPeers: {\n"
            "\t\tFQDN: hss.example.test\n"
            "\t\tDetails: {\n"
            "\t\t\tState: I_Open\n"
            "\t\t\tDisabled: False\n"
            "\t\t\tApplications: {\n"
            "\t\t\t\tappid:vendorid: 16777216:10415\n"
            "\t\t\t}\n\t\t}\n\t}\n"
        )
        self.assertTrue(PROFILE.connected_hss_peer(output, "example.test"))
        self.assertFalse(
            PROFILE.connected_hss_peer(output.replace("I_Open", "Closed"), "example.test")
        )
        self.assertFalse(
            PROFILE.connected_hss_peer(output.replace("16777216:10415", "4:10415"), "example.test")
        )
        self.assertFalse(PROFILE.connected_hss_peer(output, "other.test"))

    def test_wait_ims_peers_requires_both_cs_cfs(self):
        output = (
            "FQDN: hss.example.test\nDetails: {\nState: R_Open\n"
            "Disabled: False\nappid:vendorid: 16777216:10415\n}"
        )
        responses = [
            SimpleNamespace(returncode=0, stdout=output),
            SimpleNamespace(returncode=0, stdout=output.replace("R_Open", "Closed")),
            SimpleNamespace(returncode=0, stdout=output),
            SimpleNamespace(returncode=0, stdout=output),
        ]
        with (
            patch.object(PROFILE.ims_readiness.subprocess, "run", side_effect=responses) as rpc,
            patch.object(PROFILE.ims_readiness.time, "sleep") as sleep,
        ):
            PROFILE.wait_ims_peers({"IMS_DOMAIN": "example.test"})
        self.assertEqual(rpc.call_count, 4)
        sleep.assert_called_once()

    def test_context_restores_both_paths_and_journals_only_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "local/private/run"
            with (
                patch.object(PROFILE, "ROOT", root),
                patch.object(PROFILE.urllib.request, "urlopen", side_effect=self.http),
                patch.object(PROFILE.subprocess, "run") as docker,
            ):
                with PROFILE.baseline_ifc(self.settings(), run_dir) as state:
                    self.assertEqual([row["ifc_path"] for row in self.rows], [PROFILE.PROFILE] * 2)
                self.assertTrue(state.rollback_ok)
            docker.assert_called_once()
            self.assertEqual([row["ifc_path"] for row in self.rows], ["first.xml", "second.xml"])
            journal = json.loads(state.journal.read_text())
            self.assertEqual(journal["rollback_status"], "RESTORED")
            self.assertEqual(set(journal), {"rows", "rollback_status"})
            self.assertEqual(set(journal["rows"][0]), {"id", "ifc_path"})

    def test_partial_patch_failure_restores_both_original_paths(self):
        self.fail_second_once = True
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "local/private/run"
            with (
                patch.object(PROFILE, "ROOT", root),
                patch.object(PROFILE.urllib.request, "urlopen", side_effect=self.http),
                patch.object(PROFILE.subprocess, "run"),
            ):
                with self.assertRaisesRegex(OSError, "injected patch failure"):
                    with PROFILE.baseline_ifc(self.settings(), run_dir):
                        self.fail("body must not run")
            self.assertEqual([row["ifc_path"] for row in self.rows], ["first.xml", "second.xml"])
            self.assertEqual(
                json.loads((run_dir / "baseline-ifc-journal.json").read_text())["rollback_status"],
                "RESTORED",
            )

    def test_restore_failure_is_reported_and_journaled(self):
        self.fail_restore = True
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "local/private/run"
            with (
                patch.object(PROFILE, "ROOT", root),
                patch.object(PROFILE.urllib.request, "urlopen", side_effect=self.http),
                patch.object(PROFILE.subprocess, "run"),
            ):
                with self.assertRaisesRegex(RuntimeError, "restore failed"):
                    with PROFILE.baseline_ifc(self.settings(), run_dir):
                        pass
            self.assertEqual(
                json.loads((run_dir / "baseline-ifc-journal.json").read_text())["rollback_status"],
                "RESTORE_FAILED",
            )


if __name__ == "__main__":
    unittest.main()
