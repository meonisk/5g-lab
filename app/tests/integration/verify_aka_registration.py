"""Exclusive two-UE AKA registration probe, with private wire evidence and restoration."""

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from ipaddress import ip_address, ip_network
from pathlib import Path

from aka_cx_binding import assess as assess_cx
from aka_scenario import render
from aka_trace import validate_registration
from baseline_profile import wait_ims_peers
from baseline_rtp import relay
from cx_capture import capture
from verify_plain_call import logs, run, wait_for

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/research/tools"))
from ims_research.common import parse_env, sha256_file, write_json
from ims_research.execution import StandLock


def route(settings, ue):
    output = run("docker", "exec", f"lab-ue{ue}", "ip", "route", "get", settings["PCSCF_IP"])
    match = re.search(r"\bdev (uesimtun\d+).*\bsrc ([0-9.]+)", output)
    if not match:
        raise RuntimeError("AKA source route is not an IMS TUN")
    if ip_address(match.group(2)) not in ip_network(settings["IMS_UE_CIDR"]):
        raise RuntimeError("AKA source is outside IMS PDU address range")
    return output, match.group(2)


def probe(settings, ue, directory, stamp, rejected):
    trace_path = directory / f"ue{ue}-messages.log"
    scenario = directory / f"ue{ue}.xml"
    render(scenario, settings, ue, rejected=rejected)
    route_text, ip = route(settings, ue)
    (directory / f"ue{ue}-route.txt").write_text(route_text, encoding="utf-8")
    name = f"lab-aka-{stamp.lower()}-{ue}"
    port = int(settings["SIP_AKA_PORT"])
    command = [
        "docker",
        "run",
        "--name",
        name,
        "--network",
        f"container:lab-ue{ue}",
        "-v",
        f"{directory.as_posix()}:/evidence",
        "-w",
        "/evidence",
        settings["SIP_AKA_IMAGE"],
        f"{settings['PCSCF_IP']}:{settings['PCSCF_SIP_PORT']}",
        "-sf",
        f"/evidence/ue{ue}.xml",
        "-auth_uri",
        settings["IMS_DOMAIN"],
        "-t",
        "u1",
        "-i",
        ip,
        "-p",
        str(port),
        "-m",
        "1",
        "-l",
        "1",
        "-r",
        "1",
        "-timeout",
        settings["SIP_AKA_TIMEOUT_SECONDS"],
        "-timeout_error",
        "-nostdin",
        "-nd",
        "-trace_msg",
        "-message_file",
        f"/evidence/ue{ue}-messages.log",
        "-trace_err",
        "-error_file",
        f"/evidence/ue{ue}-errors.log",
    ]
    result = {"status": "FAIL", "ue": ue, "rejected_response": rejected}
    try:
        with (directory / f"ue{ue}-client.log").open("w", encoding="utf-8") as output:
            child = subprocess.run(
                command,
                cwd=ROOT,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=int(settings["SIP_AKA_TIMEOUT_SECONDS"]) + 20,
            )
        result["exit_code"] = child.returncode
        if trace_path.exists():
            result["trace"] = validate_registration(
                trace_path.read_text(encoding="utf-8", errors="replace"),
                settings[f"UE{ue}_IMSI"],
                settings["IMS_DOMAIN"],
                ip,
                port,
                rejected=rejected,
            )
            if child.returncode == 0 and result["trace"]["status"] == "PASS":
                result["status"] = "PASS"
    except Exception as exc:
        result["error_type"] = type(exc).__name__
    finally:
        # Explicit name owns only this temporary client, including after host timeout.
        removed = subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True,
            timeout=20,
            check=False,
        )
        result["client_cleanup"] = "PASS" if removed.returncode == 0 else "FAIL"
        if removed.returncode:
            result["status"] = "FAIL"
    return result


def execute(bad_response=False):
    cfg = {**parse_env(ROOT / "app/config/lab.env"), **parse_env(ROOT / "local/secrets/ims.env")}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = ROOT / "local/private" / f"aka-register-{stamp}"
    directory.mkdir()
    report = {
        "status": "FAIL",
        "cleanup": "NOT_TESTED",
        "scenario": "aka-invalid-response" if bad_response else "aka-registration-probe",
    }
    report["source_hashes"] = {
        str(path.relative_to(ROOT)): sha256_file(path)
        for path in (
            Path(__file__),
            Path(__file__).with_name("aka_scenario.py"),
            Path(__file__).with_name("aka_trace.py"),
            Path(__file__).with_name("cx_capture.py"),
        )
    }
    for path in sorted(Path(__file__).parent.glob("cx_*.py")) + [
        Path(__file__).with_name("aka_cx_binding.py")
    ]:
        report["source_hashes"][str(path.relative_to(ROOT))] = sha256_file(path)
    since = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    clients = ["lab-sipue1", "lab-sipue2"]
    with StandLock(ROOT):
        if not re.search(r"Current sessions total:\s*0(?:\s|$)", relay(cfg, "list", "numsessions")):
            raise RuntimeError("AKA probe requires an idle relay")
        report["image_id"] = run(
            "docker", "image", "inspect", cfg["SIP_AKA_IMAGE"], "--format", "{{.Id}}"
        ).strip()
        try:
            run("docker", "stop", *clients)
            run("docker", "restart", "lab-scscf")
            wait_ims_peers(cfg)
            with capture(directory / "cx.pcap", seconds=150, port=int(cfg["PYHSS_BIND_PORT"])):
                report["subscribers"] = [
                    probe(cfg, ue, directory, stamp, bad_response and ue == 1) for ue in (1, 2)
                ]
            report["cx"] = assess_cx(directory, cfg, bad_response)
            if report["cx"]["status"] == "PASS" and all(
                row["status"] == "PASS" for row in report["subscribers"]
            ):
                report["status"] = "PASS"
        except Exception as exc:
            report["error_type"] = type(exc).__name__
        finally:
            cleanup_errors = []
            for container in ("lab-pcscf", "lab-icscf", "lab-scscf", "lab-pyhss"):
                try:
                    (directory / f"{container}.log").write_text(
                        logs(container, since), encoding="utf-8"
                    )
                except Exception as exc:
                    cleanup_errors.append("diagnostics:" + type(exc).__name__)
            try:
                run("docker", "restart", "lab-scscf")
                wait_ims_peers(cfg)
            except Exception as exc:
                cleanup_errors.append("IMS:" + type(exc).__name__)
            try:
                run("docker", "start", *clients)
                for client in clients:
                    started = run(
                        "docker", "inspect", "--format", "{{.State.StartedAt}}", client
                    ).strip()
                    wait_for(
                        lambda: "Response msg 200/REGISTER" in logs(client, started),
                        "Digest restore failed",
                    )
            except Exception as exc:
                cleanup_errors.append("clients:" + type(exc).__name__)
            report["cleanup"] = "FAIL" if cleanup_errors else "PASS"
            if cleanup_errors:
                report.update(status="FAIL", cleanup_errors=cleanup_errors)
            write_json(directory / "result.json", report)
    print(f"AKA registration probe: {report['status']}; evidence: {directory}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bad-response", action="store_true")
    args = parser.parse_args()
    raise SystemExit(execute(args.bad_response))
