"""Load the pinned local speech model and expose readiness through runtime."""

from __future__ import annotations

import os
import time

import numpy as np
from faster_whisper import WhisperModel
from lab_common.http import request_json

from . import runtime, settings


def load_model():
    try:
        started = time.perf_counter()
        model = WhisperModel(
            settings.model_size,
            device=settings.device,
            compute_type=settings.compute_type,
            download_root=os.environ["AI_MODEL_CACHE"],
            revision=settings.model_revision,
        )
        # Consume the lazy iterator: construction alone leaves first-inference
        # initialization on the caller's critical path.
        segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language="ru")
        list(segments)
        warm_llm()
        runtime.model = model
        print(
            f"AI model_ready backend={settings.backend} model={settings.model_size} device={settings.device} "
            f"load_seconds={time.perf_counter() - started:.3f}",
            flush=True,
        )
    except Exception as exc:
        runtime.model_error = f"{type(exc).__name__}: {exc}"
        print(f"AI model_failed error={runtime.model_error}", flush=True)


def warm_llm():
    """Do one real token of inference before advertising pipeline readiness."""
    deadline = time.monotonic() + settings.llm_warmup_timeout
    while time.monotonic() < deadline:
        try:
            request_json(
                "POST",
                settings.llm_url,
                payload={
                    "model": settings.llm_model,
                    "stream": False,
                    "keep_alive": settings.llm_keep_alive,
                    "messages": [{"role": "user", "content": "Say OK."}],
                    "options": {"num_ctx": settings.llm_context_length, "num_predict": 1},
                },
                timeout=max(1, deadline - time.monotonic()),
            )
            print(f"AI llm_warm model={settings.llm_model}", flush=True)
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("LLM warmup timed out; pipeline is not ready")
