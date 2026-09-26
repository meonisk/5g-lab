"""Synthetic PCM markers and receiver-side fidelity checks for the plain IMS call."""

import wave

import numpy as np

RATE = 8000
SILENCE_MIN_SECONDS = 8
SILENCE_MAX_RMS = 160
SILENCE_MAX_PEAK = 512


def marker(seed):
    # Deterministic low-band noise gives each direction a distinct time signature.
    rng = np.random.default_rng(seed)
    samples = rng.normal(size=RATE * 4)
    samples = np.convolve(samples, np.ones(5) / 5, mode="same")
    samples *= 7000 / np.max(np.abs(samples))
    return samples.astype("<i2")


def write_marker(path, seed):
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        stream.writeframes(np.tile(marker(seed), 30).tobytes())


def read_pcm(path):
    with wave.open(str(path), "rb") as stream:
        if stream.getsampwidth() != 2 or stream.getnchannels() != 1:
            raise ValueError("receiver recording must be mono signed 16-bit PCM")
        rate = stream.getframerate()
        samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(float)
    if rate != RATE:
        samples = np.interp(
            np.arange(0, len(samples), rate / RATE), np.arange(len(samples)), samples
        )
    return samples


def correlation(received, expected):
    # FFT matched filter; normalization at each candidate window rejects silence.
    received = received.astype(float)
    expected = expected.astype(float)
    n = len(expected)
    if len(received) < n:
        return {"correlation": 0.0, "offset_seconds": None, "minimum_block_correlation": 0.0}
    size = 1 << (len(received) + n - 1).bit_length()
    cross = np.fft.irfft(np.fft.rfft(received, size) * np.fft.rfft(expected[::-1], size), size)
    cross = cross[n - 1 : len(received)]
    sums = np.concatenate(([0.0], np.cumsum(received * received)))
    norms = np.sqrt(np.maximum(sums[n:] - sums[:-n], 0) * np.sum(expected * expected))
    scores = cross / np.maximum(norms, 1)
    offset = int(np.argmax(scores))
    segment = received[offset : offset + n]
    blocks = []
    for start in range(0, n, RATE // 4):
        x, y = segment[start : start + RATE // 4], expected[start : start + RATE // 4]
        blocks.append(float(np.dot(x, y) / max(np.linalg.norm(x) * np.linalg.norm(y), 1)))
    return {
        "correlation": float(scores[offset]),
        "offset_seconds": offset / RATE,
        "minimum_block_correlation": min(blocks),
    }


def verify_receiver(path, expected_seed, self_seed):
    received = read_pcm(path)
    correct = correlation(received, np.tile(marker(expected_seed), 2))
    wrong = correlation(received, np.tile(marker(self_seed), 2))
    passed = correct["correlation"] >= 0.90 and correct["minimum_block_correlation"] >= 0.85
    passed = passed and wrong["correlation"] < 0.20
    return {
        "status": "PASS" if passed else "FAIL",
        "received_seconds": len(received) / RATE,
        "expected_marker": correct,
        "self_marker_correlation": wrong["correlation"],
        "boundary": "receiver PJSUA WAV, 8-second continuous marker; not physical loudspeaker",
    }


def verify_silence(path):
    """Require an intact receiver recording with only PCMU digital noise floor."""
    received = read_pcm(path)
    seconds = len(received) / RATE
    rms = float(np.sqrt(np.mean(received * received))) if len(received) else 0.0
    peak = float(np.max(np.abs(received))) if len(received) else 0.0
    passed = seconds >= SILENCE_MIN_SECONDS and rms <= SILENCE_MAX_RMS and peak <= SILENCE_MAX_PEAK
    return {
        "status": "PASS" if passed else "FAIL",
        "received_seconds": seconds,
        "rms_pcm16": rms,
        "peak_pcm16": peak,
        "boundary": "receiver PJSUA WAV, >=8 seconds at PCMU noise floor; not physical loudspeaker",
    }
