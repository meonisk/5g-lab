"""Bounded UERANSIM CLI and network snapshots for real PDU recovery."""

import json
import re

from ue_pdu_state import parse_ps_list
from verify_plain_call import run


def cli(cfg, ue, command):
    seconds = int(cfg["UE_CLI_TIMEOUT_SECONDS"])
    return run(
        "docker",
        "exec",
        f"lab-ue{ue}",
        "timeout",
        "-k",
        "2",
        str(seconds),
        "nr-cli",
        f"imsi-{cfg[f'UE{ue}_IMSI']}",
        "-e",
        command,
        timeout=seconds + 5,
    )


def sessions(cfg, ue, require_active=True):
    return parse_ps_list(
        cli(cfg, ue, "ps-list"), cfg["IMS_DNN"], cfg["IMS_UE_CIDR"], require_active=require_active
    )


def snapshot(cfg, ue):
    pdu = sessions(cfg, ue)
    address = pdu["ims"]["address"]
    interfaces = json.loads(run("docker", "exec", f"lab-ue{ue}", "ip", "-j", "-4", "addr"))
    matches = [i for i in interfaces if any(a.get("local") == address for a in i["addr_info"])]
    if len(matches) != 1 or not re.fullmatch(r"uesimtun\d+", matches[0]["ifname"]):
        raise RuntimeError("Negotiated IMS address does not have one UERANSIM TUN")
    interface = {key: matches[0][key] for key in ("ifname", "ifindex")}
    routes = {}
    for key in ("PCSCF_IP", "RTPENGINE_IP"):
        output = run("docker", "exec", f"lab-ue{ue}", "ip", "route", "get", cfg[key])
        if f" dev {interface['ifname']} " not in f" {output} " or not re.search(
            rf"\bsrc {re.escape(address)}\b", output
        ):
            raise RuntimeError("IMS route does not use negotiated PDU source and TUN")
        routes[key] = output.strip()
    client = json.loads(run("docker", "inspect", f"lab-sipue{ue}"))[0]
    if not client["State"]["Running"]:
        raise RuntimeError("Normal SIP client is not running")
    return {
        "pdu": pdu,
        "interface": interface,
        "routes": routes,
        "client": {
            "id": client["Id"],
            "started_at": client["State"]["StartedAt"],
            "restart_count": client["RestartCount"],
        },
    }
