"""Negative media predicate requires long, genuinely quiet receiver PCM."""

import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/tests/integration"))
from baseline_audio import RATE, marker, verify_receiver, verify_silence


def write_wav(path, samples):
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        stream.writeframes(np.asarray(samples, dtype="<i2").tobytes())


class VerifySilenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "receiver.wav"

    def test_opposite_marker_survives_odd_delay_and_gain(self):
        samples = np.concatenate([np.zeros(7001), np.tile(marker(2), 2) * 0.6])
        write_wav(self.path, samples)
        result = verify_receiver(self.path, 2, 1)
        self.assertEqual(result["status"], "PASS")
        self.assertGreater(result["expected_marker"]["correlation"], 0.99)
        self.assertEqual(verify_receiver(self.path, 1, 2)["status"], "FAIL")

    def test_partial_audio_and_silence_cannot_pass(self):
        for samples in (np.zeros(RATE * 10), np.concatenate([marker(2), np.zeros(RATE * 6)])):
            with self.subTest(samples=len(samples)):
                write_wav(self.path, samples)
                self.assertEqual(verify_receiver(self.path, 2, 1)["status"], "FAIL")

    def test_pcmu_noise_floor_passes(self):
        write_wav(self.path, np.full(RATE * 9, 8))
        result = verify_silence(self.path)
        self.assertEqual(result["status"], "PASS")

    def test_wrong_source_or_self_audio_fails(self):
        write_wav(self.path, np.tile(marker(2), 3))
        result = verify_silence(self.path)
        self.assertEqual(result["status"], "FAIL")
        self.assertGreater(result["rms_pcm16"], 160)

    def test_short_quiet_recording_fails(self):
        write_wav(self.path, np.zeros(RATE * 4))
        result = verify_silence(self.path)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["received_seconds"], 4)

    def test_sparse_loud_spike_fails_peak_threshold(self):
        samples = np.zeros(RATE * 9)
        samples[100] = 2000
        write_wav(self.path, samples)
        self.assertEqual(verify_silence(self.path)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
