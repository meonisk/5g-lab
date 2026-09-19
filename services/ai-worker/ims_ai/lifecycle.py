"""Serialize audio work and flush recording tails before call finalization."""

from __future__ import annotations

import json
import time

from . import runtime, settings
from .segmentation import process_event
from .utterances import process_utterance


def finalize_call(call_id):
    # SIP endpoints commonly suppress RTP during silence. Flush the last
    # transcription turn on BYE because no trailing silent frames may arrive.
    for key in [key for key in runtime.buffers if key.startswith(call_id + ":")]:
        buffered = runtime.buffers.pop(key)
        buffered_event = buffered.get("event") or {}
        if (
            buffered["in_speech"]
            and buffered["speech_bytes"] >= settings.min_utterance_bytes
            and buffered_event.get("service_mode") in {"transcribe", "bilingual_test"}
        ):
            process_utterance(
                bytes(buffered["utterance"]),
                buffered_event,
                buffered.get("received_at", time.time()),
                "call-ended",
            )
    state = runtime.recordings.pop(call_id, None)
    if state:
        completed = {
            "completed_at": time.time(),
            "turns": state["turns"],
            "audio_bytes": state["audio_bytes"],
            "transcript_chars": state["transcript_chars"],
            "retention_days": settings.recording_retention_days,
        }
        (state["path"] / "completed.json").write_text(
            json.dumps(completed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            f"AI recording_finalized session={state['session_id']} turns={state['turns']} "
            f"audio_bytes={state['audio_bytes']} transcript_chars={state['transcript_chars']}",
            flush=True,
        )
    runtime.conversations.pop(call_id, None)
    runtime.reply_counts.pop(call_id, None)
    runtime.turn_counts.pop(call_id, None)


def process_events():
    while True:
        event = runtime.work.get()
        try:
            if event.get("control") == "end_call":
                finalize_call(event["call_id"])
            else:
                process_event(event)
        except Exception as exc:
            print(
                f"AI processing_failed type={type(exc).__name__} error={exc}",
                flush=True,
            )
        finally:
            runtime.work.task_done()
