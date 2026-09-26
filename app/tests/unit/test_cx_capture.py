"""Cx PCAP capture lifecycle without Docker or network access."""

import io
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.tests.integration import cx_capture


class FakeProcess:
    def __init__(self, args, *, stdout, stderr_line=b"CX_CAPTURE_READY\n", **_):
        self.args = args
        self.stdin = io.BytesIO()
        self.stderr = io.BytesIO(stderr_line)
        self.returncode = None
        stdout.write(struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
        stdout.flush()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


class CxCapture(unittest.TestCase):
    def test_private_pcap_started_then_owned_process_stopped(self):
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "cx.pcap"
            processes = []

            def start(*args, **kwargs):
                process = FakeProcess(*args, **kwargs)
                processes.append(process)
                return process

            with patch.object(cx_capture.subprocess, "Popen", side_effect=start):
                with cx_capture.capture(path, seconds=2, port=3868) as captured:
                    self.assertEqual(captured, path)
                    self.assertTrue(path.is_file())

            self.assertEqual(path.read_bytes()[:4], b"\xd4\xc3\xb2\xa1")
            self.assertEqual(processes[0].args[-2:], ["3868", "2"])
            self.assertEqual(processes[0].returncode, 0)

    def test_failed_readiness_removes_partial_artifact(self):
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "cx.pcap"
            with patch.object(
                cx_capture.subprocess,
                "Popen",
                side_effect=lambda *a, **k: FakeProcess(*a, stderr_line=b"failed\n", **k),
            ):
                with self.assertRaisesRegex(RuntimeError, "before readiness"):
                    with cx_capture.capture(path, seconds=2):
                        pass
            self.assertFalse(path.exists())

    def test_existing_artifact_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "cx.pcap"
            path.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                with cx_capture.capture(path):
                    pass
            self.assertEqual(path.read_bytes(), b"existing")
