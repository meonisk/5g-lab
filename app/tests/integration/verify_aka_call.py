"""Same-process AKA registration and plain two-way PCMU call through IMS."""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from aka_call_runtime import control_media, running, start_media, start_sip, stop_media, trace
from aka_call_scenarios import render_pair
from aka_cx_binding import assess as assess_cx
from aka_dialog_trace import extract_remote_media, split_registration, validate_dialog
from aka_trace import validate_registration
from baseline_audio import verify_receiver
from baseline_profile import baseline_ifc, wait_ims_peers
from baseline_rtp import absent, invite_id, relay
from cx_capture import capture
from verify_aka_registration import route
from verify_plain_call import logs, run, wait_for

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/research/tools"))
from ims_research.common import parse_env, sha256_file, write_json
from ims_research.execution import StandLock


def registration(directory, cfg, ue, ip):
    captured = trace(directory, ue)
    try:
        prefix, _ = split_registration(captured)
    except ValueError:
        prefix = captured  # Before INVITE the complete trace is the registration prefix.
    return validate_registration(
        prefix, cfg[f"UE{ue}_IMSI"], cfg["IMS_DOMAIN"], ip, cfg["SIP_AKA_PORT"]
    )


def execute(caller=1):
    cfg = {**parse_env(ROOT / "app/config/lab.env"), **parse_env(ROOT / "local/secrets/ims.env")}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = ROOT / "local/private" / f"aka-call-{stamp}"
    directory.mkdir()
    report = {
        "status": "FAIL",
        "cleanup": "NOT_TESTED",
        "caller_ue": caller,
        "scenario": "continuous-aka-pcmu",
    }
    report["source_hashes"] = {
        str(path.relative_to(ROOT)): sha256_file(path)
        for path in sorted(
            set(Path(__file__).parent.glob("aka_*.py"))
            | set(Path(__file__).parent.glob("cx_*.py"))
            | {Path(__file__)}
        )
    }
    paths = render_pair(directory, cfg, caller)
    owned, sip_names, media_names, ips = [], {}, {}, {}
    call_id = None
    since = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with StandLock(ROOT):
        active = set(run("docker", "ps", "--format", "{{.Names}}").splitlines())
        if active & {"lab-sip-as", "lab-ai-worker", "lab-media-adapter", "lab-voice-agent"}:
            raise RuntimeError("AKA baseline requires AS/AI stopped")
        if not re.search(r"Current sessions total:\s*0(?:\s|$)", relay(cfg, "list", "numsessions")):
            raise RuntimeError("AKA baseline requires idle relay")
        try:
            run("docker", "stop", "lab-sipue1", "lab-sipue2")
            with baseline_ifc(cfg, directory):
                run("docker", "restart", "lab-scscf")
                wait_ims_peers(cfg)
                for ue in (1, 2):
                    route_text, ips[ue] = route(cfg, ue)
                    (directory / f"ue{ue}-route.txt").write_text(route_text, encoding="utf-8")
                    name = f"lab-aka-media-{stamp.lower()}-{ue}"
                    owned.append(name)
                    media_names[ue] = name
                    start_media(cfg, directory, ue, ips[ue], name)
                with capture(directory / "cx.pcap", seconds=150, port=int(cfg["PYHSS_BIND_PORT"])):
                    report["clients"] = []
                    for ue in (3 - caller, caller):
                        role = "caller" if ue == caller else "callee"
                        name = f"lab-aka-call-{stamp.lower()}-{ue}"
                        owned.append(name)
                        sip_names[ue] = name
                        info = start_sip(
                            cfg,
                            directory,
                            ue,
                            ips[ue],
                            name,
                            paths[role],
                            paths.get("callee_ooc") if role == "callee" else None,
                        )
                        report["clients"].append(
                            {
                                "ue": ue,
                                "container_id": info["Id"],
                                "image_id": info["Image"],
                                "started_at": info["State"]["StartedAt"],
                            }
                        )
                        wait_for(
                            lambda: registration(directory, cfg, ue, ips[ue])["status"] == "PASS",
                            "AKA registration incomplete",
                            25,
                        )
                    for ue in (1, 2):
                        role = "caller" if ue == caller else "callee"

                        def remote():
                            try:
                                return extract_remote_media(trace(directory, ue), role)
                            except ValueError:
                                return None

                        peer = wait_for(remote, "INVITE SDP negotiation incomplete", 20)
                        media_route = run(
                            "docker", "exec", f"lab-ue{ue}", "ip", "route", "get", peer[0]
                        )
                        if (
                            not re.search(r"\bdev uesimtun\d+\b", media_route)
                            or f"src {ips[ue]}" not in media_route
                        ):
                            raise RuntimeError("RTP route bypasses IMS PDU")
                        control_media(directory, ue, peer)
                    call_id = invite_id(trace(directory, caller))
                    active_relay = relay(cfg, "call", call_id, "info")
                    (directory / "relay-active.log").write_text(active_relay, encoding="utf-8")
                    if (
                        f"callid: {call_id}" not in active_relay
                        or active_relay.count("using PCMU/8000") != 2
                    ):
                        raise RuntimeError("Missing active two-leg relay")
                    wait_for(
                        lambda: not running(sip_names[caller]), "Caller did not finish BYE", 45
                    )
                    stop_media(directory)
                    wait_for(
                        lambda: all(not running(name) for name in media_names.values()),
                        "Media capture did not stop",
                        10,
                    )
                    wait_for(lambda: absent(cfg, call_id), "Relay survived BYE", 40)
                    wait_for(
                        lambda: not running(sip_names[3 - caller]),
                        "Callee process did not finish",
                        45,
                    )
                report["cx"] = assess_cx(directory, cfg)
                report["endpoints"] = []
                for ue in (1, 2):
                    reg = registration(directory, cfg, ue, ips[ue])
                    dialog = validate_dialog(
                        trace(directory, ue),
                        role="caller" if ue == caller else "callee",
                        local_imsi=cfg[f"UE{ue}_IMSI"],
                        peer_imsi=cfg[f"UE{3 - ue}_IMSI"],
                        domain=cfg["IMS_DOMAIN"],
                        local_ip=ips[ue],
                        local_port=int(cfg["SIP_AKA_PORT"]),
                        registration_ok=reg["status"] == "PASS",
                        media_port=int(cfg["SIP_AKA_MEDIA_PORT"]),
                    )
                    pcm = verify_receiver(directory / f"media{ue}/received.wav", 3 - ue, ue)
                    pcm["boundary"] = (
                        "receiver UDP RTP decoded to WAV; eight-second marker, not speaker playback"
                    )
                    packets = json.loads((directory / f"media{ue}/received.json").read_text())
                    info = json.loads(run("docker", "inspect", sip_names[ue]))[0]
                    process_ok = info["State"]["ExitCode"] == 0 and info["RestartCount"] == 0
                    report["endpoints"].append(
                        {
                            "ue": ue,
                            "registration": reg,
                            "dialog": dialog,
                            "audio": pcm,
                            "rtp": packets,
                            "process_ok": process_ok,
                        }
                    )
                scscf = logs("lab-scscf", since)
                report["no_as"] = any(
                    call_id in line and "INVITE" in line for line in scscf.splitlines()
                ) and not any(
                    call_id in line and "fwded to AS" in line for line in scscf.splitlines()
                )
                report["relay_removed"] = True
                if (
                    report["cx"]["status"] == "PASS"
                    and report["no_as"]
                    and all(
                        row["process_ok"]
                        and row["registration"]["status"]
                        == row["dialog"]["status"]
                        == row["audio"]["status"]
                        == "PASS"
                        and row["rtp"]["status"] == "CAPTURED"
                        for row in report["endpoints"]
                    )
                ):
                    report["status"] = "PASS"
        except Exception as exc:
            report["error_type"] = type(exc).__name__
            report["error"] = (
                str(exc)[:180] if isinstance(exc, RuntimeError) else "Private diagnostics retained"
            )
        finally:
            errors = []
            stop_media(directory)
            if call_id is None:
                try:
                    call_id = invite_id(trace(directory, caller))
                except RuntimeError:
                    pass
            for name in owned:
                try:
                    (directory / f"{name}.log").write_text(
                        run("docker", "logs", name), encoding="utf-8"
                    )
                except Exception:
                    errors.append("owned_container_diagnostics")
                try:
                    run("docker", "rm", "-f", name)
                except Exception:
                    errors.append("owned_container_cleanup")
            try:
                if call_id and not absent(cfg, call_id):
                    relay(cfg, "terminate", call_id)
                    wait_for(lambda: absent(cfg, call_id), "Owned relay cleanup failed", 10)
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
    print(f"Continuous AKA call: {report['status']}; evidence: {directory}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caller", type=int, choices=(1, 2), default=1)
    raise SystemExit(execute(parser.parse_args().caller))
