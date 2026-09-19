"""Group subscriber audio into phrases using VAD and suppressed-RTP gaps."""

from __future__ import annotations

import base64
import hashlib
import time

from . import runtime, settings
from .audio import frame_rms
from .maintenance import expire_transient
from .utterances import process_utterance


def process_event(event):
    service_mode = event.get("service_mode", "observe")
    current_silence_bytes_required = (
        settings.dialogue_silence_bytes_required
        if service_mode == "bilingual_test"
        else settings.silence_bytes_required
    )
    current_max_utterance_bytes = (
        settings.dialogue_max_utterance_bytes
        if service_mode == "bilingual_test"
        else settings.max_utterance_bytes
    )
    subscriber_directions = {"caller_to_core", "caller_to_agent"}
    if event.get("direction") not in subscriber_directions and service_mode != "bilingual_test":
        return
    received_at = event.get("received_at", time.time())
    encoded = event.get("audio_ulaw_b64", "")
    try:
        chunk = base64.b64decode(encoded, validate=True)
    except ValueError:
        return
    if event.get("codec") != "PCMU" or event.get("sample_rate_hz") != 8000 or not chunk:
        return
    if hashlib.sha256(chunk).hexdigest() != event.get("audio_sha256"):
        print("AI rejected audio hash mismatch", flush=True)
        return
    event_call_ids = event.get("call_ids") or []
    event_call_id = event_call_ids[0] if len(event_call_ids) == 1 else "unbound"
    # SSRC values may be reused by a UE across calls. Call-ID is therefore
    # part of the transient buffer key to prevent cross-dialog audio mixing.
    stream_key = f"{event_call_id}:{event.get('ssrc', 'unknown')}"
    now = time.time()
    expire_transient(now)
    if stream_key not in runtime.buffers and len(runtime.buffers) >= settings.buffer_max:
        oldest = min(runtime.buffers, key=lambda key: runtime.buffers[key]["last_seen"])
        runtime.buffers.pop(oldest, None)
    state = runtime.buffers.setdefault(
        stream_key,
        {
            "utterance": bytearray(),
            "preroll": bytearray(),
            "speech_bytes": 0,
            "silence_bytes": 0,
            "in_speech": False,
            "last_seen": now,
        },
    )
    observed_at = event.get("observed_at")
    previous_observed_at = state.get("observed_at")
    if (
        service_mode == "bilingual_test"
        and state["in_speech"]
        and state["speech_bytes"] >= settings.min_utterance_bytes
        and isinstance(observed_at, (int, float))
        and isinstance(previous_observed_at, (int, float))
        and observed_at - previous_observed_at >= settings.dialogue_event_gap_seconds
    ):
        # Silence-suppressing SIP clients send no RTP frames from which the VAD
        # could count silence. A gap between two batches is the media-level
        # equivalent and must close the previous phrase before the new one.
        process_utterance(
            bytes(state["utterance"]),
            state.get("event", event),
            state.get("received_at", received_at),
            "stream-gap",
        )
        state.update(
            {
                "utterance": bytearray(),
                "preroll": bytearray(),
                "speech_bytes": 0,
                "silence_bytes": 0,
                "in_speech": False,
            }
        )
    state["last_seen"] = now
    state["observed_at"] = observed_at
    state["received_at"] = received_at
    state["event"] = {key: value for key, value in event.items() if key != "audio_ulaw_b64"}
    for offset in range(0, len(chunk), 160):
        frame = chunk[offset : offset + 160]
        if len(frame) < 160:
            continue
        voiced = frame_rms(frame) >= settings.vad_rms
        if voiced:
            if not state["in_speech"]:
                state["utterance"].extend(state["preroll"])
                state["preroll"].clear()
                state["in_speech"] = True
            state["utterance"].extend(frame)
            state["speech_bytes"] += len(frame)
            state["silence_bytes"] = 0
        elif state["in_speech"]:
            state["utterance"].extend(frame)
            state["silence_bytes"] += len(frame)
        else:
            state["preroll"].extend(frame)
            del state["preroll"][: -settings.preroll_bytes]

        end_reason = None
        if (
            state["in_speech"]
            and state["speech_bytes"] >= settings.min_utterance_bytes
            and state["silence_bytes"] >= current_silence_bytes_required
        ):
            end_reason = "silence"
        elif state["in_speech"] and len(state["utterance"]) >= current_max_utterance_bytes:
            end_reason = "maximum-duration"
        if end_reason:
            ulaw = bytes(state["utterance"])
            state.update(
                {
                    "utterance": bytearray(),
                    "preroll": bytearray(),
                    "speech_bytes": 0,
                    "silence_bytes": 0,
                    "in_speech": False,
                }
            )
            process_utterance(ulaw, event, received_at, end_reason)
