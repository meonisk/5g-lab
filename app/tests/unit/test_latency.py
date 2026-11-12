"""scripts/lib/latency.py: статистика и этапы перевода из событий сервисов без стенда."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/lib"))
import latency  # noqa: E402

EVENT = {
    "last_voice_packet_at": 100.0,
    "sentence_ready_at": 100.72,
    "sentence_assembly_ms": 4200.04,
    "queue_wait_ms": 3.26,
    "stt_processing_ms": 3600.0,
    "llm_processing_ms": 250.55,
}
TTS = {"first_voice_rtp_at": 104.9, "synthesis_ms": 300.0}


class Statistics(unittest.TestCase):
    def test_percentile_interpolates_between_ranks(self):
        self.assertEqual(latency.percentile([1, 2, 3, 4, 5], 50), 3)
        self.assertAlmostEqual(latency.percentile([1, 2, 3, 4, 5], 95), 4.8)
        self.assertEqual(latency.percentile([7], 95), 7)
        self.assertIsNone(latency.percentile([], 95))

    def test_describe_gives_mean_and_p95(self):
        row = latency.describe([1.0, 2.0, 3.0, None, 4.0])
        self.assertEqual(row, {"n": 4, "mean": 2.5, "p95": 3.85, "max": 4.0})
        self.assertIsNone(latency.describe([]))

    def test_summary_keeps_bench_shape(self):
        self.assertEqual(
            latency.summary([3.0, 1.0, 2.0]), {"n": 3, "median": 2.0, "min": 1.0, "max": 3.0}
        )


class Stages(unittest.TestCase):
    def test_stage_row_from_worker_and_agent_events(self):
        row = latency.stage_row(EVENT, TTS)
        self.assertEqual(
            row,
            {
                "speech_end_to_reply_rtp_ms": 4900.0,
                "speech_plus_pause_ms": 4200.0,
                "queue_wait_ms": 3.3,
                "stt_ms": 3600.0,
                "translation_ms": 250.6,
                "tts_synthesis_ms": 300.0,
            },
        )

    def test_missing_durations_are_zero_not_errors(self):
        row = latency.stage_row({"last_voice_packet_at": 1.0, "sentence_assembly_ms": None},
                                {"first_voice_rtp_at": 2.0})  # fmt: skip
        self.assertEqual(row["speech_plus_pause_ms"], 0)
        self.assertEqual(row["speech_end_to_reply_rtp_ms"], 1000.0)

    def test_vad_wait_is_pause_after_last_voice_packet(self):
        self.assertEqual(latency.vad_wait_ms(EVENT), 720.0)
        self.assertIsNone(latency.vad_wait_ms({"sentence_ready_at": 1.0}))


class Conference(unittest.TestCase):
    def test_player_and_last_call_port(self):
        text = (
            "Conference ports:\n"
            "  Port #00[16KHz/10ms/1] Master/sound\n"
            "  Port #01[ 8KHz/20ms/1] /tmp/bench-pause.wav\n"
            "Port #02[ 8KHz/20ms/1] sip:1003@example\n"
            "  Port #04[ 8KHz/20ms/1] sip:1002@example\n"
        )
        self.assertEqual(latency.conference_ports(text), ("1", "4"))
        self.assertEqual(latency.conference_ports("no ports"), (None, None))


if __name__ == "__main__":
    unittest.main()
