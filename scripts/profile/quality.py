"""Качество распознавания (1 − WER по словам) и звук фраз в контракте стенда PCMU/8000.

WER считается после нормализации регистра, «ё» и пунктуации. Фразы перебора кодируются
в G.711 μ-law 8 кГц, как их получает AI Worker из RTP, — на хосте, без audioop и numpy.
"""

import re
import struct
import wave

WORD = re.compile(r"[^\W_]+")
BIAS, CLIP = 0x84, 32635
SAMPLE_RATE = 8000


def normalize(text):
    return WORD.findall(text.casefold().replace("ё", "е"))


def edit_distance(reference, hypothesis):
    """Расстояние Левенштейна по словам: замены, вставки, удаления."""
    previous = list(range(len(hypothesis) + 1))
    for i, word in enumerate(reference, 1):
        current = [i]
        for j, other in enumerate(hypothesis, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (word != other)))  # fmt: skip
        previous = current
    return previous[-1]


def wer(reference, hypothesis):
    words, heard = normalize(reference), normalize(hypothesis)
    if not words:
        return 0.0 if not heard else 1.0
    return edit_distance(words, heard) / len(words)


def accuracy(reference, hypothesis):
    """Доля совпавших слов: 1 − WER, не меньше нуля (вставки не уводят в минус)."""
    return max(0.0, 1.0 - wer(reference, hypothesis))


def ulaw_byte(sample):
    """G.711 μ-law одного 16-битного отсчёта."""
    sign = 0x80 if sample < 0 else 0
    magnitude = min(abs(sample), CLIP) + BIAS
    exponent = 7
    while exponent and not magnitude & (0x4000 >> (7 - exponent)):
        exponent -= 1
    mantissa = (magnitude >> (exponent + 3)) & 0x0F
    return ~(sign | exponent << 4 | mantissa) & 0xFF


def resample(samples, source_rate, target_rate):
    """Линейная интерполяция; для речи 22/16 -> 8 кГц этого достаточно для STT."""
    if source_rate == target_rate:
        return list(samples)
    count = round(len(samples) * target_rate / source_rate)
    step, last = source_rate / target_rate, len(samples) - 1
    result = []
    for index in range(count):
        position = index * step
        low = min(int(position), last)
        high = min(low + 1, last)
        fraction = position - int(position) if low < last else 0
        result.append(round(samples[low] + (samples[high] - samples[low]) * fraction))
    return result


def wav_to_pcmu(path):
    """WAV PCM16 (моно или стерео) -> (байты PCMU 8 кГц, длительность в секундах)."""
    with wave.open(str(path), "rb") as source:
        channels, width, rate = source.getnchannels(), source.getsampwidth(), source.getframerate()
        frames = source.readframes(source.getnframes())
    if width != 2:
        raise ValueError(f"{path}: нужен PCM 16 бит, а не {width * 8}")
    values = struct.unpack(f"<{len(frames) // 2}h", frames)
    mono = [sum(values[i : i + channels]) // channels for i in range(0, len(values), channels)]
    samples = resample(mono, rate, SAMPLE_RATE)
    return bytes(ulaw_byte(sample) for sample in samples), len(samples) / SAMPLE_RATE
