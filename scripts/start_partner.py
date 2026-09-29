"""Start the IMS + AI delivery without touching the partner's OAI core."""

import argparse
import ipaddress
import subprocess
import sys
import time

from start_lab import (
    COMPOSE,
    ROOT,
    bash_command,
    guard_mysql_storage,
    public_environment,
    restart_ims_chain,
    run,
    wait_for_pyhss,
    wait_for_pyhss_cx,
    wait_ims_peers,
)

PARTNER_COMPOSE = [*COMPOSE[:-1], str(ROOT / "compose.partner.yml")]
IMS_SERVICES = ("dns", "mysql", "pyhss", "icscf", "scscf", "rtpengine", "pcscf")


def validate(settings):
    network = ipaddress.ip_network(settings["LAB_NETWORK_CIDR"])
    pool = ipaddress.ip_network(settings["IMS_UE_CIDR"])
    gateway = ipaddress.ip_address(settings.get("IMS_ROUTE_GATEWAY", ""))
    if gateway not in network or network.overlaps(pool):
        raise ValueError("IMS next hop must be on the LAN; IMS UE pool must not overlap it")
    if not settings.get("IMS_PARENT_INTERFACE"):
        raise ValueError("Set IMS_PARENT_INTERFACE to the Linux interface facing the IMS LAN")
    keys = (
        "DNS_IP",
        "MYSQL_IP",
        "PYHSS_IP",
        "ICSCF_IP",
        "SCSCF_IP",
        "PCSCF_IP",
        "RTPENGINE_IP",
        "SIP_AS_IP",
        "AI_WORKER_IP",
        "VOICE_AGENT_IP",
    )
    addresses = [ipaddress.ip_address(settings[key]) for key in keys]
    if len(set(addresses)) != len(addresses) or gateway in addresses:
        raise ValueError("IMS service addresses must be unique and differ from the LAN gateway")
    if any(address not in network for address in addresses):
        raise ValueError("All IMS service addresses must belong to LAB_NETWORK_CIDR")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ims-only", action="store_true", help="Start IMS before loading AI models"
    )
    parser.add_argument("--check", action="store_true", help="Validate without starting containers")
    args = parser.parse_args()
    settings = public_environment()
    validate(settings)
    run(
        [sys.executable, "scripts/initialize_local.py", "--ims-only"],
        "IMS credentials initialization failed",
    )
    run(PARTNER_COMPOSE + ["config", "--quiet"], "Partner Compose validation failed")
    if args.check:
        print("PARTNER CONFIG: VALID (network reachability and calls are unverified)")
        return
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Partner macvlan deployment requires a Linux VM/host")
    guard_mysql_storage()
    services = list(IMS_SERVICES) if args.ims_only else []
    run(PARTNER_COMPOSE + ["up", "-d", "--build", *services], "IMS + AI startup failed")
    wait_for_pyhss(settings)
    run(
        [bash_command(), "scripts/provision-ims-subscribers.sh", "--apply"],
        "IMS provisioning failed",
    )
    wait_for_pyhss_cx(settings)
    restart_ims_chain()
    wait_ims_peers(settings)
    if not args.ims_only:
        deadline = time.monotonic() + float(settings["LLM_WARMUP_TIMEOUT_SECONDS"]) + 60
        while time.monotonic() < deadline:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", "lab-ai-worker"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip() == "healthy":
                break
            time.sleep(2)
        else:
            raise RuntimeError("AI models did not become ready")
    print(
        "PARTNER SERVICES: STARTED; external UE registration, SIP/RTP and AI call remain UNVERIFIED"
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
