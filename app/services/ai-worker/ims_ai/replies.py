"""Переводит готовую реплику и доставляет TTS в нужный языковой канал."""

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

REPLY_MODES = {"translate", "assistant", *INTERPRETER_MODES}


def single_call_id(event: dict) -> str | None:
    """Ответ допустим только для аудио, однозначно связанного с одним звонком."""
    call_ids = event.get("call_ids") or []
    return call_ids[0] if len(call_ids) == 1 else None


def may_reply(call_id: str | None, transcript: str, service_mode: str) -> bool:
    if call_id is None or not transcript or service_mode not in REPLY_MODES:
        return False

    delivered_replies = runtime.reply_counts.get(call_id, 0)
    limit = settings.max_replies_per_call
    if settings.streaming_enabled and service_mode in INTERPRETER_MODES:
        limit = settings.stream_max_replies
    return delivered_replies < limit


def create_reply_id(call_id: str, turn_index: int, queued_at: float) -> str:
    """Стабильный короткий ID связывает AI и TTS-метрики без текста ответа."""
    identity = f"{call_id}:{turn_index}:{queued_at}".encode()
    return hashlib.sha256(identity).hexdigest()[:16]


def generate_validated_reply(
    call_id: str,
    transcript: str,
    service_mode: str,
) -> tuple[str, float, int, int]:
    """Сгенерировать ответ и один раз исправить неверный язык перевода."""
    reply, llm_processing_ms = generate_reply(call_id, transcript, service_mode)
    if not reply:
        return "", llm_processing_ms, 0, 0

    reply_cyrillic_chars = cyrillic_chars(reply)

    try:
        reply_latin_chars = validate_output(
            reply,
            service_mode,
            reply_cyrillic_chars,
        )
    except ValueError:
        if service_mode not in INTERPRETER_MODES:
            raise

        repaired_reply, repair_processing_ms = repair_translation_language(
            reply,
            service_mode,
        )
        reply = repaired_reply
        llm_processing_ms += repair_processing_ms
        reply_cyrillic_chars = cyrillic_chars(reply)
        reply_latin_chars = validate_output(
            reply,
            service_mode,
            reply_cyrillic_chars,
        )

    return (
        reply,
        llm_processing_ms,
        reply_cyrillic_chars,
        reply_latin_chars,
    )


def opposite_interpreter_mode(service_mode: str) -> str:
    """Метрика показывает языковой канал, куда ушёл результат."""
    if service_mode == "interpret_ru":
        return "interpret_en"
    if service_mode == "interpret_en":
        return "interpret_ru"
    return service_mode


def increment_reply_count(call_id: str) -> int:
    reply_index = runtime.reply_counts.get(call_id, 0) + 1
    runtime.reply_counts[call_id] = reply_index
    return reply_index


def evict_old_conversations() -> None:
    """Ограничить память процесса тем же пределом, что и аудиобуферы."""
    while len(runtime.reply_counts) > settings.buffer_max:
        oldest_call_id = next(iter(runtime.reply_counts))
        runtime.reply_counts.pop(oldest_call_id, None)
        runtime.turn_counts.pop(oldest_call_id, None)
        runtime.conversations.pop(oldest_call_id, None)


def record_success(
    result: dict,
    reply: str,
    reply_id: str,
    reply_voice: str,
    reply_index: int,
    service_mode: str,
    llm_processing_ms: float,
    dispatch_ms: float,
    reply_cyrillic_chars: int,
    reply_latin_chars: int,
) -> None:
    result.update(
        {
            "llm_model": settings.llm_model,
            "translation_backend": settings.translation_backend,
            "llm_response_chars": len(reply),
            "llm_response_cyrillic_chars": reply_cyrillic_chars,
            "llm_response_latin_chars": reply_latin_chars,
            "llm_processing_ms": llm_processing_ms,
            "reply_voice": reply_voice,
            "reply_id": reply_id,
            "reply_delivered": True,
            "reply_dispatch_ms": dispatch_ms,
            "reply_destination_mode": opposite_interpreter_mode(service_mode),
            "reply_index": reply_index,
        }
    )


def reply_to_utterance(
    event: dict,
    result: dict,
    transcript: str,
    queued_at: float,
) -> None:
    """Выполнить LLM и TTS-часть конвейера для одной распознанной реплики."""
    service_mode = result["service_mode"]
    call_id = single_call_id(event)
    if not may_reply(call_id, transcript, service_mode):
        return

    call_ids = event.get("call_ids") or []

    try:
        (
            reply,
            llm_processing_ms,
            reply_cyrillic_chars,
            reply_latin_chars,
        ) = generate_validated_reply(call_id, transcript, service_mode)
        if not reply:
            return

        reply_voice = output_voice(service_mode)
        destination_call_id = delivery_call(call_id, service_mode)
        reply_id = create_reply_id(call_id, result["turn_index"], queued_at)

        dispatch_started_at = time.perf_counter_ns()
        deliver_reply(destination_call_id, reply, reply_voice, reply_id)
        dispatch_ms = (time.perf_counter_ns() - dispatch_started_at) / 1_000_000

        reply_index = increment_reply_count(call_id)
        remember_turn(call_id, transcript, reply)
        evict_old_conversations()

        record_success(
            result,
            reply,
            reply_id,
            reply_voice,
            reply_index,
            service_mode,
            llm_processing_ms,
            dispatch_ms,
            reply_cyrillic_chars,
            reply_latin_chars,
        )
        print(
            f"AI reply_delivered model={settings.llm_model} "
            f"prompt_chars={len(transcript)} response_chars={len(reply)} "
            f"llm_ms={llm_processing_ms:.3f} calls={call_ids}",
            flush=True,
        )
    except Exception as error:
        # Ошибка ответа не должна терять STT-метрики уже обработанной реплики.
        result.update(
            {
                "llm_model": settings.llm_model,
                "reply_delivered": False,
                "llm_error_type": type(error).__name__,
            }
        )
        print(
            f"AI reply_failed model={settings.llm_model} "
            f"type={type(error).__name__} calls={call_ids}",
            flush=True,
        )
