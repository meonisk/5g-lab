"""Publish bounded, identity-minimized media batches."""

import base64
import hashlib
import threading
import time

from lab_common.http import request_json

from . import runtime
from .api import end_worker_call
from .rtpengine import resolve_subscriber_port


def match_session(src_port, dst_port, direction, active):
    """Return one call for a stream, or None when attribution is ambiguous."""
    if direction == "caller_to_agent":
        matches = [
            (call_id, session)
            for call_id, session in active.items()
            if session.get("rtpengine_port") == src_port
        ]
        return matches[0] if len(matches) == 1 else None
    if direction == "caller_to_core":
        matches = [
            (call_id, session)
            for call_id, session in active.items()
            if session.get("subscriber_port") == dst_port
        ]
        if len(matches) == 1:
            return matches[0]
        if len(active) == 1:
            call_id, session = next(iter(active.items()))
            # Subscriber-to-subscriber sessions do not terminate at the agent.
            if session.get("rtpengine_port") is None:
                return call_id, session
    return None


def refresh_subscriber_ports(active):
    """Resolve the subscriber-facing relay port once per terminated call."""
    for call_id, current in list(active.items()):
        if current.get("rtpengine_port") is None or current.get("subscriber_port") is not None:
            continue
        port = resolve_subscriber_port(call_id)
        if port is None:
            continue
        session = dict(current)
        session["subscriber_port"] = port
        active[call_id] = session
        with runtime.lock:
            if call_id in runtime.sessions:
                runtime.sessions[call_id]["subscriber_port"] = port
        print(f"MEDIA mapped call_id={call_id} subscriber_port={port}", flush=True)


def publish():
    while True:
        time.sleep(runtime.interval)
        with runtime.lock:
            batch = dict(runtime.counters)
            runtime.counters.clear()
            cutoff = time.time() - runtime.session_ttl
            expired = [
                call_id
                for call_id, value in runtime.sessions.items()
                if value.get("observed_at", 0) < cutoff
            ]
            for call_id in expired:
                runtime.sessions.pop(call_id, None)
            active = dict(runtime.sessions)
        refresh_subscriber_ports(active)
        for call_id in expired:
            threading.Thread(target=end_worker_call, args=(call_id,), daemon=True).start()
        for (ssrc, src, dst, payload_type, direction), value in batch.items():
            audio = bytes(value["audio"])
            matched = match_session(src, dst, direction, active)
            if not matched:
                continue
            call_id, session = matched
            event = {
                "event": "normalized_audio_activity",
                "mode": "OBSERVE",
                "call_ids": [call_id],
                "service_mode": session["service_mode"],
                "ssrc": ssrc,
                "payload_type": payload_type,
                "packets": value["packets"],
                "source_stream_id": hashlib.sha256(f"{src}:{ssrc}".encode()).hexdigest()[:16],
                "direction": direction,
                "payload_bytes": value["payload_bytes"],
                "window_seconds": runtime.interval,
                "observed_at": time.time(),
            }
            if audio:
                event.update(
                    {
                        "codec": "PCMU",
                        "sample_rate_hz": 8000,
                        "audio_bytes": len(audio),
                        "audio_sha256": hashlib.sha256(audio).hexdigest(),
                        "audio_ulaw_b64": base64.b64encode(audio).decode("ascii"),
                    }
                )
            try:
                request_json(
                    "POST",
                    runtime.worker_url,
                    payload=event,
                    token=runtime.control_token,
                    timeout=1,
                )
                print(
                    f"MEDIA delivered direction={direction} ssrc={ssrc} packets={value['packets']} "
                    f"audio={len(audio)} calls=1 service={session['service_mode']}",
                    flush=True,
                )
            except Exception as exc:
                print(
                    f"MEDIA AI unavailable (media relay unaffected) type={type(exc).__name__}",
                    flush=True,
                )
