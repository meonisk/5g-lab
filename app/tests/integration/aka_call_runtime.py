"""Owned SIPp/media containers for the continuous AKA call gate."""

import json
from pathlib import Path

from aka_media_endpoint import make_marker
from baseline_audio import write_marker
from verify_plain_call import run, wait_for


def running(name):
    return run("docker", "inspect", "--format", "{{.State.Running}}", name).strip() == "true"


def trace(directory, ue):
    path = directory / f"ue{ue}-messages.log"
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def start_media(settings, directory, ue, ip, name):
    folder = directory / f"media{ue}"
    folder.mkdir()
    write_marker(folder / "source.wav", ue)
    make_marker(folder / "source.wav", folder / "marker.pcmu")
    base = f"/evidence/media{ue}"
    source = Path(__file__).parent.resolve().as_posix()
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
        "-v",
        f"{source}:/code:ro",
        settings["SIP_AKA_MEDIA_IMAGE"],
        "python",
        "/code/aka_media_endpoint.py",
        "--bind-ip",
        ip,
        "--bind-port",
        settings["SIP_AKA_MEDIA_PORT"],
        "--marker",
        f"{base}/marker.pcmu",
        "--control",
        f"{base}/control.json",
        "--ready",
        f"{base}/ready.json",
        "--stop",
        f"{base}/stop.flag",
        "--output-prefix",
        f"{base}/received",
        "--seconds",
        "110",
        "--ssrc",
        str(0x414B4100 + ue),
    )
    wait_for(lambda: (folder / "ready.json").exists(), "RTP endpoint did not bind", 20)


def start_sip(settings, directory, ue, ip, name, main_path, ooc_path=None):
    options = ["-oocsf", f"/evidence/{ooc_path.name}"] if ooc_path else []
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
        settings["SIP_AKA_IMAGE"],
        f"{settings['PCSCF_IP']}:{settings['PCSCF_SIP_PORT']}",
        "-sf",
        f"/evidence/{main_path.name}",
        *options,
        "-auth_uri",
        settings["IMS_DOMAIN"],
        "-t",
        "u1",
        "-i",
        ip,
        "-mi",
        ip,
        "-p",
        settings["SIP_AKA_PORT"],
        "-users",
        "1",
        "-m",
        "2",
        "-timeout",
        "90",
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
    return json.loads(run("docker", "inspect", name))[0]


def control_media(directory, ue, remote):
    folder = directory / f"media{ue}"
    temporary = folder / "control.tmp"
    temporary.write_text(
        json.dumps({"remote_ip": remote[0], "remote_port": remote[1], "payload_type": 0}),
        encoding="utf-8",
    )
    temporary.replace(folder / "control.json")


def stop_media(directory):
    for ue in (1, 2):
        folder = directory / f"media{ue}"
        if folder.exists():
            (folder / "stop.flag").touch()
