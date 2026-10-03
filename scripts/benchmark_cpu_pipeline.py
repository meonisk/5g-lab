"""Компонентный STT/перевод benchmark внутри ai-worker на синтетическом PCM16/8000 WAV."""

import argparse
import json
import platform
import resource
import statistics
import time
import wave
from pathlib import Path


def main():
    # Запуск только в Python 3.11 сервисного образа; audioop отсутствует в Python 3.13+.
    import audioop

    from ims_ai import runtime, settings
    from ims_ai.models import load_model
    from ims_ai.translation import translate
    from ims_ai.utterances import recognize

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ru-wav", type=Path, required=True)
    parser.add_argument("--en-wav", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats должен быть положительным")
    if settings.translation_backend != "opus-mt":
        parser.error("Этот benchmark предназначен для CPU-профилей OPUS-MT")
    if "local" not in args.output.resolve().parts:
        parser.error("Сохраняйте результат в local/")
    started = time.perf_counter()
    load_model()
    if runtime.model is None:
        raise RuntimeError(runtime.model_error)
    load_seconds = time.perf_counter() - started
    records = []
    for repeat in range(args.repeats + 1):
        for language, path in (("ru", args.ru_wav), ("en", args.en_wav)):
            with wave.open(str(path), "rb") as source:
                if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (
                    8000,
                    1,
                    2,
                ):
                    raise ValueError("Нужен mono PCM16/8000 WAV")
                duration = source.getnframes() / 8000
                pcmu = audioop.lin2ulaw(source.readframes(source.getnframes()), 2)
            mode = "interpret_" + language
            cpu_before = time.process_time()
            result = recognize(pcmu, mode)
            translated, translation_ms = translate(result.transcript, mode)
            if not result.transcript or not translated:
                raise ValueError("Пустая расшифровка или перевод")
            records.append(
                {
                    "language": language,
                    "repeat": repeat,
                    "warmup": repeat == 0,
                    "audio_seconds": duration,
                    "stt_ms": result.processing_ms,
                    "translation_ms": translation_ms,
                    "cpu_seconds": time.process_time() - cpu_before,
                    "transcript": result.transcript,
                    "translation": translated,
                }
            )
    summaries = []
    for language in ("ru", "en"):
        subset = [row for row in records if row["language"] == language and not row["warmup"]]
        summaries.append(
            {
                "language": language,
                "stt_ms_median": statistics.median(row["stt_ms"] for row in subset),
                "translation_ms_median": statistics.median(row["translation_ms"] for row in subset),
                "cpu_seconds_median": statistics.median(row["cpu_seconds"] for row in subset),
                "audio_seconds": subset[0]["audio_seconds"],
            }
        )
    cgroup = Path("/sys/fs/cgroup")
    report = {
        "status": "COMPONENTS_ONLY",
        "platform": platform.platform(),
        "model": settings.model_size,
        "revision": settings.model_revision,
        "device": settings.device,
        "compute_type": settings.compute_type,
        "stt_threads": settings.stt_cpu_threads,
        "mt_threads": settings.translation_threads,
        "cpu_max": (cgroup / "cpu.max").read_text().strip(),
        "memory_max": (cgroup / "memory.max").read_text().strip(),
        "load_seconds": load_seconds,
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "cgroup_memory_peak_bytes": int((cgroup / "memory.peak").read_text()),
        "cgroup_memory_events": (cgroup / "memory.events").read_text(),
        "summary": summaries,
        "records": records,
        "limitations": "Две синтетические фразы; без ожидания конца речи, очередей, TTS, IMS и воспроизведения UE.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"CPU PIPELINE BENCHMARK: {args.output}", flush=True)


if __name__ == "__main__":
    main()
