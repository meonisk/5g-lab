"""Синтетический диалог RU/EN для verify_interpreter.py: два WAV и manifest.

phrase_wavs() — отдельные русские фразы тем же голосом для профилирования;
conversation_wavs() — длинный разговор в обычном темпе (scripts/profile/conversation.py).

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
CONVERSATION = ROOT / "app/tests/fixtures/conversation-long-v1.json"
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


def render_phrases(texts_path, output_path):
    """Выполняется внутри lab-voice-agent: p1.wav, p2.wav... — по фразе, 0,5 с тишины по краям."""
    texts = json.loads(texts_path.read_text(encoding="utf-8"))
    model = load_voice("PIPER")
    scale = float(os.environ["PIPER_LENGTH_SCALE"])
    for number, text in enumerate(texts, 1):
        with wave.open(str(output_path / f"p{number}.wav"), "wb") as destination:
            destination.setparams((1, SAMPLE_WIDTH, SAMPLE_RATE, 0, "NONE", "not compressed"))
            destination.writeframes(silence(500) + speech_bytes(model, text, scale) + silence(500))


def render_conversation(design_path, output_path):
    """Выполняется внутри lab-voice-agent: общий таймлайн двух собеседников.

    conversation-ue1.wav и conversation-ue2.wav одной длины: пока говорит один, у
    другого тишина. timeline.json — начало и конец каждого предложения в мс от начала WAV.
    """
    design = json.loads(design_path.read_text(encoding="utf-8"))
    per_ms = SAMPLE_RATE * SAMPLE_WIDTH // 1000
    models, sentences = {}, []
    tracks = {name: bytearray() for name in design["speakers"]}
    cursor = design["leading_silence_ms"]
    for turn in design["turns"]:
        language = design["speakers"][turn["speaker"]]
        prefix = "PIPER" if language.startswith("ru") else "PIPER_EN"
        model = models.setdefault(prefix, load_voice(prefix))
        scale = float(os.environ[f"{prefix}_LENGTH_SCALE"])
        track = tracks[turn["speaker"]]
        track.extend(silence(cursor - len(track) // per_ms))
        for index, text in enumerate(turn["sentences"]):
            if index:
                track.extend(silence(design["sentence_pause_ms"]))
            start = len(track) // per_ms
            track.extend(speech_bytes(model, text, scale))
            sentences.append({"speaker": turn["speaker"], "language": language, "text": text,
                              "start_ms": start, "end_ms": len(track) // per_ms})  # fmt: skip
        cursor = len(track) // per_ms + design["turn_gap_ms"]
    duration = cursor - design["turn_gap_ms"] + design["trailing_silence_ms"]
    for name, track in tracks.items():
        track.extend(silence(duration - len(track) // per_ms))
        with wave.open(str(output_path / f"conversation-{name}.wav"), "wb") as destination:
            destination.setparams((1, SAMPLE_WIDTH, SAMPLE_RATE, 0, "NONE", "not compressed"))
            destination.writeframes(bytes(track))
    timeline = {"fixture_id": design["fixture_id"], "duration_ms": duration, "sentences": sentences}
    (output_path / "timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_inside(source, output, mode):
    """На хосте: синтез в образе Voice Agent без сети, файлы принадлежат текущему пользователю."""
    output.mkdir(parents=True, exist_ok=True)
    command = ["docker", "run", "--rm", "--network", "none", "--cpus", "1", "--memory", "512m"]
    command += ["--user", f"{os.getuid()}:{os.getgid()}"]
    command += ["--env-file", str(ROOT / "app/config/lab.env")]
    for path, target, readonly in (
        (source, "/fixture/design.json", ",readonly"),
        (output, "/fixture/output", ""),
        (HERE, "/fixture/dialogue.py", ",readonly"),
    ):
        command += ["--mount", f"type=bind,src={path},dst={target}{readonly}"]
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
    command += ["--entrypoint", "python", image, "/fixture/dialogue.py", mode]
    subprocess.run(command, check=True, timeout=600)


def generate():
    run_inside(DESIGN, OUTPUT, "--inside")


def phrase_wavs(texts, folder):
    """Русские фразы голосом Piper (как реплики диалога): WAV PCM16 8 кГц folder/p1.wav..."""
    folder = Path(folder).resolve()  # docker монтирует только абсолютные пути
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "phrases.json"
    source.write_text(json.dumps(list(texts), ensure_ascii=False), encoding="utf-8")
    run_inside(source, folder, "--phrases")
    return [folder / f"p{number}.wav" for number in range(1, len(texts) + 1)]


def conversation_wavs(folder):
    """Длинный разговор голосами Piper в folder: два WAV и timeline.json (его и возвращает)."""
    folder = Path(folder).resolve()
    run_inside(CONVERSATION, folder, "--conversation")
    return json.loads((folder / "timeline.json").read_text(encoding="utf-8"))


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
    elif sys.argv[1:] == ["--phrases"]:
        render_phrases(Path("/fixture/design.json"), Path("/fixture/output"))
    elif sys.argv[1:] == ["--conversation"]:
        render_conversation(Path("/fixture/design.json"), Path("/fixture/output"))
    else:
        print(json.dumps(verified_fixture()["tracks"], indent=2))
