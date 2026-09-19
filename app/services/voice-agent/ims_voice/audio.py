"""PCMU codec and local speech synthesis."""

import hashlib
import math
import os
import subprocess
import tempfile

from . import runtime


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
    key = hashlib.sha256(f"{voice}\0{runtime.tts_rate}\0{text}".encode()).hexdigest()[:16]
    raw_path = f"/tmp/{key}.ulaw"
    if not os.path.exists(raw_path):
        with tempfile.NamedTemporaryFile(suffix=".wav") as wav:
            subprocess.run(
                [
                    "espeak-ng",
                    "-v",
                    voice,
                    "-s",
                    str(runtime.tts_rate),
                    "-w",
                    wav.name,
                    text,
                ],
                check=True,
                timeout=30,
            )
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
