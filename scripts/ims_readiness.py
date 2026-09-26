"""Read-only readiness probe for Kamailio's established HSS Cx peers."""

import re
import subprocess
import time

CX_APP = "16777216:10415"


def connected_hss_peer(output, domain):
    """Read the HSS peer's negotiated Cx state from cdp.list_peers."""
    hss = f"hss.{domain}"
    match = re.search(
        rf"(?m)^\s*FQDN:\s*{re.escape(hss)}\s*\n"
        r"\s*Details:\s*\{\s*\n\s*State:\s*(I_Open|R_Open)\b",
        output,
    )
    if not match:
        return False
    next_peer = output.find("\n\t\tFQDN:", match.end())
    peer_block = output[match.start() : next_peer if next_peer >= 0 else None]
    return CX_APP in peer_block and "Disabled: False" in peer_block


def wait_ims_peers(settings, timeout_seconds=60, interval_seconds=2):
    """Block registrations until I/S-CSCF have usable HSS Cx peers."""
    domain = settings["IMS_DOMAIN"]
    deadline = time.monotonic() + timeout_seconds
    while True:
        ready = []
        for container in ("lab-icscf", "lab-scscf"):
            try:
                result = subprocess.run(
                    ["docker", "exec", container, "kamcmd", "cdp.list_peers"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                ready.append(result.returncode == 0 and connected_hss_peer(result.stdout, domain))
            except (OSError, subprocess.TimeoutExpired):
                ready.append(False)
        if all(ready):
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("I/S-CSCF HSS Cx peers did not reach I_Open/R_Open")
        time.sleep(interval_seconds)
