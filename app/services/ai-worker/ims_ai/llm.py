"""Три операции LLM используют один HTTP-клиент: ответ, перевод и очистка текста."""

import re
import time
from urllib.parse import quote

from lab_common.http import request_json

from . import runtime, settings
from .interpretation import prompt_for


def cyrillic_chars(text: str) -> int:
    return sum("\u0400" <= char <= "\u052f" for char in text)


def chat(messages: list[dict], max_tokens: int, temperature: float = 0) -> tuple[str, float]:
    """Единое место для протокола Ollama и измерения времени LLM."""
    started = time.perf_counter()
    response = request_json(
        "POST",
        settings.llm_url,
        payload={
            "model": settings.llm_model,
            "stream": False,
            "keep_alive": settings.llm_keep_alive,
            "messages": messages,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": settings.llm_context_length,
            },
        },
        timeout=settings.llm_timeout,
    )
    text = " ".join(response["message"]["content"].split())
    # Timing only: never put caller text in operational logs.
    print(
        f"LLM timing load_ms={response.get('load_duration', 0) / 1e6:.1f} "
        f"prompt_ms={response.get('prompt_eval_duration', 0) / 1e6:.1f} "
        f"generation_ms={response.get('eval_duration', 0) / 1e6:.1f} "
        f"tokens={response.get('eval_count', 0)}",
        flush=True,
    )
    return text, (time.perf_counter() - started) * 1000


def conversation_for(call_id: str) -> dict:
    conversation = runtime.conversations.setdefault(call_id, {"messages": [], "last_seen": 0})
    conversation["last_seen"] = time.time()
    return conversation


def generate_reply(call_id, transcript, service_mode):
    if settings.translation_backend == "opus-mt":
        from .translation import translate

        return translate(transcript, service_mode)
    messages = [
        {"role": "system", "content": prompt_for(service_mode)},
        *conversation_for(call_id)["messages"],
        {"role": "user", "content": transcript},
    ]
    text, elapsed = chat(messages, settings.llm_max_tokens, settings.llm_temperature)
    return text[: settings.llm_response_max_chars], elapsed


def repair_translation_language(text, service_mode):
    """Одна попытка исправить язык; окончательное решение принимает языковой барьер."""
    if settings.translation_backend != "llm":
        raise ValueError("Перевод не прошёл языковой барьер; fallback к LLM отключён")
    if service_mode == "interpret_en":
        prompt = (
            "Перепиши перевод полностью на русском языке и только кириллицей. "
            "Имена и сокращения транслитерируй. Верни только исправленный перевод."
        )
    else:
        prompt = (
            "Rewrite the translation entirely in English using Latin letters only. "
            "Return only the corrected translation."
        )
    repaired, elapsed = chat(
        [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
        settings.llm_max_tokens,
    )
    return repaired[: settings.llm_response_max_chars].strip(' "«»'), elapsed


def normalize_transcript(transcript, detected_language):
    english = detected_language == "en"
    prompt = (
        settings.llm_english_transcription_prompt if english else settings.llm_transcription_prompt
    )
    wrapper = f"Input: «{transcript}»\nOutput:" if english else f"Вход: «{transcript}»\nВыход:"
    text, elapsed = chat(
        [{"role": "system", "content": prompt}, {"role": "user", "content": wrapper}],
        settings.llm_normalization_max_tokens,
    )
    text = text.strip(' "«»')
    validate_normalization(transcript, text, detected_language)
    # Маленькая модель иногда пересказывает вместо редактирования: сохраняем исходник.
    if len(text) < len(transcript) * settings.llm_normalization_min_length_ratio:
        text = transcript
    return text, elapsed


def validate_normalization(source: str, result: str, language: str):
    if not result or len(result) > settings.normalized_transcript_max_chars:
        raise ValueError("normalized transcript has invalid length")
    if cyrillic_chars(source) and not cyrillic_chars(result):
        raise ValueError("normalized transcript changed language")
    if language == "en" and not any(char.isascii() and char.isalpha() for char in result):
        raise ValueError("normalized English transcript changed language")
    if re.match(
        r"(?i)^(?:(?:нормализованный|исправленный|очищенный)\s+текст|выход(?:ит)?|output)\s*:",
        result,
    ):
        raise ValueError("normalized transcript contains a preamble")


def remember_turn(call_id, transcript, reply):
    history = conversation_for(call_id)["messages"]
    history.extend(
        (
            {"role": "user", "content": transcript},
            {"role": "assistant", "content": reply},
        )
    )
    del history[: -settings.history_turns * 2]


def deliver_reply(call_id, text, voice, reply_id):
    request_json(
        "POST",
        f"{settings.voice_agent_url}/calls/{quote(call_id, safe='')}/reply",
        payload={"text": text, "voice": voice, "reply_id": reply_id},
        token=runtime.control_token,
        timeout=settings.reply_http_timeout,
    )
