"""Serial two-UE AKA refresh/deregistration with authoritative contact snapshots."""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from aka_call_runtime import running, trace
from aka_cx_binding import assess as assess_cx
from aka_lifecycle_scenario import render
from aka_lifecycle_trace import checkpoint, validate_lifecycle
from aka_registrar import RegistrarError, read_registration, require_contact
from baseline_profile import wait_ims_peers
from baseline_rtp import relay
from cx_capture import capture
from verify_aka_registration import route
from verify_plain_call import logs, run, wait_for

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/research/tools"))
from ims_research.common import parse_env, sha256_file, write_json
from ims_research.execution import StandLock


def start_client(cfg, directory, ue, ip, name):
    scenario = directory / f"ue{ue}.xml"
    render(scenario, cfg, ue)
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
        "-t",
        "u1",
        "-i",
        ip,
        "-p",
        cfg["SIP_AKA_PORT"],
        "-m",
        "1",
        "-l",
        "1",
        "-r",
        "1",
        "-timeout",
        "120",
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


def trace_state(cfg, directory, ue, ip):
    return checkpoint(
        trace(directory, ue), cfg[f"UE{ue}_IMSI"], cfg["IMS_DOMAIN"], ip, cfg["SIP_AKA_PORT"]
    )


def execute():
    cfg = {**parse_env(ROOT / "app/config/lab.env"), **parse_env(ROOT / "local/secrets/ims.env")}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = ROOT / "local/private" / f"aka-lifecycle-{stamp}"
    directory.mkdir()
    report = {"status": "FAIL", "cleanup": "NOT_TESTED", "subscribers": []}
    report["source_hashes"] = {
        str(p.relative_to(ROOT)): sha256_file(p)
        for p in sorted(
            set(Path(__file__).parent.glob("aka_*.py"))
            | set(Path(__file__).parent.glob("cx_*.py"))
            | {Path(__file__)}
        )
    }
    owned = []
    since = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with StandLock(ROOT):
        if not re.search(r"Current sessions total:\s*0(?:\s|$)", relay(cfg, "list", "numsessions")):
            raise RuntimeError("AKA lifecycle requires an idle relay")
        try:
            run("docker", "stop", "lab-sipue1", "lab-sipue2")
            run("docker", "restart", "lab-scscf")
            wait_ims_peers(cfg)
            with capture(directory / "cx.pcap", seconds=600, port=int(cfg["PYHSS_BIND_PORT"])):
                for ue in (1, 2):
                    _, ip = route(cfg, ue)
                    name = f"lab-aka-lifecycle-{stamp.lower()}-{ue}"
                    owned.append(name)
                    row = {"ue": ue, "process": start_client(cfg, directory, ue, ip, name)}
                    report["subscribers"].append(row)
                    impu = f"sip:{cfg[f'UE{ue}_IMSI']}@{cfg['IMS_DOMAIN']}"
                    contact = f"sip:{cfg[f'UE{ue}_IMSI']}@{ip}:{cfg['SIP_AKA_PORT']}"
                    row["registrar"] = {}
                    for stage in ("initial", "refresh", "deregistration"):
                        wait_for(
                            lambda: (
                                trace_state(cfg, directory, ue, ip)[stage] == "PASS"
                                and trace_state(cfg, directory, ue, ip)["status"] != "FAIL"
                            ),
                            f"AKA {stage} incomplete",
                            45,
                        )

                        def read_contact():
                            snapshot = read_registration(impu)
                            write_json(directory / f"ue{ue}-{stage}-registrar.json", snapshot)
                            try:
                                return require_contact(snapshot, contact, stage != "deregistration")
                            except RegistrarError:
                                return None

                        row["registrar"][stage] = wait_for(
                            read_contact,
                            "Registrar lifecycle mismatch",
                            int(cfg["SIP_AKA_REGISTRAR_DELETE_TIMEOUT_SECONDS"])
                            if stage == "deregistration"
                            else 10,
                        )
                        row[stage] = trace_state(cfg, directory, ue, ip)
                        if stage == "initial":
                            # An aged sample proves refresh renews the lifetime, rather
                            # than merely accepting the still-positive original binding.
                            time.sleep(5)
                            row["registrar"]["aged"] = require_contact(
                                read_registration(impu), contact, True
                            )
                        if stage == "refresh":
                            row["renewed"] = (
                                row["registrar"][stage]["expiry"]
                                > row["registrar"]["aged"]["expiry"]
                            )
                    wait_for(lambda: not running(name), "Lifecycle client did not exit", 15)
                    state = json.loads(run("docker", "inspect", name))[0]
                    row["process_ok"] = (
                        state["State"]["ExitCode"] == 0 and state["RestartCount"] == 0
                    )
                    row["trace"] = validate_lifecycle(
                        trace(directory, ue),
                        cfg[f"UE{ue}_IMSI"],
                        cfg["IMS_DOMAIN"],
                        ip,
                        cfg["SIP_AKA_PORT"],
                    )
            report["cx"] = assess_cx(directory, cfg, expected_challenges=3)
            if (
                report["cx"]["status"] == "PASS"
                and all(
                    row["process_ok"] and row["renewed"] and row["trace"]["status"] == "PASS"
                    for row in report["subscribers"]
                )
                and len(report["subscribers"]) == 2
            ):
                report["status"] = "PASS"
        except Exception as exc:
            report["error_type"] = type(exc).__name__
            report["error"] = (
                str(exc)[:160] if isinstance(exc, RuntimeError) else "Private diagnostics retained"
            )
        finally:
            errors = []
            for name in owned:
                try:
                    (directory / f"{name}.log").write_text(
                        run("docker", "logs", name), encoding="utf-8"
                    )
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
            try:
                run("docker", "start", "lab-sipue1", "lab-sipue2")
                report["restored_clients"] = []
                for ue in (1, 2):
                    name = f"lab-sipue{ue}"
                    started = run(
                        "docker", "inspect", "--format", "{{.State.StartedAt}}", name
                    ).strip()
                    wait_for(
                        lambda: "Response msg 200/REGISTER" in logs(name, started),
                        "Digest restoration failed",
                        int(cfg["SIP_AKA_RESTORE_TIMEOUT_SECONDS"]),
                    )
                    report["restored_clients"].append(
                        {
                            "ue": ue,
                            "response_statuses": re.findall(
                                r"Response msg (\d{3})/REGISTER", logs(name, started)
                            ),
                        }
                    )
            except Exception:
                errors.append("Digest_cleanup")
            report["cleanup"] = "FAIL" if errors else "PASS"
            if errors:
                report.update(status="FAIL", cleanup_errors=errors)
            write_json(directory / "result.json", report)
    print(f"AKA lifecycle: {report['status']}; evidence: {directory}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(execute())
