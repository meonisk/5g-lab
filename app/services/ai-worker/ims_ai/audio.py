"""Decode the fixed PCMU/8000 media contract into PCM and measure frame energy."""

from __future__ import annotations

import numpy as np


def ulaw_sample(value):
    value = (~value) & 0xFF
    sign = value & 0x80
    exponent = (value >> 4) & 0x07
    mantissa = value & 0x0F
    sample = ((mantissa << 3) + 0x84) << exponent
    sample -= 0x84
    return -sample if sign else sample


ULAW_TABLE = np.array([ulaw_sample(value) for value in range(256)], dtype=np.int16)


def decode_pcm8(ulaw):
    return ULAW_TABLE[np.frombuffer(ulaw, dtype=np.uint8)]


def decode_audio(ulaw):
    pcm8 = decode_pcm8(ulaw)
    pcm16 = np.repeat(pcm8, 2)
    return pcm16.astype(np.float32) / 32768.0


def frame_rms(ulaw):
    pcm = decode_pcm8(ulaw).astype(np.float64)
    return int(np.sqrt(np.mean(np.square(pcm)))) if len(pcm) else 0
