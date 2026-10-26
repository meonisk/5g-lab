"""Синтетический диалог RU/EN для verify_interpreter.py: два WAV и manifest.

На хосте скрипт запускает сам себя в образе lab-voice-agent (там Piper и голоса
с закреплёнными SHA-256); результат пишется в local/private/interpreter.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path

# Внутри контейнера скрипт лежит в /fixture, корня репозитория там нет:
# пути репозитория нужны только на хосте.
HERE = Path(__file__).resolve()
ROOT = HERE.parents[3] if len(HERE.parents) > 3 else HERE.parent
DESIGN = ROOT / "app/tests/fixtures/interpreter-dialogue-v2.json"
OUTPUT = ROOT / "local/private/interpreter"
SAMPLE_RATE = 8000
SAMPLE_WIDTH = 2


def load_voice(prefix):
    import onnxruntime
    from piper import PiperVoice
    from piper.config import PiperConfig

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
    from piper import SynthesisConfig

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


def render(design_path, output_path):
    """Выполняется внутри lab-voice-agent: синтез и manifest с SHA-256 каждого трека."""
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
        "audio_format": design["audio_format"],
        "playback_seconds": design["playback_seconds"],
        "tracks": tracks,
    }
    (output_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def generate():
    """На хосте: синтез без сети, файлы принадлежат текущему пользователю."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    command = ["docker", "run", "--rm", "--network", "none", "--cpus", "1", "--memory", "512m"]
    command += ["--user", f"{os.getuid()}:{os.getgid()}"]
    command += ["--env-file", str(ROOT / "app/config/lab.env")]
    for source, target, mode in (
        (DESIGN, "/fixture/design.json", ",readonly"),
        (OUTPUT, "/fixture/output", ""),
        (HERE, "/fixture/dialogue.py", ",readonly"),
    ):
        command += ["--mount", f"type=bind,src={source},dst={target}{mode}"]
    # CPU-режимы собирают тот же Voice Agent под другим именем образа.
    images = ("lab-voice-agent", "lab-voice-agent-cpu")
    image = next(
        (
            name
            for name in images
            if not subprocess.run(
                ["docker", "image", "inspect", name], capture_output=True, check=False
            ).returncode
        ),
        images[0],
    )
    command += ["--entrypoint", "python", image, "/fixture/dialogue.py", "--inside"]
    subprocess.run(command, check=True)


def verified_fixture():
    """Возвращает manifest, создавая WAV при первом запуске или смене сценария."""
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    manifest_path = OUTPUT / "manifest.json"
    if not manifest_path.is_file() or (
        json.loads(manifest_path.read_text()).get("fixture_id") != design["fixture_id"]
    ):
        generate()
    manifest = json.loads(manifest_path.read_text())
    for track in manifest["tracks"].values():
        path = OUTPUT / track["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != track["sha256"]:
            raise RuntimeError(f"WAV изменён после генерации: {path.name}; удалите {OUTPUT}")
        with wave.open(str(path), "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 8000):
                raise RuntimeError(f"Неверный формат WAV: {path.name}")
    return manifest


if __name__ == "__main__":
    if sys.argv[1:] == ["--inside"]:
        render(Path("/fixture/design.json"), Path("/fixture/output"))
    else:
        print(json.dumps(verified_fixture()["tracks"], indent=2))
