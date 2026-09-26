"""Owned SIPp processes and restoration for inactive-registration probes."""

import json
import re

from aka_dialog_trace import _direction
from baseline_profile import wait_ims_peers
from verify_plain_call import logs, run, wait_for


def initial_trace(trace):
    lines = trace.splitlines(keepends=True)
    registers = [i for i, line in enumerate(lines) if line.startswith("REGISTER ")]
    if len(registers) > 2:
        _, start = _direction([line.rstrip() for line in lines], registers[2])
        return "".join(lines[:start])
    invites = [i for i, line in enumerate(lines) if line.startswith("INVITE ")]
    if invites:
        _, start = _direction([line.rstrip() for line in lines], invites[0])
        return "".join(lines[:start])
    return trace


def start_client(cfg, directory, ue, ip, name, scenario, contexts=1):
    run(
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--network",
        f"container:lab-ue{ue}",
        "-v",
        f"{directory.as_posix()}:/evidence",
        "-w",
        "/evidence",
        cfg["SIP_AKA_IMAGE"],
        f"{cfg['PCSCF_IP']}:{cfg['PCSCF_SIP_PORT']}",
        "-sf",
        f"/evidence/{scenario.name}",
        "-auth_uri",
        cfg["IMS_DOMAIN"],
        "-i",
        ip,
        "-mi",
        ip,
        "-p",
        cfg["SIP_AKA_PORT"],
        "-t",
        "u1",
        "-users",
        "1",
        "-m",
        str(contexts),
        "-timeout",
        str(max(480, int(cfg["SIP_AKA_INACTIVE_HOLD_SECONDS"]) + 60)),
        "-timeout_error",
        "-nostdin",
        "-nd",
        "-trace_msg",
        "-message_file",
        f"/evidence/ue{ue}-messages.log",
        "-trace_err",
        "-error_file",
        f"/evidence/ue{ue}-errors.log",
    )
    info = json.loads(run("docker", "inspect", name))[0]
    return {
        "container_id": info["Id"],
        "image_id": info["Image"],
        "started_at": info["State"]["StartedAt"],
    }


def restore(cfg, directory, owned, since):
    errors = []
    for name in owned:
        try:
            (directory / f"{name}.log").write_text(run("docker", "logs", name), encoding="utf-8")
        except Exception:
            errors.append("client_diagnostics")
        try:
            run("docker", "rm", "-f", name)
        except Exception:
            errors.append("client_cleanup")
    try:
        (directory / "scscf.log").write_text(logs("lab-scscf", since), encoding="utf-8")
        run("docker", "restart", "lab-scscf")
        wait_ims_peers(cfg)
    except Exception:
        errors.append("IMS_cleanup")
    restored = []
    try:
        run("docker", "start", "lab-sipue1", "lab-sipue2")
        for ue in (1, 2):
            name = f"lab-sipue{ue}"
            started = run("docker", "inspect", "--format", "{{.State.StartedAt}}", name).strip()
            wait_for(
                lambda: "Response msg 200/REGISTER" in logs(name, started),
                "Digest restoration failed",
                int(cfg["SIP_AKA_RESTORE_TIMEOUT_SECONDS"]),
            )
            restored.append(
                {
                    "ue": ue,
                    "response_statuses": re.findall(
                        r"Response msg (\d{3})/REGISTER", logs(name, started)
                    ),
                }
            )
    except Exception:
        errors.append("Digest_cleanup")
    return errors, restored
