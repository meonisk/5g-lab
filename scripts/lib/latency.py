"""Статистика замеров и этапы перевода из событий AI Worker и Voice Agent.

Общее для scripts/bench_5g.py и scripts/profile/: только чистые функции, без стенда.
"""

import re
import statistics

PORT = re.compile(r"^\s*Port #0*(\d+)\[[^\]]*\]\s+(\S+)", re.M)


def summary(values):
    """Медиана, минимум и максимум; пропуски (None) не считаются."""
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {
        "n": len(values),
        "median": round(statistics.median(values), 1),
        "min": round(min(values), 1),
        "max": round(max(values), 1),
    }


def percentile(values, rank):
    """Перцентиль с линейной интерполяцией между соседними значениями."""
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * rank / 100
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def describe(values):
    """Среднее, p95 и максимум ряда (например, занятых ядер за сценарий)."""
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 3),
        "p95": round(percentile(values, 95), 3),
        "max": round(max(values), 3),
    }


def _ms(value):
    return round(value or 0, 1)


def stage_row(event, tts):
    """Этапы одной реплики: событие AI Worker и озвучка ответа Voice Agent."""
    speech_end, audible = event.get("last_voice_packet_at"), tts.get("first_voice_rtp_at")
    return {
        "speech_end_to_reply_rtp_ms": round((audible - speech_end) * 1000, 1),
        # От начала речи до готовой фразы: сама речь плюс пауза AI_UTTERANCE_SILENCE_MS.
        "speech_plus_pause_ms": _ms(event.get("sentence_assembly_ms")),
        "queue_wait_ms": _ms(event.get("queue_wait_ms")),
        "stt_ms": _ms(event.get("stt_processing_ms")),
        "translation_ms": _ms(event.get("llm_processing_ms")),
        "tts_synthesis_ms": _ms(tts.get("synthesis_ms")),
    }


def vad_wait_ms(event):
    """Ожидание паузы: от последнего голосового пакета до готовой фразы."""
    end, ready = event.get("last_voice_packet_at"), event.get("sentence_ready_at")
    if not isinstance(end, (int, float)) or not isinstance(ready, (int, float)):
        return None
    return round((ready - end) * 1000, 1)


def conference_ports(text):
    """Порты конференц-моста PJSUA из вывода `cl`: (проигрыватель WAV, последний вызов)."""
    rows = PORT.findall(text)
    players = [number for number, label in rows if label.endswith(".wav")]
    calls = [number for number, label in rows if label.startswith("sip:")]
    return (players[-1] if players else None, calls[-1] if calls else None)
