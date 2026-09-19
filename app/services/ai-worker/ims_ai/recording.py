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
