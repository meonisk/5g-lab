"""Offline exit-status contract for the package 01 shell verifier."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "app/tests/integration/verify.sh"
BASH = shutil.which("bash")
GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
if GIT_BASH.exists():
    BASH = str(GIT_BASH)


@unittest.skipUnless(BASH, "Bash is unavailable")
class VerifyScript(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        script = root / "app/tests/integration/verify.sh"
        script.parent.mkdir(parents=True)
        shutil.copyfile(SOURCE, script)
        loader = root / "scripts/load-lab-env.sh"
        loader.parent.mkdir()
        loader.write_text(
            "INTERNET_UE_GATEWAY=192.0.2.1\n"
            "INTERNET_UE_CIDR=192.0.2.0/24\n"
            "INTERNET_PROBE_IP=198.51.100.1\n"
            "ipv4_in_cidr() { [[ $1 == 192.0.2.* ]]; }\n",
            encoding="utf-8",
        )
        docker = root / "bin/docker"
        docker.parent.mkdir()
        docker.write_text(
            "#!/usr/bin/env bash\n"
            'case "$*" in\n'
            "  'logs lab-gnb') output='SCTP connection established\nNG Setup procedure' ;;\n"
            "  'logs lab-ue1'|'logs lab-ue2') output='Initial Registration is successful\nPDU Session establishment is successful\nTUN interface' ;;\n"
            "  *uesimtun0*) output='192.0.2.2' ;;\n"
            "  *uesimtun1*) output='' ;;\n"
            "  *'ip -4 addr show ogstun'*) output='inet 192.0.2.1/24' ;;\n"
            "  *'mongosh --quiet --eval'*) output='[{ imsi: 001 }]';;\n"
            "  *'ping -I '*) output='4 packets received' ;;\n"
            "esac\n"
            'if [[ -n ${FAIL_MATCH:-} && "$*" == *"$FAIL_MATCH"* ]]; then exit 1; fi\n'
            "if [[ -n ${OMIT_EVENT:-} ]]; then output=${output//$OMIT_EVENT/}; fi\n"
            "printf '%s\\n' \"$output\"\n",
            encoding="utf-8",
        )
        docker.chmod(0o755)
        self.script = script
        self.env = {**os.environ, "PATH": str(docker.parent) + os.pathsep + os.environ["PATH"]}

    def run_verify(self, **env):
        return subprocess.run(
            [BASH, str(self.script)],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_success(self):
        result = self.run_verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_required_failures_are_nonzero(self):
        for command in (
            "logs lab-gnb",
            "logs lab-ue1",
            "ping -I",
            "ip -4 addr show ogstun",
            "mongosh",
        ):
            with self.subTest(command=command):
                result = self.run_verify(FAIL_MATCH=command)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("FAIL:", result.stderr)

    def test_missing_tun_and_log_event_fail(self):
        for env in (
            {"FAIL_MATCH": "addr show 'uesimtun0'"},
            {"OMIT_EVENT": "PDU Session establishment is successful"},
        ):
            with self.subTest(env=env):
                result = self.run_verify(**env)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("FAIL:", result.stderr)
