"""Паузы внутри фразы диалога: где её можно закончить, не разрезав слово.

Живая речь идёт с паузами 200–500 мс между предложениями — короче обычного порога
конца фразы. Поэтому в диалоге:
- фраза длиннее AI_DIALOGUE_SHORT_PAUSE_AFTER_SECONDS заканчивается уже на паузе
  AI_DIALOGUE_SHORT_PAUSE_MS («short-pause»);
- если пауз такой длины не было и фраза дошла до предела длины, она режется посередине
  самой длинной паузы внутри неё («pause-cut»), а остаток сразу начинает новую фразу.
  Разрез посреди звука («maximum-duration») — только если пауз не было совсем.
"""

from __future__ import annotations

from . import settings

# Короче 80 мс — не пауза, а промежуток между звуками внутри слова.
MIN_CUT_PAUSE_BYTES = 640


def remember_pause(state: dict) -> None:
    """Вызывается на голосовом кадре после тишины: запомнить паузу как место разреза."""
    run = state["silence_bytes"]
    if run < MIN_CUT_PAUSE_BYTES or run < state["cut_pause_bytes"]:
        return
    if len(state["utterance"]) < settings.min_utterance_bytes:
        return
    state.update(
        cut_at=len(state["utterance"]) - run // 2,
        cut_pause_bytes=run,
        # Конец голоса перед паузой: last_voice_packet_at ещё не обновлён этим кадром.
        cut_voice_end_at=state["last_voice_packet_at"],
        cut_resume_pending=True,
    )


def short_pause_reached(state: dict) -> bool:
    return (
        len(state["utterance"]) >= settings.dialogue_short_pause_after_bytes
        and state["silence_bytes"] >= settings.dialogue_short_pause_bytes
    )


def split_at_pause(state: dict) -> tuple[bytes, dict] | None:
    """Отрезать от фразы всё после лучшей паузы: (остаток, состояние для него) или None."""
    cut = state.get("cut_at")
    if not cut:
        return None
    remainder = bytes(state["utterance"][cut:])
    started = state["utterance_started_at"]
    following = {
        "utterance": bytearray(remainder),
        "in_speech": True,
        "speech_bytes": max(0, len(remainder) - state["silence_bytes"]),
        "silence_bytes": state["silence_bytes"],
        "utterance_started_at": started + cut / 8000 if started else None,
        "first_voice_packet_at": state.get("cut_resume_at"),
        "last_voice_packet_at": state["last_voice_packet_at"],
    }
    del state["utterance"][cut:]
    state["last_voice_packet_at"] = state.get("cut_voice_end_at")
    return remainder, following
