"""scripts/profile/quality.py: WER по словам и подготовка PCMU 8 кГц без стенда."""

import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts/lib"), str(ROOT / "scripts/profile")]
import quality  # noqa: E402


def ulaw_decode(value):
    """G.711 μ-law, как ims_ai.audio.ulaw_sample в AI Worker."""
    value = (~value) & 0xFF
    sign, exponent, mantissa = value & 0x80, (value >> 4) & 0x07, value & 0x0F
    sample = (((mantissa << 3) + 0x84) << exponent) - 0x84
    return -sample if sign else sample


class Words(unittest.TestCase):
    def test_normalize_case_punctuation_and_yo(self):
        self.assertEqual(
            quality.normalize("Привет, локальный  агент! Ёж — «да»"),
            ["привет", "локальный", "агент", "еж", "да"],
        )

    def test_word_error_rate(self):
        self.assertEqual(quality.wer("a b c d", "a x c"), 0.5)
        self.assertEqual(quality.wer("Добрый день.", "добрый день"), 0.0)
        self.assertEqual(quality.wer("", ""), 0.0)
        self.assertEqual(quality.wer("", "лишнее"), 1.0)

    def test_accuracy_is_one_minus_wer_not_below_zero(self):
        self.assertEqual(quality.accuracy("a b c d", "a x c"), 0.5)
        self.assertEqual(quality.accuracy("a", "x y z"), 0.0)


class Audio(unittest.TestCase):
    def test_ulaw_round_trip_within_quantization(self):
        self.assertEqual(quality.ulaw_byte(0), 0xFF)
        for sample in (0, 50, -50, 1000, -1000, 12000, -32768, 32767):
            decoded = ulaw_decode(quality.ulaw_byte(sample))
            self.assertLessEqual(abs(decoded - sample), max(16, abs(sample) // 16), sample)

    def test_linear_resample(self):
        self.assertEqual(quality.resample([0, 2, 4, 6], 16000, 8000), [0, 4])
        self.assertEqual(quality.resample([0, 10], 8000, 16000), [0, 5, 10, 10])
        self.assertEqual(quality.resample([1, 2, 3], 8000, 8000), [1, 2, 3])

    def test_wav_to_pcmu_8k(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "phrase.wav"
            with wave.open(str(path), "wb") as target:
                target.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                target.writeframes(struct.pack("<4h", 0, 1000, -1000, 0))
            pcmu, seconds = quality.wav_to_pcmu(path)
        self.assertEqual(len(pcmu), 2)
        self.assertEqual(pcmu[0], 0xFF)
        self.assertEqual(seconds, 0.00025)


if __name__ == "__main__":
    unittest.main()
