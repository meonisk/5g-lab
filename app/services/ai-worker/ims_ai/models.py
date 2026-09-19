"""Load the pinned local speech model and expose readiness through runtime."""

from __future__ import annotations

import os
import time

from faster_whisper import WhisperModel

from . import runtime, settings


def load_model():
    try:
        started = time.perf_counter()
        runtime.model = WhisperModel(
            settings.model_size,
            device=settings.device,
            compute_type=settings.compute_type,
            download_root=os.environ["AI_MODEL_CACHE"],
            revision=settings.model_revision,
        )
        print(
            f"AI model_ready backend={settings.backend} model={settings.model_size} device={settings.device} "
            f"load_seconds={time.perf_counter() - started:.3f}",
            flush=True,
        )
    except Exception as exc:
        runtime.model_error = f"{type(exc).__name__}: {exc}"
        print(
            f"AI model_failed backend={settings.backend} model={settings.model_size} error={runtime.model_error}",
            flush=True,
        )
