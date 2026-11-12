"""Перебор настроек AI внутри одноразового контейнера из образа AI Worker.

Запускается scripts/profile/sweep.py: python /sweep-code/sweep_worker.py /sweep/plan.json.
Распознавание — код сервиса ims_ai.utterances.recognize на PCMU 8 кГц, перевод —
ims_ai.translation.translate (OPUS-MT). Модель Whisper берётся только из локального
кэша (сети у контейнера нет): нет снимка — модель пропускается с причиной. Результат —
одна строка JSON в stdout, ход работы — в stderr. Текст фраз синтетический.
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")
import numpy as np  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402
from ims_ai import runtime, settings  # noqa: E402
from ims_ai.streaming import stable_prefix  # noqa: E402
from ims_ai.utterances import recognize  # noqa: E402

MODE = "translate"


def log(message):
    print(f"[sweep] {message}", file=sys.stderr, flush=True)


def snapshot(size, revision):
    """Каталог снимка модели в кэше HF: закреплённая ревизия, иначе любая полная."""
    root = Path(os.environ["AI_MODEL_CACHE"]) / f"models--Systran--faster-whisper-{size}/snapshots"
    if (root / revision / "model.bin").is_file():
        return root / revision, revision
    others = (
        sorted(p for p in root.glob("*") if (p / "model.bin").is_file()) if root.is_dir() else []
    )
    return (others[0], others[0].name) if others else (None, None)


def load_translation():
    """OPUS-MT сервиса, если он в этом режиме; иначе перевод берётся из сценариев."""
    if settings.translation_backend != "opus-mt":
        return None, f"AI_TRANSLATION_BACKEND={settings.translation_backend}: без OPUS-MT"
    manifest = Path(settings.translation_model_root) / "ru-en/manifest.json"
    if not manifest.is_file():
        return None, f"нет {manifest}"
    from ims_ai import translation

    translation.load_translation_models()
    return translation.translate, ""


def load_model(path, threads):
    started = time.perf_counter()
    model = WhisperModel(str(path), device=settings.device, compute_type=settings.compute_type,
                         cpu_threads=threads)  # fmt: skip
    # Первый inference инициализирует движок: как load_model() сервиса, не в замер.
    segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language="ru")
    list(segments)
    runtime.model = model
    return round((time.perf_counter() - started) * 1000, 1)


def measure(audio, translate):
    """Одна фраза: время и CPU процесса на распознавание, затем перевод текста."""
    cpu = time.process_time()
    result = recognize(audio, MODE)
    row = {
        "stt_ms": round(result.processing_ms, 1),
        "cpu_ms": round((time.process_time() - cpu) * 1000, 1),
        "transcript": result.transcript,
        "translation_ms": None,
    }
    if translate and result.transcript:
        try:
            row["translation_ms"] = round(translate(result.transcript, MODE)[1], 1)
        except Exception as error:  # отказ перевода — строка замера, а не обрыв перебора
            row["translation_error"] = f"{type(error).__name__}: {error}"
    return row


def first_partial(audio, interval_ms, holdback):
    """Потоковый режим: снимки растущей фразы; первый устойчивый префикс — частичный итог.

    Время от начала речи: снимок готов, когда прозвучал его звук и закончено
    распознавание предыдущего (один обработчик, AI_PROCESSING_WORKERS=1), плюс его
    собственное распознавание. Сервис пропускает устаревшие снимки — это верхняя оценка.
    """
    previous, step, ready = "", interval_ms * 8, 0.0
    for end in range(step, len(audio) + step, step):
        chunk = audio[: min(end, len(audio))]
        result = recognize(chunk, MODE)
        ready = max(len(chunk) / 8, ready) + result.processing_ms
        final = end >= len(audio)
        if stable_prefix(previous, result.transcript, final, holdback):
            return {"first_partial_ms": round(ready, 1), "snapshots": end // step,
                    "speech_ms": round(len(audio) / 8, 1), "final": final}  # fmt: skip
        previous = result.transcript
    return {"first_partial_ms": None, "snapshots": len(audio) // step + 1, "final": True}


def main():
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    folder = Path(sys.argv[1]).parent
    phrases = [(p["id"], (folder / p["file"]).read_bytes()) for p in plan["phrases"]]
    translate, translation_note = load_translation()
    result = {
        "translation": translation_note or "opus-mt",
        "models": {},
        "runs": [],
        "streaming": [],
    }

    for size, revision in plan["models"].items():
        path, found = snapshot(size, revision)
        if path is None:
            result["models"][size] = {"status": "skip", "reason": f"нет модели {size} в кэше"}
            log(f"{size}: SKIP — нет в кэше")
            continue
        info = {"status": "ok", "revision": found, "pinned": found == revision, "load_ms": {}}
        result["models"][size] = info
        for threads in plan["threads"]:
            info["load_ms"][threads] = load_model(path, threads)
            log(f"{size}: потоков {threads}")
            for repeat in range(plan["repeats"]):
                for phrase, audio in phrases:
                    row = measure(audio, translate)
                    result["runs"].append({"model": size, "threads": threads, "repeat": repeat,
                                           "phrase": phrase, **row})  # fmt: skip
        if plan["streaming"]:
            load_model(path, plan["default_threads"])
            for phrase, audio in phrases:
                row = first_partial(audio, plan["stream_interval_ms"], plan["holdback"])
                result["streaming"].append({"model": size, "threads": plan["default_threads"],
                                            "phrase": phrase, **row})  # fmt: skip
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
