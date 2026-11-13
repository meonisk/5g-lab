"""scripts/profile/conversation_log.py: числа длинного разговора и журнал по времени."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts/lib"), str(ROOT / "scripts/profile")]
import conversation_log as log  # noqa: E402

# Предложение звучит с 2,0 до 4,0 с от начала WAV.
SENTENCES = [{"speaker": "ue1", "text": "один два", "start_ms": 2000, "end_ms": 4000}]
START = 1000.0  # момент начала WAV по часам стенда


def phrase(**extra):
    base = {"call_ids": ["a"], "first_voice_packet_at": START + 2.0,
            "last_voice_packet_at": START + 4.0, "sentence_ready_at": START + 4.6,
            "ai_started_at": START + 4.6, "stt_processing_ms": 800, "queue_wait_ms": 0,
            "processed_at": START + 5.5, "utterance_end_reason": "silence",
            "audio_duration_seconds": 2.6, "transcript": "один два", "translation": "one two",
            "reply_id": "r1"}  # fmt: skip
    return {**base, **extra}


TTS = {"r1": {"event": "tts_sent", "first_voice_rtp_at": START + 5.8, "rtp_playout_ms": 1500,
              "synthesis_ms": 300}}  # fmt: skip


class ConversationLog(unittest.TestCase):
    def test_word_times_split_sentence_by_letters(self):
        words = log.word_times(SENTENCES[0])
        self.assertEqual([w for w, _ in words], ["один", "два"])
        self.assertTrue(2000 < words[0][1] < 3000 < words[1][1] < 4000)
        self.assertEqual(log.words_between(SENTENCES, 3000, 4000), "два")

    def test_wav_start_from_first_voice_packet(self):
        self.assertAlmostEqual(log.wav_start([phrase()], SENTENCES), START)

    def test_metrics_count_lag_and_accuracy(self):
        data = log.direction_metrics([phrase()], TTS, SENTENCES)
        self.assertEqual(data["lag_by_phrase_ms"], [1800])
        self.assertEqual((data["translated"], data["voiced"], data["interrupted"]), (1, 1, 0))
        self.assertEqual(data["accuracy"], 1.0)
        self.assertEqual(data["tail_s"], 3.3)
        self.assertEqual(log.problems({"ru→en": data}, 0.7), [])

    def test_stages_explain_the_lag(self):
        data = log.direction_metrics([phrase(llm_processing_ms=120)], TTS, SENTENCES)
        self.assertEqual(
            data["stages_ms"], {"pause": 600, "stt": 800, "translation": 120, "synthesis": 300}
        )
        missing = log.direction_metrics([phrase(reply_id=None)], TTS, SENTENCES)
        self.assertEqual(set(missing["stages_ms"].values()), {None})

    def test_untranslated_and_interrupted_are_problems(self):
        interrupted = {"r1": {**TTS["r1"], "event": "tts_interrupted"}}
        data = log.direction_metrics([phrase(), phrase(reply_id=None, translation=None)],
                                     interrupted, SENTENCES)  # fmt: skip
        found = log.problems({"ru→en": data}, 0.7)
        self.assertTrue(any("переведено 1 из 2" in p for p in found))
        self.assertTrue(any("прервана 1" in p for p in found))

    def test_journal_is_ordered_and_names_every_stage(self):
        lines = log.journal(SENTENCES, {"ru→en": ("ue1", [phrase()])}, TTS)
        stamps = [float(line.split()[0]) for line in lines]
        self.assertEqual(stamps, sorted(stamps))
        text = "\n".join(lines)
        for stage in ("говорит", "сервер", "распознано", "переведено", "звучит"):
            self.assertIn(stage, text)
        self.assertIn("через 1800 мс после конца речи", text)
        self.assertIn("слова ≈ «один два»", text)


if __name__ == "__main__":
    unittest.main()
