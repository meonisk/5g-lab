"""Измерить закреплённые голоса Piper отдельно от IMS; результаты хранить в local/."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import platform
import statistics
import threading
import time
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = {
    "ru": [
        "Встреча завтра в пять часов.",
        "Здравствуйте! Я хорошо слышу перевод. Давайте продолжим разговор и запишем результат проверки.",
        "Пожалуйста, перенесите встречу с пятницы на понедельник. Мы не сможем приехать раньше десяти часов. Подтвердите новый адрес и номер комнаты.",
    ],
    "en": [
        "The meeting is tomorrow at five.",
        "Hello! I can hear the translation clearly. Let us continue our conversation and record the test results.",
        "Please move the meeting from Friday to Monday. We will not be able to arrive before ten o'clock. Confirm the new address and room number.",
    ],
}


def read_settings():
    settings = {}
    for line in (ROOT / "app/config/lab.env").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            settings[key] = value.strip().strip('"')
    return settings


def verified_asset(url, destination, digest):
    if not destination.exists():
        temporary = destination.with_suffix(destination.suffix + ".download")
        with urllib.request.urlopen(url, timeout=120) as source, temporary.open("wb") as output:
            while chunk := source.read(1024 * 1024):
                output.write(chunk)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
            raise ValueError(f"SHA256 не совпадает: {destination.name}")
        temporary.replace(destination)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        raise ValueError(f"SHA256 не совпадает: {destination.name}")


def prepare_assets(directory, settings):
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for language, prefix in (("ru", "PIPER"), ("en", "PIPER_EN")):
        destination = directory / Path(settings[f"{prefix}_MODEL_PATH"]).name
        verified_asset(
            settings[f"{prefix}_MODEL_URL"], destination, settings[f"{prefix}_MODEL_SHA256"]
        )
        verified_asset(
            settings[f"{prefix}_MODEL_URL"] + ".json",
            Path(str(destination) + ".json"),
            settings[f"{prefix}_CONFIG_SHA256"],
        )
        paths[language] = destination
    return paths


def measure(paths, threads, repeats, disable_arena=False):
    import onnxruntime
    import psutil
    from piper import PiperVoice, SynthesisConfig
    from piper.config import PiperConfig

    process = psutil.Process()
    rss_start = process.memory_info().rss
    peak = [rss_start]
    stop = threading.Event()

    def sample_memory():
        while not stop.is_set():
            peak[0] = max(peak[0], process.memory_info().rss)
            stop.wait(0.005)

    sampler = threading.Thread(target=sample_memory, daemon=True)
    sampler.start()
    voices, loads, records = {}, [], []
    try:
        for language, path in paths.items():
            started = time.perf_counter()
            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = threads
            options.inter_op_num_threads = 1
            options.enable_cpu_mem_arena = not disable_arena
            voices[language] = PiperVoice(
                config=PiperConfig.from_dict(
                    json.loads(Path(str(path) + ".json").read_text(encoding="utf-8"))
                ),
                session=onnxruntime.InferenceSession(
                    str(path), sess_options=options, providers=["CPUExecutionProvider"]
                ),
            )
            loads.append(
                {
                    "language": language,
                    "seconds": time.perf_counter() - started,
                    "process_rss_bytes": process.memory_info().rss,
                    "model_bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )

        for repeat in range(repeats + 1):
            for language, voice in voices.items():
                for sample_index, text in enumerate(SAMPLES[language]):
                    output = io.BytesIO()
                    cpu_before = process.cpu_times()
                    started = time.perf_counter()
                    with wave.open(output, "wb") as wav_output:
                        voice.synthesize_wav(
                            text, wav_output, syn_config=SynthesisConfig(length_scale=1)
                        )
                    elapsed = time.perf_counter() - started
                    cpu_after = process.cpu_times()
                    output.seek(0)
                    with wave.open(output, "rb") as wav_input:
                        duration = wav_input.getnframes() / wav_input.getframerate()
                    records.append(
                        {
                            "language": language,
                            "sample_index": sample_index,
                            "repeat": repeat,
                            "warmup": repeat == 0,
                            "synthesis_seconds": elapsed,
                            "audio_seconds": duration,
                            "rtf": elapsed / duration,
                            "cpu_seconds": (
                                cpu_after.user
                                + cpu_after.system
                                - cpu_before.user
                                - cpu_before.system
                            ),
                            "process_rss_bytes": process.memory_info().rss,
                        }
                    )
        peak[0] = max(peak[0], process.memory_info().rss)
    finally:
        stop.set()
        sampler.join()

    summaries = []
    for language in voices:
        for index in range(len(SAMPLES[language])):
            subset = [
                row
                for row in records
                if row["language"] == language
                and row["sample_index"] == index
                and not row["warmup"]
            ]
            summaries.append(
                {
                    "language": language,
                    "sample_index": index,
                    "audio_seconds_median": statistics.median(
                        row["audio_seconds"] for row in subset
                    ),
                    "synthesis_seconds_median": statistics.median(
                        row["synthesis_seconds"] for row in subset
                    ),
                    "synthesis_seconds_max": max(row["synthesis_seconds"] for row in subset),
                    "cpu_seconds_median": statistics.median(row["cpu_seconds"] for row in subset),
                    "rtf_median": statistics.median(row["rtf"] for row in subset),
                }
            )
    return {
        "status": "MEASURED_TTS_COMPONENT_ONLY",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("piper-tts", "onnxruntime", "psutil", "numpy")
        },
        "cpu_logical_count": psutil.cpu_count(),
        "ram_bytes": psutil.virtual_memory().total,
        "threads": threads,
        "cpu_mem_arena": not disable_arena,
        "repeats": repeats,
        "rss_after_import_bytes": rss_start,
        "sampled_peak_rss_bytes": peak[0],
        "rss_end_bytes": process.memory_info().rss,
        "loads": loads,
        "summary": summaries,
        "records": records,
        "limitations": [
            "Без IMS, ffmpeg и RTP; лимиты Docker задаются внешним запуском.",
            "Оба голоса резидентны; синтез последовательный, как в текущем сервисе.",
            "RSS семплируется каждые 5 мс; краткий пик между отсчётами может быть пропущен.",
            "CPU time включает измерительный поток; выходной WAV существует только в памяти.",
            "Это время полного синтеза, не первая слышимая речь на телефоне.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--disable-arena", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.threads < 1 or args.repeats < 1:
        parser.error("threads и repeats должны быть положительными")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "local"):
        parser.error("Результаты должны находиться в local/")
    settings = read_settings()
    paths = prepare_assets(ROOT / "local/benchmarks/cpu-ai/models/piper", settings)
    report = measure(paths, args.threads, args.repeats, args.disable_arena)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PIPER BENCHMARK: {output}")


if __name__ == "__main__":
    main()
