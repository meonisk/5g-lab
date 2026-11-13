"""Отказ от старта, если контейнер поднят в обход scripts/start.py."""

from __future__ import annotations

from collections.abc import Mapping


def unapplied_mode_error(environ: Mapping[str, str]) -> str | None:
    """Режим AI (compact и др.) применяет только start.py: env и overlay из local/.

    Голый `docker compose up ai-worker` берёт lab.env без профиля режима и поднимает
    эталон с LLM, которого на CPU-стенде нет: worker висит на «LLM warmup timed out».
    Лучше сразу остановиться с понятной причиной.
    """
    if environ.get("AI_MODE_APPLIED"):
        return None
    wanted = environ.get("AI_MODE") or "baseline"
    return (
        f"режим AI не применён (AI_MODE={wanted}): поднимайте AI Worker через "
        "python3 scripts/start.py, а не docker compose up напрямую"
    )
