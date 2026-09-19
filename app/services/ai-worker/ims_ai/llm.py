"""Local LLM requests, normalization checks, and bounded conversation history."""

from __future__ import annotations

import json
import re
import time
import urllib.request

from . import runtime, settings
from .interpretation import prompt_for


def cyrillic_chars(text):
    return sum("\u0400" <= char <= "\u052f" for char in text)


def generate_reply(call_id, transcript, service_mode):
    conversation = runtime.conversations.setdefault(
        call_id, {"messages": [], "last_seen": time.time()}
    )
    conversation["last_seen"] = time.time()
    system_prompt = prompt_for(service_mode)
    request_body = json.dumps(
        {
            "model": settings.llm_model,
            "stream": False,
            "messages": (
                [{"role": "system", "content": system_prompt}]
                + conversation["messages"]
                + [{"role": "user", "content": transcript}]
            ),
            "options": {
                "temperature": settings.llm_temperature,
                "num_predict": settings.llm_max_tokens,
            },
        }
    ).encode()
    request = urllib.request.Request(
        settings.llm_url, request_body, {"Content-Type": "application/json"}
    )
    started = time.perf_counter_ns()
    response = json.load(urllib.request.urlopen(request, timeout=settings.llm_timeout))
    text = " ".join(response["message"]["content"].split())[: settings.llm_response_max_chars]
    return text, (time.perf_counter_ns() - started) / 1_000_000


def repair_translation_language(text, service_mode):
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
    request_body = json.dumps(
        {
            "model": settings.llm_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            "options": {"temperature": 0, "num_predict": settings.llm_max_tokens},
        }
    ).encode()
    request = urllib.request.Request(
        settings.llm_url, request_body, {"Content-Type": "application/json"}
    )
    started = time.perf_counter_ns()
    response = json.load(urllib.request.urlopen(request, timeout=settings.llm_timeout))
    repaired = " ".join(response["message"]["content"].split())
    repaired = repaired[: settings.llm_response_max_chars].strip().strip('"«»').strip()
    return repaired, (time.perf_counter_ns() - started) / 1_000_000


def normalize_transcript(transcript, detected_language):
    prompt = (
        settings.llm_english_transcription_prompt
        if detected_language == "en"
        else settings.llm_transcription_prompt
    )
    wrapper = (
        f"Input: «{transcript}»\nOutput:"
        if detected_language == "en"
        else f"Вход: «{transcript}»\nВыход:"
    )
    request_body = json.dumps(
        {
            "model": settings.llm_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": wrapper},
            ],
            "options": {
                "temperature": 0,
                "num_predict": settings.llm_normalization_max_tokens,
            },
        }
    ).encode()
    request = urllib.request.Request(
        settings.llm_url, request_body, {"Content-Type": "application/json"}
    )
    started = time.perf_counter_ns()
    response = json.load(urllib.request.urlopen(request, timeout=settings.llm_timeout))
    normalized = " ".join(response["message"]["content"].split())
    normalized = normalized.strip().strip('"«»').strip()
    if not normalized or len(normalized) > settings.normalized_transcript_max_chars:
        raise ValueError("normalized transcript has invalid length")
    if cyrillic_chars(transcript) and not cyrillic_chars(normalized):
        raise ValueError("normalized transcript changed language")
    if detected_language == "en" and not any(
        char.isascii() and char.isalpha() for char in normalized
    ):
        raise ValueError("normalized English transcript changed language")
    if re.match(
        r"(?i)^(?:(?:нормализованный|исправленный|очищенный)\s+текст|выход(?:ит)?|output)\s*:",
        normalized,
    ):
        raise ValueError("normalized transcript contains a preamble")
    if len(normalized) < len(transcript) * settings.llm_normalization_min_length_ratio:
        # A small local model may summarize instead of editing. Completeness is
        # more important than disfluency removal, so retain the source text.
        normalized = transcript
    return normalized, (time.perf_counter_ns() - started) / 1_000_000


def remember_turn(call_id, transcript, reply):
    conversation = runtime.conversations.setdefault(
        call_id, {"messages": [], "last_seen": time.time()}
    )
    conversation["messages"].extend(
        (
            {"role": "user", "content": transcript},
            {"role": "assistant", "content": reply},
        )
    )
    conversation["messages"] = conversation["messages"][-settings.history_turns * 2 :]
    conversation["last_seen"] = time.time()


def deliver_reply(call_id, text, voice, reply_id):
    body = json.dumps({"text": text, "voice": voice, "reply_id": reply_id}).encode()
    request = urllib.request.Request(
        f"{settings.voice_agent_url}/calls/{urllib.parse.quote(call_id, safe='')}/reply",
        body,
        {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {runtime.control_token}",
        },
    )
    urllib.request.urlopen(request, timeout=settings.reply_http_timeout).read()
