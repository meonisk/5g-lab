"""A retrospective report must not merge separate turns or alter raw ASR segments."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from transcript_timeline import clock, group_phrases, timestamp


class TranscriptTimeline(unittest.TestCase):
    def test_adjacent_segments_merge_but_separate_turns_do_not(self):
        segments = [
            {"start": 2.0, "end": 3.0, "text": "Hello"},
            {"start": 3.0, "end": 4.0, "text": "world."},
            {"start": 20.0, "end": 21.0, "text": "Next turn."},
        ]
        phrases = group_phrases(segments)
        self.assertEqual(len(phrases), 2)
        self.assertEqual(phrases[0]["text"], "Hello world.")
        self.assertEqual(segments[0]["text"], "Hello")

    def test_utc_origin_and_file_clock_are_explicit(self):
        self.assertEqual(clock(64.21), "01:04.210")
        self.assertEqual(timestamp("2026-09-19T20:28:01Z") - timestamp("2026-09-19T20:28:00Z"), 1)
