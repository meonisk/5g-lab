"""Opt-in private WAV and transcript persistence with a per-call size bound."""

from __future__ import annotations

import hashlib
import json
import time
import wave

from . import runtime, settings


def recording_session(call_id):
    state = runtime.recordings.get(call_id)
    if state:
        return state
    session_id = hashlib.sha256(call_id.encode()).hexdigest()[:20]
    path = settings.recording_root / session_id
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    state = {
        "session_id": session_id,
        "path": path,
        "turns": 0,
        "audio_bytes": 0,
        "started_at": time.time(),
        "transcript_chars": 0,
        "speakers": {},
    }
    runtime.recordings[call_id] = state
    notice = (
        "PRIVATE LOCAL RECORDING\n"
        "Created only by an explicit call to the transcription service.\n"
        f"Configured retention: {settings.recording_retention_days} days.\n"
        "Review and delete this directory according to the declared policy.\n"
    )
    (path / "README.txt").write_text(notice, encoding="utf-8")
    return state


def save_recording_turn(call_id, pcm8, transcript, result, speaker):
    if not settings.recording_enabled:
        return None
    state = recording_session(call_id)
    audio_bytes = int(pcm8.nbytes)
    if state["audio_bytes"] + audio_bytes > settings.recording_max_bytes:
        return {
            "session_id": state["session_id"],
            "saved": False,
            "limit_reached": True,
        }
    state["turns"] += 1
    state["audio_bytes"] += audio_bytes
    state["transcript_chars"] += len(transcript)
    turn_name = f"turn-{state['turns']:04d}"
    wav_path = state["path"] / f"{turn_name}.wav"
    with wave.open(str(wav_path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(8000)
        target.writeframes(pcm8.astype("<i2", copy=False).tobytes())
    if transcript:
        with (state["path"] / "transcript.txt").open("a", encoding="utf-8") as target:
            target.write(
                f"[{speaker}/{result.get('detected_language') or 'und'}] {transcript.strip()}\n"
            )
    private_metadata = {
        "turn": state["turns"],
        "audio_file": wav_path.name,
        "audio_duration_seconds": result["audio_duration_seconds"],
        "audio_sha256": result["audio_sha256"],
        "transcript_chars": len(transcript),
        "normalization_applied": result.get("normalization_applied", False),
        "transcript_kind": result.get(
            "transcript_kind",
            "llm_normalized" if result.get("normalization_applied") else "unavailable",
        ),
        "raw_transcript_chars": result.get("transcript_chars"),
        "normalization_processing_ms": result.get("normalization_processing_ms"),
        "detected_language": result.get("detected_language"),
        "speaker": speaker,
        "processing_ms": result.get("processing_ms"),
    }
    with (state["path"] / "manifest.jsonl").open("a", encoding="utf-8") as target:
        target.write(json.dumps(private_metadata, ensure_ascii=False) + "\n")
    return {
        "session_id": state["session_id"],
        "saved": True,
        "turn": state["turns"],
        "audio_bytes": audio_bytes,
    }


TIMELINE_FIELDS = (
    "recording_turn", "call_ids", "service_mode", "utterance_end_reason",
    "audio_duration_seconds", "first_voice_packet_at", "last_voice_packet_at",
    "sentence_ready_at", "ai_started_at", "queue_wait_ms", "stt_processing_ms",
    "llm_processing_ms", "processed_at", "reply_id", "reply_delivered", "detected_language",
)  # fmt: skip


def save_turn_timeline(result, transcript, translation):
    """Ход фразы в записи звонка: метки времени, распознанный текст и перевод.

    Только для звонков с записью (услуга record): текст лежит рядом с transcript.txt в
    приватном каталоге записи, в журналы и /events не попадает.
    """
    if not result.get("recording_saved"):
        return
    line = {key: result.get(key) for key in TIMELINE_FIELDS}
    line.update(transcript=transcript, translation=translation)
    path = settings.recording_root / result["recording_session_id"] / "timeline.jsonl"
    with path.open("a", encoding="utf-8") as target:
        target.write(json.dumps(line, ensure_ascii=False) + "\n")


def add_recording_legs(session_call_id, legs):
    """Ноги одного звонка пишутся в одну запись; закрыть её можно после последней ноги."""
    runtime.record_sessions.setdefault(session_call_id, set()).update(cid for cid, _ in legs)
    for call_id, speaker in legs:
        runtime.record_legs[call_id] = {"session_call_id": session_call_id, "speaker": speaker}


def recording_target(call_id, service_mode, event):
    """(ключ записи, говорящий) для реплики или None — эту ногу не записывают."""
    leg = runtime.record_legs.get(call_id)
    if leg is not None:
        return leg["session_call_id"], leg["speaker"]
    if service_mode == "transcribe":
        return call_id, "caller"
    if service_mode in {"bilingual_test", "record"}:
        recording = recording_session(call_id)
        source_key = event.get("source_stream_id") or str(event.get("ssrc"))
        speaker = recording["speakers"].setdefault(
            source_key, f"speaker_{len(recording['speakers']) + 1}"
        )
        return call_id, speaker
    return None


def finished_recording(call_id):
    """Ключ записи, которую закрывает конец этой ноги; None — другие ноги ещё говорят."""
    leg = runtime.record_legs.pop(call_id, None)
    if leg is None:
        return call_id
    session_call_id = leg["session_call_id"]
    remaining = runtime.record_sessions.get(session_call_id, set())
    remaining.discard(call_id)
    if remaining:
        return None
    runtime.record_sessions.pop(session_call_id, None)
    return session_call_id
