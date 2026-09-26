"""Offline SIP process lifecycle under IMS network generation changes."""

import ipaddress
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASH = Path(r"C:\Program Files\Git\bin\bash.exe")


@unittest.skipUnless(BASH.exists(), "Git Bash is unavailable")
class SipNetworkLifecycle(unittest.TestCase):
    def test_tun_recreation_stops_bound_pjsua_and_cleans_fifo(self):
        with tempfile.TemporaryDirectory() as dirname:
            config = dict(
                line.split("=", 1)
                for line in (ROOT / "app/config/lab.env").read_text(encoding="utf-8").splitlines()
                if line and not line.startswith("#") and "=" in line
            )
            ue_ip = str(ipaddress.ip_network(config["IMS_UE_CIDR"])[2])
            root = Path(dirname)
            net = root / "net/uesimtun1"
            net.mkdir(parents=True)
            (net / "ifindex").write_text("51", encoding="ascii")
            fixture = root / "fixture.wav"
            fixture.write_bytes(b"RIFFfake")
            bindir = root / "bin"
            bindir.mkdir()
            ip = bindir / "ip"
            ip.write_text(
                "#!/usr/bin/env bash\n"
                'if [[ "$*" == "-4 route get $IMS_UE_GATEWAY" ]]; then echo "$IMS_UE_GATEWAY dev eth0 src $MOCK_BRIDGE_IP"; exit 0; fi\n'
                'case "$*" in\n'
                "  '-o -4 addr show uesimtun1') echo \"1: uesimtun1 inet $MOCK_UE_IP/16\";;\n"
                "  '-4 route get '*) echo \"$5 via $IMS_UE_GATEWAY dev uesimtun1 src $MOCK_UE_IP\";;\n"
                "  'route replace '*) :;;\n"
                "  *) exit 2;;\n"
                "esac\n",
                encoding="utf-8",
            )
            ip.chmod(0o755)
            pjsua = bindir / "pjsua"
            pjsua.write_text(
                "#!/usr/bin/env bash\n"
                'printf \'%s\\n\' "$*" > "$PJSUA_ARGS"\n'
                "trap 'echo stopped > \"$PJSUA_STOPPED\"; exit 0' TERM\n"
                "while :; do sleep 0.05; done\n",
                encoding="utf-8",
            )
            pjsua.chmod(0o755)

            def shell_path(path):
                return subprocess.check_output(
                    [str(BASH), "-c", 'cygpath -u "$1"', "--", str(path)],
                    text=True,
                ).strip()

            env = {
                **os.environ,
                "IMSI": "001",
                "IMS_DIGEST_PASSWORD": "fake",
                "IMS_DOMAIN": "example.test",
                "PCSCF_IP": config["PCSCF_IP"],
                "PCSCF_SIP_PORT": "5060",
                "RTPENGINE_IP": config["RTPENGINE_IP"],
                "IMS_UE_GATEWAY": config["IMS_UE_GATEWAY"],
                "IMS_UE_CIDR": config["IMS_UE_CIDR"],
                "MOCK_UE_IP": ue_ip,
                "MOCK_BRIDGE_IP": config["PCSCF_IP"],
                "SIP_UE_AUTO_ANSWER": "200",
                "SIP_UE_AUTO_CONFERENCE": "0",
                "SIP_UE_TEST_UTTERANCE": "hello",
                "SIP_UE_PLAYBACK_FILE": shell_path(fixture),
                "SIP_UE_CODEC": "PCMU/8000",
                "TTS_VOICE": "en",
                "TTS_RATE": "150",
                "SIP_UE_NET_CLASS_DIR": shell_path(net.parent),
                "SIP_UE_WATCH_INTERVAL": "0.1",
                "SIP_UE_CONTROL_PATH": shell_path(root / "pjsua-control"),
                "PJSUA_ARGS": shell_path(root / "pjsua-args"),
                "PJSUA_STOPPED": shell_path(root / "pjsua-stopped"),
                "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
            }
            script = root / "sip-ue-run.sh"
            shutil.copyfile(ROOT / "scripts/sip-ue-run.sh", script)
            # Resolve fake commands in Git Bash even when Windows PATH conversion varies.
            command = f'PATH="{shell_path(bindir)}:$PATH"; exec bash "{shell_path(script)}"'
            process = subprocess.Popen(
                [str(BASH), "-c", command],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.monotonic() + 5
                while not (root / "pjsua-args").exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                if not (root / "pjsua-args").exists():
                    process.kill()
                    stdout, stderr = process.communicate(timeout=5)
                    self.fail(f"pjsua did not start: {stdout} {stderr}")
                (net / "ifindex").write_text("52", encoding="ascii")
                stdout, stderr = process.communicate(timeout=5)
                self.assertNotEqual(process.returncode, 0, stdout + stderr)
                self.assertIn("IMS TUN, address, or route changed", stderr)
                self.assertTrue((root / "pjsua-stopped").exists())
                self.assertFalse((root / "pjsua-control").exists())
                self.assertIn(f"--ip-addr={ue_ip}", (root / "pjsua-args").read_text())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)
