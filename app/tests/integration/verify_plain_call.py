"""Plain Digest IMS call with opposite-source receiver PCM, AS/AI stopped."""

import argparse
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from baseline_audio import verify_receiver, verify_silence, write_marker
from baseline_profile import baseline_ifc, wait_ims_peers
from baseline_rtp import absent, invite_id, relay

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/research/tools"))
from ims_research.common import parse_env, sha256_file, write_json
from ims_research.execution import StandLock


def run(*args, timeout=60):
    result = subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=True,
    )
    return result.stdout + result.stderr


def control(client, text):
    run(
        "docker",
        "exec",
        client,
        "sh",
        "-c",
        'printf "%s" "$1" > /tmp/pjsua-control',
        "control",
        text,
    )


def wait_for(check, message, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(1)
    raise RuntimeError(message)


def logs(client, since):
    return run("docker", "logs", "--since", since, client)


def attach_player(client, since):
    control(client, "cl\n")

    def ports():
        rows = re.findall(
            r"Port #(\d+)\[[^\r\n]*\]\s+(.+?)\s+transmitting to:", logs(client, since)
        )
        players = [number for number, label in rows if "send" in label and ".wav" in label]
        calls = [number for number, label in rows if label.startswith("sip:")]
        return (players[-1], calls[-1]) if players and calls else None

    player, call = wait_for(ports, "missing player or call conference port", 10)
    control(client, f"cc\n{player}\n{call}\n")


def execute(root=ROOT, caller_number=1, mute_ue=None):
    cfg = {**parse_env(root / "app/config/lab.env"), **parse_env(root / "local/secrets/ims.env")}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = root / "local/private" / f"plain-call-{stamp}"
    directory.mkdir(parents=True)
    report = {
        "scenario": "plain-digest-two-way-pcm"
        if mute_ue is None
        else "plain-muted-source-negative",
        "caller_ue": caller_number,
        "muted_ue": mute_ue,
        "status": "FAIL",
        "cleanup": "NOT_TESTED",
    }
    report["source_hashes"] = {
        str(path.relative_to(root)): sha256_file(path)
        for path in [
            Path(__file__),
            root / "app/tests/integration/baseline_audio.py",
            root / "app/tests/integration/baseline_profile.py",
            root / "app/tests/integration/baseline_rtp.py",
            root / "scripts/sip-ue-run.sh",
            root / "app/infrastructure/configs/pyhss/baseline_ifc.xml",
        ]
    }
    compose = [
        "docker",
        "compose",
        "--env-file",
        str(root / "app/config/lab.env"),
        "--env-file",
        str(root / "local/secrets/ims.env"),
        "-f",
        str(root / "docker-compose.yml"),
    ]
    clients = [f"lab-sipue{caller_number}", f"lab-sipue{3 - caller_number}"]
    override = directory / "compose.json"
    services = {}
    for i in (1, 2):
        write_marker(directory / f"send{i}.wav", i)
        services[f"sipue{i}"] = {
            "restart": "no",
            "environment": {
                "SIP_UE_PLAYBACK_FILE": f"/baseline/send{i}.wav",
                "SIP_UE_AUTO_CONFERENCE": "0",
                "SIP_UE_RECORD_FILE": f"/baseline/receive{i}.wav",
            },
            "volumes": [f"{directory.as_posix()}:/baseline"],
        }
    write_json(override, {"services": services})
    # Refuse a baseline that quietly leaves AS or its services involved.
    running = set(run("docker", "ps", "--format", "{{.Names}}").splitlines())
    if running & {"lab-sip-as", "lab-ai-worker", "lab-media-adapter", "lab-voice-agent"}:
        raise RuntimeError("plain-call profile requires AS and AI services stopped")
    since = None
    call_id = None
    with StandLock(root):
        if not re.search(r"Current sessions total:\s*0(?:\s|$)", relay(cfg, "list", "numsessions")):
            raise RuntimeError("plain-call restart profile requires an idle relay")
        try:
            with baseline_ifc(cfg, directory):
                run("docker", "restart", "lab-scscf")
                wait_ims_peers(cfg)
                run(
                    *compose,
                    "-f",
                    str(override),
                    "up",
                    "-d",
                    "--no-deps",
                    "--force-recreate",
                    "sipue1",
                    "sipue2",
                )
                wait_for(
                    lambda: all(
                        "Response msg 200/REGISTER" in run("docker", "logs", c) for c in clients
                    ),
                    "plain clients did not register",
                )
                since = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                control(
                    clients[0], f"m\nsip:{cfg[f'UE{3 - caller_number}_IMSI']}@{cfg['IMS_DOMAIN']}\n"
                )
                wait_for(
                    lambda: "Response msg 200/INVITE" in logs(clients[0], since),
                    "plain INVITE failed",
                )
                call_id = invite_id(logs(clients[0], since))
                relay_active = relay(cfg, "call", call_id, "info")
                (directory / "relay-active.log").write_text(relay_active, encoding="utf-8")
                if (
                    f"callid: {call_id}" not in relay_active
                    or relay_active.count("using PCMU/8000") != 2
                ):
                    raise RuntimeError("missing active two-leg PCMU relay session")
                for client in clients:
                    if client != f"lab-sipue{mute_ue}":
                        attach_player(client, since)
                time.sleep(12)
                control(clients[0], "ha\n")
                wait_for(
                    lambda: (
                        "Response msg 200/BYE" in logs(clients[0], since)
                        and "Request msg BYE" in logs(clients[1], since)
                    ),
                    "BYE transaction incomplete",
                    15,
                )
                wait_for(lambda: absent(cfg, call_id), "relay session survived BYE", 40)
                report["relay_removed_after_bye"] = True
                for i, client in enumerate(clients, 1):
                    trace = logs(client, since)
                    (directory / f"sip{i}.log").write_text(trace, encoding="utf-8")
                    control(client, "q\n")
                wait_for(
                    lambda: all(
                        run("docker", "inspect", "--format", "{{.State.Running}}", c).strip()
                        == "false"
                        for c in clients
                    ),
                    "recorders did not finalize",
                    15,
                )
                report["receivers"] = [
                    verify_receiver(directory / f"receive{i}.wav", 3 - i, i) for i in (1, 2)
                ]
                caller = (directory / "sip1.log").read_text(encoding="utf-8")
                callee = (directory / "sip2.log").read_text(encoding="utf-8")
                scscf = logs("lab-scscf", since)
                (directory / "scscf.log").write_text(scscf, encoding="utf-8")
                report["no_as_forward"] = not any(
                    call_id in line and "fwded to AS" in line for line in scscf.splitlines()
                )
                report["signalling"] = {
                    "no_as_forward": report["no_as_forward"],
                    "scscf_call_seen": any(
                        call_id in line and "INVITE" in line for line in scscf.splitlines()
                    ),
                    "invite_200": "Response msg 200/INVITE" in caller,
                    "ack_received": "Request msg ACK" in callee,
                    "bye_received": "Request msg BYE" in callee,
                    "bye_200": "Response msg 200/BYE" in caller,
                    "pcmu": all("PCMU" in text for text in (caller, callee)),
                }
                expected_media = ["PASS", "PASS"]
                if mute_ue is not None:
                    expected_media[2 - mute_ue] = "FAIL"
                    report["muted_receiver"] = verify_silence(
                        directory / f"receive{3 - mute_ue}.wav"
                    )
                report["expected_media_statuses"] = expected_media
                if (
                    not all(report["signalling"].values())
                    or [r["status"] for r in report["receivers"]] != expected_media
                    or report.get("muted_receiver", {"status": "PASS"})["status"] != "PASS"
                ):
                    raise RuntimeError("plain call signalling or received waveform failed")
                report["status"] = "PASS"
        except BaseException as exc:
            report["error"] = type(exc).__name__ + ": " + str(exc)[:250]
            raise
        finally:
            try:
                cleanup_errors = []
                if since:
                    for i, client in enumerate(clients, 1):
                        try:
                            trace = logs(client, since)
                            (directory / f"sip{i}-final.log").write_text(trace, encoding="utf-8")
                            if i == 1 and call_id is None:
                                call_id = invite_id(trace)
                        except Exception as exc:
                            cleanup_errors.append(type(exc).__name__)
                    if call_id:
                        try:
                            if not absent(cfg, call_id):
                                relay(cfg, "terminate", call_id)
                                wait_for(
                                    lambda: absent(cfg, call_id), "owned relay cleanup failed", 10
                                )
                        except Exception as exc:
                            cleanup_errors.append(type(exc).__name__)
                try:
                    run("docker", "restart", "lab-scscf")
                    wait_ims_peers(cfg)
                except Exception as exc:
                    cleanup_errors.append("IMS restore: " + type(exc).__name__)
                # Still attempt to remove the temporary client profile if IMS readiness fails.
                run(*compose, "up", "-d", "--no-deps", "--force-recreate", "sipue1", "sipue2")
                wait_for(
                    lambda: all(
                        "Response msg 200/REGISTER" in run("docker", "logs", c) for c in clients
                    ),
                    "restored clients did not register",
                )
                if cleanup_errors:
                    report["cleanup_errors"] = cleanup_errors
                    raise RuntimeError("cleanup diagnostics or relay termination failed")
                report["cleanup"] = "PASS"
            except BaseException:
                report.update(status="FAIL", cleanup="FAIL")
                raise
            finally:
                write_json(directory / "result.json", report)
                print(f"Plain-call result: {report['status']}; private evidence: {directory}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caller", type=int, choices=(1, 2), default=1)
    parser.add_argument("--mute-ue", type=int, choices=(1, 2))
    args = parser.parse_args()
    execute(caller_number=args.caller, mute_ue=args.mute_ue)
