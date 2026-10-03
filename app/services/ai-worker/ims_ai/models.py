"""Load the pinned local speech model and expose readiness through runtime."""

from __future__ import annotations

import os
import time

import numpy as np
from faster_whisper import WhisperModel
from lab_common.http import request_json

from . import runtime, settings
from .interpretation import prompt_for


def load_model():
    try:
        started = time.perf_counter()
        model = WhisperModel(
            settings.model_size,
            device=settings.device,
            compute_type=settings.compute_type,
            download_root=os.environ["AI_MODEL_CACHE"],
            revision=settings.model_revision,
            cpu_threads=settings.stt_cpu_threads,
        )
        # Consume the lazy iterator: construction alone leaves first-inference
        # initialization on the caller's critical path.
        segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language="ru")
        list(segments)
        if settings.translation_backend == "opus-mt":
            from .translation import load_translation_models

            load_translation_models()
        if settings.translation_backend == "llm" or settings.transcript_normalization == "llm":
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
            # A one-word empty prompt does not warm GPU prefill shapes used by
            # the longer bilingual system prompts. Warm both actual directions.
            for mode, sample in (
                ("interpret_ru", "Здравствуйте, это проверка локального перевода."),
                ("interpret_en", "Hello, this is a local translation warmup."),
            ):
                for prompt_input in (sample, " ".join([sample] * 8)):
                    request_json(
                        "POST",
                        settings.llm_url,
                        payload={
                            "model": settings.llm_model,
                            "stream": False,
                            "keep_alive": settings.llm_keep_alive,
                            "messages": [
                                {"role": "system", "content": prompt_for(mode)},
                                {"role": "user", "content": prompt_input},
                            ],
                            "options": {"num_ctx": settings.llm_context_length, "num_predict": 1},
                        },
                        timeout=max(1, deadline - time.monotonic()),
                    )
            print(f"AI llm_warm model={settings.llm_model}", flush=True)
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("LLM warmup timed out; pipeline is not ready")
