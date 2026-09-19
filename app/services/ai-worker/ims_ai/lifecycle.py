"""Serialize audio work and flush recording tails before call finalization."""

from __future__ import annotations

import json
import queue
import time

from . import runtime, settings
from .queueing import enqueue_utterance, wait_for_call
from .segmentation import flush_idle_streams, process_event

FINALIZED_RECORDING_MODES = {
    "transcribe",
    "bilingual_test",
    "interpret_ru",
    "interpret_en",
}


def flush_buffered_speech(call_id: str) -> None:
    """Поставить хвост речи в очередь, если SIP-клиент не отправил тишину."""
    matching_buffer_keys = [
        buffer_key for buffer_key in runtime.buffers if buffer_key.startswith(call_id + ":")
    ]

    for buffer_key in matching_buffer_keys:
        buffered_stream = runtime.buffers.pop(buffer_key)
        buffered_event = buffered_stream.get("event") or {}
        has_complete_speech = (
            buffered_stream["in_speech"]
            and buffered_stream["speech_bytes"] >= settings.min_utterance_bytes
        )
        mode_needs_tail = buffered_event.get("service_mode") in FINALIZED_RECORDING_MODES

        if has_complete_speech and mode_needs_tail:
            completed_event = dict(buffered_event)
            completed_event["_utterance_started_at"] = buffered_stream.get("utterance_started_at")
            completed_event["last_voice_packet_at"] = buffered_stream.get("last_voice_packet_at")
            completed_event["first_voice_packet_at"] = buffered_stream.get("first_voice_packet_at")
            if settings.streaming_enabled and buffered_event.get("service_mode") in {
                "interpret_ru",
                "interpret_en",
            }:
                completed_event["stream_phrase_id"] = str(buffered_stream["utterance_started_at"])
            enqueue_utterance(
                bytes(buffered_stream["utterance"]),
                completed_event,
                buffered_stream.get("received_at", time.time()),
                "call-ended",
            )


def finalize_recording(call_id: str) -> None:
    """Создать маркер завершения, не копируя текст в операционные логи."""
    recording = runtime.recordings.pop(call_id, None)
    if recording is None:
        return

    completed = {
        "completed_at": time.time(),
        "turns": recording["turns"],
        "audio_bytes": recording["audio_bytes"],
        "transcript_chars": recording["transcript_chars"],
        "retention_days": settings.recording_retention_days,
    }
    (recording["path"] / "completed.json").write_text(
        json.dumps(completed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"AI recording_finalized session={recording['session_id']} "
        f"turns={recording['turns']} audio_bytes={recording['audio_bytes']} "
        f"transcript_chars={recording['transcript_chars']}",
        flush=True,
    )


def clear_call_state(call_id: str) -> None:
    """Удалить краткоживущее состояние только после завершения всех реплик."""
    runtime.conversations.pop(call_id, None)
    runtime.reply_counts.pop(call_id, None)
    runtime.turn_counts.pop(call_id, None)
    runtime.call_locks.pop(call_id, None)
    for identity in list(runtime.stream_hypotheses):
        if identity[0] == call_id:
            runtime.stream_hypotheses.pop(identity, None)

    with runtime.lock:
        runtime.active_calls.pop(call_id, None)


def finalize_call(call_id: str) -> None:
    """Завершить хвост аудио, запись и память одного SIP-диалога."""
    # SIP endpoints commonly suppress RTP during silence. Flush the last
    # transcription turn on BYE because no trailing silent frames may arrive.
    flush_buffered_speech(call_id)
    wait_for_call(call_id)
    finalize_recording(call_id)
    clear_call_state(call_id)


def process_events():
    """Последовательно менять буферы; тяжёлые реплики уходят в отдельную очередь."""
    while True:
        try:
            event = runtime.work.get(timeout=0.1)
        except queue.Empty:
            try:
                flush_idle_streams(time.time())
            except queue.Full:
                print("AI idle_phrase_queue_full", flush=True)
            continue

        try:
            if event.get("control") == "end_call":
                finalize_call(event["call_id"])
            else:
                process_event(event)
        except Exception as error:
            print(
                f"AI processing_failed type={type(error).__name__}",
                flush=True,
            )
        finally:
            runtime.work.task_done()
