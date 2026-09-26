"""Reject a call to an explicitly deregistered or passively expired AKA UE."""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from aka_call_runtime import running, trace
from aka_cx_binding import assess as assess_cx
from aka_inactive_runtime import initial_trace, restore, start_client
from aka_registrar import (
    RegistrarError,
    read_registration,
    require_contact,
    require_inactive_contact,
)
from aka_rejection_trace import validate_inactive_callee, validate_rejection
from aka_socket import require_exact_bind
from aka_trace import validate_registration
from aka_unregistered_scenarios import render_callee, render_caller
from baseline_profile import baseline_ifc, wait_ims_peers
from baseline_rtp import absent, invite_id, relay
from cx_capture import capture
from verify_aka_registration import route
from verify_plain_call import logs, run, wait_for

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/research/tools"))
from ims_research.common import parse_env, sha256_file, write_json
from ims_research.execution import StandLock


def registration(cfg, directory, ue, ip):
    return validate_registration(
        initial_trace(trace(directory, ue)),
        cfg[f"UE{ue}_IMSI"],
        cfg["IMS_DOMAIN"],
        ip,
        cfg["SIP_AKA_PORT"],
    )


def execute(mode, callee):
    caller = 3 - callee
    cfg = {**parse_env(ROOT / "app/config/lab.env"), **parse_env(ROOT / "local/secrets/ims.env")}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = ROOT / "local/private" / f"aka-inactive-{mode}-{stamp}"
    directory.mkdir()
    report = {"status": "FAIL", "cleanup": "NOT_TESTED", "mode": mode, "callee_ue": callee}
    report["source_hashes"] = {
        str(p.relative_to(ROOT)): sha256_file(p)
        for p in sorted(
            set(Path(__file__).parent.glob("aka_*.py"))
            | set(Path(__file__).parent.glob("cx_*.py"))
            | {Path(__file__)}
        )
    }
    owned, names, ips = [], {}, {}
    since = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    call_id = None
    with StandLock(ROOT):
        if not re.search(r"Current sessions total:\s*0(?:\s|$)", relay(cfg, "list", "numsessions")):
            raise RuntimeError("Inactive call requires an idle relay")
        active = set(run("docker", "ps", "--format", "{{.Names}}").splitlines())
        if active & {"lab-sip-as", "lab-ai-worker", "lab-media-adapter", "lab-voice-agent"}:
            raise RuntimeError("Inactive call requires AS/AI stopped")
        try:
            run("docker", "stop", "lab-sipue1", "lab-sipue2")
            with baseline_ifc(cfg, directory):
                run("docker", "restart", "lab-scscf")
                wait_ims_peers(cfg)
                for ue in (1, 2):
                    route_text, ips[ue] = route(cfg, ue)
                    (directory / f"ue{ue}-route.txt").write_text(route_text, encoding="utf-8")
                    names[ue] = f"lab-aka-inactive-{stamp.lower()}-{ue}"
                impu = f"sip:{cfg[f'UE{callee}_IMSI']}@{cfg['IMS_DOMAIN']}"
                contact = f"sip:{cfg[f'UE{callee}_IMSI']}@{ips[callee]}:{cfg['SIP_AKA_PORT']}"
                with capture(directory / "cx.pcap", seconds=450, port=int(cfg["PYHSS_BIND_PORT"])):
                    scenario = render_callee(directory / f"ue{callee}.xml", cfg, callee, mode)
                    owned.append(names[callee])
                    report["callee_process"] = start_client(
                        cfg, directory, callee, ips[callee], names[callee], scenario
                    )
                    wait_for(
                        lambda: (
                            registration(cfg, directory, callee, ips[callee])["status"] == "PASS"
                        ),
                        "Callee registration incomplete",
                        25,
                    )
                    report["callee_registration"] = registration(
                        cfg, directory, callee, ips[callee]
                    )
                    report["initial_contact"] = require_contact(
                        read_registration(impu), contact, True
                    )
                    started_wait = time.monotonic()

                    def removed():
                        snapshot = read_registration(impu)
                        write_json(directory / "callee-registrar.json", snapshot)
                        try:
                            return require_contact(snapshot, contact, False)
                        except RegistrarError:
                            return None

                    def expired():
                        snapshot = read_registration(impu)
                        write_json(directory / "callee-expired-registrar.json", snapshot)
                        try:
                            return require_inactive_contact(snapshot, contact)
                        except RegistrarError:
                            return None

                    report["inactive_contact"] = wait_for(
                        expired if mode == "expire" else removed,
                        "Callee Contact did not become inactive",
                        report["initial_contact"]["expiry"] + 10
                        if mode == "expire"
                        else int(cfg["SIP_AKA_REGISTRAR_DELETE_TIMEOUT_SECONDS"]) + 15,
                    )
                    report["absence_wait_seconds"] = round(time.monotonic() - started_wait, 3)
                    if not running(names[callee]):
                        raise RuntimeError("Old Contact listener exited before the call")
                    report["callee_socket_before"] = require_exact_bind(
                        names[callee], ips[callee], int(cfg["SIP_AKA_PORT"])
                    )
                    scenario = render_caller(
                        directory, cfg, caller, int(cfg["SIP_AKA_INACTIVE_STATUS"])
                    )
                    owned.append(names[caller])
                    report["caller_process"] = start_client(
                        cfg, directory, caller, ips[caller], names[caller], scenario, 2
                    )
                    wait_for(
                        lambda: (
                            registration(cfg, directory, caller, ips[caller])["status"] == "PASS"
                        ),
                        "Caller registration incomplete",
                        25,
                    )
                # This capture proves authentication, not the subsequent LIR/INVITE exchange.
                report["cx_authentication"] = assess_cx(
                    directory,
                    cfg,
                    expected_challenges={caller: 1, callee: 2 if mode == "deregister" else 1},
                )
                wait_for(lambda: not running(names[caller]), "Rejection caller did not finish", 30)
                report["rejection"] = validate_rejection(
                    trace(directory, caller),
                    expected_status=int(cfg["SIP_AKA_INACTIVE_STATUS"]),
                    local_imsi=cfg[f"UE{caller}_IMSI"],
                    peer_imsi=cfg[f"UE{callee}_IMSI"],
                    domain=cfg["IMS_DOMAIN"],
                    local_ip=ips[caller],
                    local_port=cfg["SIP_AKA_PORT"],
                )
                report["callee_trace"] = validate_inactive_callee(
                    trace(directory, callee),
                    mode=mode,
                    local_imsi=cfg[f"UE{callee}_IMSI"],
                    domain=cfg["IMS_DOMAIN"],
                    local_ip=ips[callee],
                    local_port=cfg["SIP_AKA_PORT"],
                    requested_expiry=int(cfg["SIP_AKA_EXPIRY_SECONDS"])
                    if mode == "expire"
                    else 300,
                )
                report["old_contact_listener_alive"] = running(names[callee])
                report["callee_socket_after"] = require_exact_bind(
                    names[callee], ips[callee], int(cfg["SIP_AKA_PORT"])
                )
                state = json.loads(run("docker", "inspect", names[caller]))[0]
                report["caller_exit_ok"] = (
                    state["State"]["ExitCode"] == 0 and state["RestartCount"] == 0
                )
                call_id = invite_id(trace(directory, caller))
                wait_for(lambda: absent(cfg, call_id), "Rejected call retained a relay session", 20)
                report["relay_removed"] = True
                scscf = logs("lab-scscf", since)
                report["no_as"] = any(
                    call_id in line and "INVITE" in line for line in scscf.splitlines()
                ) and not any(
                    call_id in line and "fwded to AS" in line for line in scscf.splitlines()
                )
                if mode == "expire":
                    report["physical_contact_removal"] = wait_for(
                        removed,
                        "Expired Contact record did not disappear",
                        int(cfg["SIP_AKA_PASSIVE_DELETE_TIMEOUT_SECONDS"]),
                    )
                    report["physical_removal_elapsed_seconds"] = round(
                        time.monotonic() - started_wait, 3
                    )
                    require_exact_bind(names[callee], ips[callee], int(cfg["SIP_AKA_PORT"]))
                else:
                    report["physical_contact_removal"] = report["inactive_contact"]
                if all(
                    report[k]["status"] == "PASS"
                    for k in ("cx_authentication", "rejection", "callee_trace")
                ) and all(
                    report[k]
                    for k in (
                        "old_contact_listener_alive",
                        "caller_exit_ok",
                        "relay_removed",
                        "no_as",
                    )
                ):
                    report["status"] = "PASS"
        except Exception as exc:
            report["error_type"] = type(exc).__name__
            report["error"] = (
                str(exc)[:180] if isinstance(exc, RuntimeError) else "Private diagnostics retained"
            )
        finally:
            if call_id is None:
                try:
                    call_id = invite_id(trace(directory, caller))
                except RuntimeError:
                    pass
            relay_error = []
            try:
                if call_id and not absent(cfg, call_id):
                    relay(cfg, "terminate", call_id)
                    wait_for(lambda: absent(cfg, call_id), "Owned relay cleanup failed", 10)
            except Exception:
                relay_error.append("relay_cleanup")
            errors, restored = restore(cfg, directory, owned, since)
            errors += relay_error
            report["restored_clients"] = restored
            report["cleanup"] = "FAIL" if errors else "PASS"
            if errors:
                report.update(status="FAIL", cleanup_errors=errors)
            write_json(directory / "result.json", report)
    print(f"AKA inactive call: {report['status']}; evidence: {directory}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("deregister", "expire"), default="deregister")
    parser.add_argument("--callee", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    raise SystemExit(execute(args.mode, args.callee))
