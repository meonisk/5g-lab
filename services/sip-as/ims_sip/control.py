"""Notify media and voice services through authenticated HTTP."""

import json
import re
import time
import urllib.parse
import urllib.request

from . import runtime
from .messages import header


def notify_adapter(message, service_mode="observe", rtpengine_port=None):
    if rtpengine_port is None:
        media = re.search(r"(?im)^m=audio (\d+)\s+RTP/AVP", message)
        rtpengine_port = int(media.group(1)) if media else None
    payload = json.dumps(
        {
            "call_id": header(message, "Call-ID") or header(message, "i"),
            "observed_at": time.time(),
            "service_mode": service_mode,
            "rtpengine_port": rtpengine_port,
        }
    ).encode()
    try:
        req = urllib.request.Request(
            runtime.adapter_url,
            payload,
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {runtime.control_token}",
            },
        )
        urllib.request.urlopen(req, timeout=1).read()
    except Exception as exc:
        print(f"AS adapter unavailable (call continues): {exc}", flush=True)


def stop_adapter(call_id):
    try:
        safe_call_id = urllib.parse.quote(call_id, safe="")
        request = urllib.request.Request(
            f"{runtime.adapter_url}/{safe_call_id}",
            method="DELETE",
            headers={"Authorization": f"Bearer {runtime.control_token}"},
        )
        urllib.request.urlopen(request, timeout=1).read()
    except Exception as exc:
        print(f"AS adapter cleanup failed call_id={call_id}: {exc}", flush=True)


def notify_voice(call_id, remote_ip, remote_port, service_mode):
    payload = json.dumps(
        {
            "call_id": call_id,
            "remote_ip": remote_ip,
            "remote_port": remote_port,
            "service_mode": service_mode,
        }
    ).encode()
    req = urllib.request.Request(
        runtime.voice_url,
        payload,
        {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {runtime.control_token}",
        },
    )
    urllib.request.urlopen(req, timeout=2).read()


def stop_voice(call_id):
    try:
        safe_call_id = urllib.parse.quote(call_id, safe="")
        request = urllib.request.Request(
            f"{runtime.voice_url}/{safe_call_id}",
            method="DELETE",
            headers={"Authorization": f"Bearer {runtime.control_token}"},
        )
        urllib.request.urlopen(request, timeout=1).read()
    except Exception as exc:
        print(f"AS voice cleanup failed call_id={call_id}: {exc}", flush=True)
