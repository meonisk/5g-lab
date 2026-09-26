"""Call-specific relay evidence; never terminate unrelated sessions."""

import re
import subprocess


def invite_id(trace):
    ids = re.findall(
        r"(?m)^INVITE [^\n]+ SIP/2\.0\r?\n(?:(?!\r?\n).+\r?\n)*?(?:Call-ID|i):\s*([^\s]+)", trace
    )
    unique = set(ids)
    if len(unique) != 1:
        raise RuntimeError("expected one unique INVITE Call-ID in private caller trace")
    return unique.pop()


def relay(settings, *command):
    result = subprocess.run(
        [
            "docker",
            "exec",
            "lab-rtpengine",
            "rtpengine-ctl",
            "-ip",
            settings["RTPENGINE_IP"],
            "-port",
            settings["RTPENGINE_CLI_PORT"],
            *command,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=True,
    )
    return result.stdout + result.stderr


def absent(settings, call_id):
    reply = relay(settings, "call", call_id, "info")
    return (
        "not found" in reply.lower()
        or "unknown call" in reply.lower()
        or "no such call" in reply.lower()
    )
