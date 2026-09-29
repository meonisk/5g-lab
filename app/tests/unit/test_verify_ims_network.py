"""Offline live-network contract for the IMS Phase 4A gate."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "app/tests/integration/verify-ims.sh"
BASH = (
    str(Path(r"C:\Program Files\Git\bin\bash.exe"))
    if Path(r"C:\Program Files\Git\bin\bash.exe").exists()
    else shutil.which("bash")
)


@unittest.skipUnless(BASH, "Bash is unavailable")
class VerifyImsNetwork(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        script = root / "app/tests/integration/verify-ims.sh"
        script.parent.mkdir(parents=True)
        shutil.copyfile(SOURCE, script)
        loader = root / "scripts/load-lab-env.sh"
        loader.parent.mkdir()
        loader.write_text(
            "IMS_DOMAIN=example.test\nIMS_UE_GATEWAY=198.51.100.1\nIMS_UE_GATEWAY_CIDR=198.51.100.1/24\n"
            "IMS_UE_CIDR=198.51.100.0/24\nINTERNET_UE_CIDR=192.0.2.0/24\n"
            "PYHSS_API_BIND=127.0.0.1\nPYHSS_API_PORT=80\nPYHSS_IP=10.0.0.4\nPYHSS_BIND_PORT=3868\n"
            "PCSCF_IP=10.0.0.1\nICSCF_IP=10.0.0.2\nSCSCF_IP=10.0.0.3\n"
            "RTPENGINE_IP=10.0.0.5\nLOOPBACK_IP=127.0.0.1\nICSCF_SIP_PORT=5060\n"
            "UE1_IMSI=111\nUE2_IMSI=222\nUPF_IMS_TUN=tun0\n"
            'sh() { if [[ $* == *curl* ]]; then return 0; fi; command sh "$@"; }\n'
            'ipv4_in_cidr() { case "$2:$1" in 198.51.100.0/24:198.51.100.*|192.0.2.0/24:192.0.2.*) return 0;; esac; return 1; }\n',
            encoding="utf-8",
        )
        bin_dir = root / "bin"
        bin_dir.mkdir()
        docker = bin_dir / "docker"
        docker.write_text(
            "#!/usr/bin/env bash\n"
            'case "$*" in\n'
            "  *'ip -o -4 addr show'*) [[ ${MISSING_TUN:-} ]] || printf '1: uesimtun7 inet 192.0.2.2/24\\n2: uesimtun9 inet 198.51.100.2/24\\n';;\n"
            "  *'ip -4 route get'*) if [[ ${BRIDGE_ROUTE:-} ]]; then echo '10.0.0.1 dev eth0 src 172.1.1.2'; else echo '10.0.0.1 dev uesimtun9 src 198.51.100.2'; fi;;\n"
            "  *'iptables -t nat -S'*) [[ ! ${NAT_FAIL:-} ]] || exit 1; echo '-A POSTROUTING -s 192.0.2.0/24 -j MASQUERADE';;\n"
            "  *'addr show tun0'*) echo 'inet 198.51.100.1/24';;\n"
            "  *'ip route show'*) echo '198.51.100.0/24 dev tun0';;\n"
            "  *'ping -I'*) :;;\n"
            "  logs*) echo 'PDU Session establishment is successful';;\n"
            "  *) echo '10.0.0.1 10.0.0.2 10.0.0.3 10.0.0.4 5060';;\n"
            "esac\n",
            encoding="utf-8",
        )
        docker.chmod(0o755)
        curl = bin_dir / "curl"
        curl.write_text("#!/usr/bin/env bash\necho '111 222'\n")
        curl.chmod(0o755)
        self.script = script
        self.env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]}

    def run_gate(self, **extra):
        return subprocess.run(
            [BASH, str(self.script)],
            env={**self.env, **extra},
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_live_tuns_and_routes_pass(self):
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_stale_log_does_not_replace_missing_tun(self):
        result = self.run_gate(MISSING_TUN="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("live internet/ims TUN pair missing", result.stdout)

    def test_bridge_route_fails(self):
        result = self.run_gate(BRIDGE_ROUTE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bypasses ims TUN/source", result.stdout)

    def test_nat_read_failure_fails(self):
        result = self.run_gate(NAT_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot read UPF NAT rules", result.stdout)


if __name__ == "__main__":
    unittest.main()
