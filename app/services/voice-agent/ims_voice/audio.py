"""PCMU codec and local speech synthesis."""

import hashlib
import math
import os
import struct
import subprocess
import tempfile

from . import runtime


def backend_for(voice):
    if runtime.tts_backend == "piper" and voice in runtime.piper_voices:
        return "piper"
    return "espeak-ng"


def ulaw_sample(value):
    value = (~value) & 0xFF
    sign = value & 0x80
    exponent = (value >> 4) & 0x07
    mantissa = value & 0x0F
    sample = ((mantissa << 3) + 0x84) << exponent
    sample -= 0x84
    return -sample if sign else sample


def ulaw_rms(payload):
    if not payload:
        return 0
    return int(math.sqrt(sum(ulaw_sample(value) ** 2 for value in payload) / len(payload)))


def synthesize(text, voice, length_factor=1.0, keep=True):
    """PCMU 8 кГц; length_factor < 1 — речь быстрее (только Piper).

    keep=True — неизменные фразы (приветствие, уведомление): звук хранится в /tmp и
    повторно не синтезируется. Перевод и ответ (keep=False) синтезируются каждый раз:
    задержка услуги — честная, и /tmp не растёт от текстов разговоров.
    """
    if not keep:
        with tempfile.TemporaryDirectory() as folder:
            raw_path = os.path.join(folder, "speech.ulaw")
            render(text, voice, length_factor, raw_path)
            with open(raw_path, "rb") as source:
                return source.read()
    identity = (
        backend_for(voice),
        voice,
        runtime.tts_rate,
        runtime.piper_voices.get(voice),
        length_factor,
        text,
    )
    key = hashlib.sha256(repr(identity).encode()).hexdigest()[:16]
    raw_path = f"/tmp/{key}.ulaw"
    if not os.path.exists(raw_path):
        render(text, voice, length_factor, raw_path)
    with open(raw_path, "rb") as source:
        return source.read()


def render(text, voice, length_factor, raw_path):
    with tempfile.NamedTemporaryFile(suffix=".wav") as wav:
        if backend_for(voice) == "piper":
            from .neural_voice import synthesize_neural

            synthesize_neural(text, voice, wav.name, length_factor)
        else:
            synthesize_espeak(text, voice, wav.name)
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-i",
                wav.name,
                "-ar",
                "8000",
                "-ac",
                "1",
                "-f",
                "mulaw",
                raw_path,
            ],
            check=True,
            timeout=30,
        )


def synthesize_espeak(text, voice, destination):
    subprocess.run(
        [
            "espeak-ng",
            "-v",
            voice,
            "-s",
            str(runtime.tts_rate),
            "-w",
            destination,
            text,
        ],
        check=True,
        timeout=30,
    )


def ulaw_wav(payload: bytes) -> bytes:
    """Обернуть PCMU в WAV (формат 7, G.711 µ-law): так его играет RTPengine play media."""
    fmt = struct.pack("<HHIIHHH", 7, 1, 8000, 8000, 1, 8, 0)
    padding = b"\0" if len(payload) % 2 else b""
    body = (
        b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"fact"
        + struct.pack("<II", 4, len(payload))
        + b"data"
        + struct.pack("<I", len(payload))
        + payload
        + padding
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body
