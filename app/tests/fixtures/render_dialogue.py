"""Render scheduled Piper turns inside the voice-agent build image."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path

import onnxruntime
from piper import PiperVoice, SynthesisConfig
from piper.config import PiperConfig

SAMPLE_RATE = 8000
SAMPLE_WIDTH = 2


def load_voice(prefix):
    model_path = os.environ[f"{prefix}_MODEL_PATH"]
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = int(os.environ["PIPER_THREADS"])
    options.inter_op_num_threads = 1
    with open(model_path + ".json", encoding="utf-8") as source:
        config = PiperConfig.from_dict(json.load(source))
    session = onnxruntime.InferenceSession(
        model_path, sess_options=options, providers=["CPUExecutionProvider"]
    )
    return PiperVoice(config=config, session=session)


def speech_bytes(model, text, length_scale):
    with tempfile.TemporaryDirectory() as temporary:
        native_path = Path(temporary) / "native.wav"
        with wave.open(str(native_path), "wb") as destination:
            model.synthesize_wav(
                text, destination, syn_config=SynthesisConfig(length_scale=length_scale)
            )
        return subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(native_path),
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                "1",
                "-f",
                "s16le",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout


def silence(milliseconds):
    return bytes(SAMPLE_RATE * SAMPLE_WIDTH * milliseconds // 1000)


def render_track(name, track, output, models):
    prefix = "PIPER" if track["language"].startswith("ru") else "PIPER_EN"
    model = models.setdefault(prefix, load_voice(prefix))
    chunks = [silence(track["leading_silence_ms"])]
    for index, text in enumerate(track["turns"]):
        scale = float(os.environ[f"{prefix}_LENGTH_SCALE"])
        chunks.append(speech_bytes(model, text, scale))
        if index + 1 < len(track["turns"]):
            chunks.append(silence(track["between_turns_ms"]))
    chunks.append(silence(track["trailing_silence_ms"]))

    path = output / f"{name}-{track['language']}.wav"
    with wave.open(str(path), "wb") as destination:
        destination.setparams((1, SAMPLE_WIDTH, SAMPLE_RATE, 0, "NONE", "not compressed"))
        destination.writeframes(b"".join(chunks))
    content = path.read_bytes()
    return {
        "file": path.name,
        "backend": "piper",
        "model_sha256": os.environ[f"{prefix}_MODEL_SHA256"],
        "language": track["language"],
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def main():
    design_path, output_path = map(Path, sys.argv[1:3])
    design = json.loads(design_path.read_text(encoding="utf-8"))
    output_path.mkdir(parents=True, exist_ok=True)
    models = {}
    tracks = {
        name: render_track(name, track, output_path, models)
        for name, track in design["tracks"].items()
    }
    manifest = {
        "fixture_id": design["fixture_id"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_design": str(design_path),
        "audio_format": design["audio_format"],
        "playback_seconds": design["playback_seconds"],
        "tracks": tracks,
    }
    (output_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Generated Piper dialogue fixture in {output_path}")


if __name__ == "__main__":
    main()
