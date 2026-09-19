"""PCMU codec and local speech synthesis."""

import hashlib
import math
import os
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


def synthesize(text, voice):
    identity = (
        backend_for(voice),
        voice,
        runtime.tts_rate,
        runtime.piper_voices.get(voice),
        text,
    )
    key = hashlib.sha256(repr(identity).encode()).hexdigest()[:16]
    raw_path = f"/tmp/{key}.ulaw"
    if not os.path.exists(raw_path):
        with tempfile.NamedTemporaryFile(suffix=".wav") as wav:
            if backend_for(voice) == "piper":
                from .neural_voice import synthesize_neural

                synthesize_neural(text, voice, wav.name)
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
    with open(raw_path, "rb") as source:
        return source.read()


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
