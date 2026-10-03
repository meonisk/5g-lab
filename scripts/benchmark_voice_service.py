"""Измерить реальный синтез Voice Agent вместе с FFmpeg; запуск в одноразовом контейнере."""

import argparse
import json
import os
import resource
import time
from pathlib import Path

from benchmark_piper import SAMPLES


def main():
    from ims_voice import runtime
    from ims_voice.audio import synthesize

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if "local" not in args.output.resolve().parts:
        parser.error("Сохраняйте результат в local/")
    started = time.perf_counter()
    if runtime.tts_backend == "piper":
        from ims_voice.neural_voice import load_voice

        for voice in runtime.piper_voices:
            load_voice(voice)
    load_seconds = time.perf_counter() - started
    records = []
    for language, voice in (("ru", runtime.tts_voice), ("en", runtime.tts_translation_voice)):
        for index, text in enumerate(SAMPLES[language]):
            cpu_start = os.times()
            started = time.perf_counter()
            pcmu = synthesize(text, voice)
            elapsed = time.perf_counter() - started
            cpu_end = os.times()
            records.append(
                {
                    "language": language,
                    "sample_index": index,
                    "audio_seconds": len(pcmu) / 8000,
                    "synthesis_and_conversion_seconds": elapsed,
                    "cpu_seconds": sum(cpu_end[:4]) - sum(cpu_start[:4]),
                }
            )
    cgroup = Path("/sys/fs/cgroup")
    report = {
        "status": "VOICE_COMPONENT_ONLY",
        "backend": runtime.tts_backend,
        "cpu_mem_arena": runtime.piper_cpu_mem_arena,
        "load_seconds": load_seconds,
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "cgroup_memory_peak_bytes": int((cgroup / "memory.peak").read_text()),
        "cgroup_memory_events": (cgroup / "memory.events").read_text(),
        "cpu_max": (cgroup / "cpu.max").read_text().strip(),
        "memory_max": (cgroup / "memory.max").read_text().strip(),
        "records": records,
        "limitations": "Шесть разных синтетических фраз, по одному вызову; без SIP/RTP и параллельных звонков. Запускать в новом контейнере, чтобы кэш не исказил измерение.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"VOICE BENCHMARK: {args.output}")


if __name__ == "__main__":
    main()
