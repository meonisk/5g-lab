"""Publish bounded, identity-minimized media batches."""

import base64
import hashlib
import json
import threading
import time
import urllib.parse
import urllib.request

from . import runtime
from .api import end_worker_call


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
        for call_id in expired:
            threading.Thread(target=end_worker_call, args=(call_id,), daemon=True).start()
        active_call_ids = list(active)
        service_mode = (
            active[active_call_ids[0]]["service_mode"] if len(active_call_ids) == 1 else "observe"
        )
        for (ssrc, src, dst, payload_type, direction), value in batch.items():
            audio = bytes(value["audio"])
            event = {
                "event": "normalized_audio_activity",
                "mode": "OBSERVE",
                "call_ids": active_call_ids,
                "service_mode": service_mode,
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
                req = urllib.request.Request(
                    runtime.worker_url,
                    json.dumps(event).encode(),
                    {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {runtime.control_token}",
                    },
                )
                urllib.request.urlopen(req, timeout=1).read()
                print(
                    f"MEDIA delivered direction={direction} ssrc={ssrc} packets={value['packets']} "
                    f"audio={len(audio)} calls={len(active_call_ids)} service={service_mode}",
                    flush=True,
                )
            except Exception as exc:
                print(f"MEDIA AI unavailable (media relay unaffected): {exc}", flush=True)
