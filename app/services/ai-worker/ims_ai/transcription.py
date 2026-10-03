"""Сохранение реплики: нормализация, метка спикера и приватная запись."""

from __future__ import annotations

from . import settings
from .audio import decode_pcm8
from .llm import (
    cyrillic_chars,
    normalize_transcript,
)
from .recording import recording_session, save_recording_turn


def record_transcript(ulaw, event, result, transcript, detected_language):
    service_mode = result["service_mode"]
    call_ids = event.get("call_ids") or []
    call_id = call_ids[0] if len(call_ids) == 1 else None
    if not call_id or service_mode not in {"transcribe", "bilingual_test"}:
        return

    normalized_transcript = transcript
    if service_mode == "bilingual_test":
        recording = recording_session(call_id)
        source_key = event.get("source_stream_id") or str(event.get("ssrc"))
        speaker = recording["speakers"].setdefault(
            source_key, f"speaker_{len(recording['speakers']) + 1}"
        )
    else:
        speaker = "caller"
    if transcript and settings.transcript_normalization == "raw":
        result.update({"normalization_applied": False, "transcript_kind": "raw_asr"})
    elif transcript:
        try:
            normalized_transcript, normalization_ms = normalize_transcript(
                transcript, detected_language
            )
            result.update(
                {
                    "normalization_applied": True,
                    "normalization_llm_model": settings.llm_model,
                    "normalization_processing_ms": normalization_ms,
                    "normalized_transcript_chars": len(normalized_transcript),
                    "normalized_transcript_cyrillic_chars": cyrillic_chars(normalized_transcript),
                }
            )
            print(
                f"AI transcript_normalized model={settings.llm_model} input_chars={len(transcript)} "
                f"output_chars={len(normalized_transcript)} llm_ms={normalization_ms:.3f} "
                f"calls={call_ids}",
                flush=True,
            )
        except Exception as exc:
            # Fail closed for text persistence: keep the WAV so the turn can
            # be reprocessed, but never label raw STT output as normalized.
            normalized_transcript = ""
            result.update(
                {
                    "normalization_applied": False,
                    "normalization_error_type": type(exc).__name__,
                }
            )
            print(
                f"AI transcript_normalization_failed model={settings.llm_model} "
                f"type={type(exc).__name__} calls={call_ids}",
                flush=True,
            )
    saved = save_recording_turn(call_id, decode_pcm8(ulaw), normalized_transcript, result, speaker)
    if saved:
        result.update(
            {
                "recording_session_id": saved["session_id"],
                "recording_saved": saved["saved"],
                "recording_turn": saved.get("turn"),
                "recording_limit_reached": saved.get("limit_reached", False),
            }
        )
