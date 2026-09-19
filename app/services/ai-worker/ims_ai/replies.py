"""Перевод готовой реплики и доставка TTS в нужный языковой канал."""

from __future__ import annotations

import hashlib
import time

from . import runtime, settings
from .interpretation import (
    INTERPRETER_MODES,
    delivery_call,
    output_voice,
    validate_output,
)
from .llm import (
    cyrillic_chars,
    deliver_reply,
    generate_reply,
    remember_turn,
    repair_translation_language,
)


def reply_to_utterance(event, result, transcript, queued_at):
    service_mode = result["service_mode"]
    call_ids = event.get("call_ids") or []
    call_id = call_ids[0] if len(call_ids) == 1 else None
    # Без текста, единственного звонка и подходящего режима отвечать некому.
    if not transcript or not call_id:
        return
    if service_mode not in {"translate", "assistant", *INTERPRETER_MODES}:
        return
    if runtime.reply_counts.get(call_id, 0) >= settings.max_replies_per_call:
        return

    try:
        reply, llm_ms = generate_reply(call_id, transcript, service_mode)
        if reply:
            reply_cyrillic = cyrillic_chars(reply)
            try:
                latin_chars = validate_output(reply, service_mode, reply_cyrillic)
            except ValueError:
                if service_mode not in INTERPRETER_MODES:
                    raise
                reply, repair_ms = repair_translation_language(reply, service_mode)
                llm_ms += repair_ms
                reply_cyrillic = cyrillic_chars(reply)
                latin_chars = validate_output(reply, service_mode, reply_cyrillic)
            reply_voice = output_voice(service_mode)
            target_call_id = delivery_call(call_id, service_mode)
            reply_id = hashlib.sha256(
                f"{call_id}:{result['turn_index']}:{queued_at}".encode()
            ).hexdigest()[:16]
            dispatch_started = time.perf_counter_ns()
            deliver_reply(target_call_id, reply, reply_voice, reply_id)
            reply_dispatch_ms = (time.perf_counter_ns() - dispatch_started) / 1_000_000
            runtime.reply_counts[call_id] = runtime.reply_counts.get(call_id, 0) + 1
            remember_turn(call_id, transcript, reply)
            while len(runtime.reply_counts) > settings.buffer_max:
                evicted = next(iter(runtime.reply_counts))
                runtime.reply_counts.pop(evicted, None)
                runtime.turn_counts.pop(evicted, None)
                runtime.conversations.pop(evicted, None)
            result.update(
                {
                    "llm_model": settings.llm_model,
                    "llm_response_chars": len(reply),
                    "llm_response_cyrillic_chars": reply_cyrillic,
                    "llm_response_latin_chars": latin_chars,
                    "reply_voice": reply_voice,
                    "reply_id": reply_id,
                    "llm_processing_ms": llm_ms,
                    "reply_delivered": True,
                    "reply_dispatch_ms": reply_dispatch_ms,
                    "reply_destination_mode": (
                        "interpret_en"
                        if service_mode == "interpret_ru"
                        else "interpret_ru"
                        if service_mode == "interpret_en"
                        else service_mode
                    ),
                    "reply_index": runtime.reply_counts[call_id],
                }
            )
            print(
                f"AI reply_delivered model={settings.llm_model} prompt_chars={len(transcript)} "
                f"response_chars={len(reply)} llm_ms={llm_ms:.3f} calls={call_ids}",
                flush=True,
            )
    except Exception as exc:
        result.update(
            {
                "llm_model": settings.llm_model,
                "reply_delivered": False,
                "llm_error_type": type(exc).__name__,
            }
        )
        print(
            f"AI reply_failed model={settings.llm_model} type={type(exc).__name__} calls={call_ids}",
            flush=True,
        )
