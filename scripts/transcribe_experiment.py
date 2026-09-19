"""Re-transcribe four recorded tracks locally; preserve the original experiment evidence."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACKS = (
    ("input/russian-user-speaks.wav", "ru", "Русский участник: вход"),
    ("input/english-user-speaks.wav", "en", "Английский участник: вход"),
    ("output/russian-user-hears.wav", "ru", "Переводчик → русский участник"),
    ("output/english-user-hears.wav", "en", "Переводчик → английский участник"),
)


def analyze_track(model, experiment, relative, language, speaker):
    import numpy as np

    path = experiment / relative
    with wave.open(str(path), "rb") as source:
        rate, channels, width = source.getframerate(), source.getnchannels(), source.getsampwidth()
        duration = source.getnframes() / rate
        if width != 2:
            raise ValueError(f"Expected PCM16: {relative}")
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
    amplitude = samples.astype(np.float64) / 32768
    segments, _ = model.transcribe(
        str(path),
        language=language,
        beam_size=5,
        vad_filter=True,
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    transcript = []
    for segment in segments:
        transcript.append(
            {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
                "words": [
                    {"start": word.start, "end": word.end, "text": word.word}
                    for word in segment.words or []
                ],
            }
        )
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return {
        "file": relative,
        "speaker": speaker,
        "language": language,
        "sha256": digest,
        "duration_seconds": duration,
        "sample_rate": rate,
        "channels": channels,
        "rms": float(np.sqrt(np.mean(amplitude**2))),
        "nonzero_samples": int(np.count_nonzero(samples)),
        "segments": transcript,
        "time_basis": "seconds from start of this WAV; ASR-estimated boundaries",
    }


def inside_container(experiment):
    from faster_whisper import WhisperModel
    from transcript_timeline import write_reports

    model = WhisperModel(
        os.environ["AI_MODEL_SIZE"],
        device="cpu",
        compute_type="int8",
        download_root="/models",
        revision=os.environ["AI_MODEL_REVISION"],
        local_files_only=True,
        cpu_threads=4,
    )
    result = {
        "method": "posthoc ASR of actual WAV; not historical STT or LLM text",
        "model": os.environ["AI_MODEL_SIZE"],
        "revision": os.environ["AI_MODEL_REVISION"],
        "tracks": [],
    }
    manifest = json.loads((experiment / "manifest.json").read_text(encoding="utf-8-sig"))
    expected_hashes = {entry["path"]: entry["sha256"] for entry in manifest["audio_files"]}
    for relative, language, speaker in TRACKS:
        print(f"Transcribing {relative}", flush=True)
        track = analyze_track(model, experiment, relative, language, speaker)
        if track["sha256"] != expected_hashes.get(relative):
            raise ValueError(f"WAV differs from experiment manifest: {relative}")
        track["manifest_sha256_verified"] = True
        result["tracks"].append(track)
    destination = experiment / "analysis"
    destination.mkdir(exist_ok=True)
    (destination / "transcript.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_reports(experiment, result)
    print("Saved analysis/transcript.json and analysis/timeline.md", flush=True)


def launch(experiment):
    # Reuse the installed runtime and cache; no uploads, downloads or live calls.
    container = json.loads(subprocess.check_output(["docker", "inspect", "lab-ai-worker"]))[0]
    cache = next(
        mount["Name"] for mount in container["Mounts"] if mount["Destination"] == "/models"
    )
    snapshot = json.loads(
        (experiment / "metadata/containers.inspect.json").read_text(encoding="utf-8-sig")
    )
    ai = next(item for item in snapshot if item["Name"] == "/lab-ai-worker")
    config = dict(item.split("=", 1) for item in ai["Config"]["Env"])
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--cpus",
        "4",
        "--memory",
        "3g",
        "--entrypoint",
        "python",
        "--mount",
        f"type=volume,src={cache},dst=/models,readonly",
        "--mount",
        f"type=bind,src={experiment},dst=/experiment",
        "--mount",
        f"type=bind,src={ROOT / 'scripts'},dst=/audit,readonly",
    ]
    if sys.platform.startswith("linux"):
        command.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
    for key in ("AI_MODEL_SIZE", "AI_MODEL_REVISION"):
        command.extend(["-e", f"{key}={config[key]}"])
    command.extend(
        [container["Image"], "/audit/transcribe_experiment.py", "/experiment", "--inside"]
    )
    subprocess.run(command, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    experiment = arguments.experiment.resolve()
    if arguments.inside:
        inside_container(experiment)
    else:
        launch(experiment)


if __name__ == "__main__":
    main()
