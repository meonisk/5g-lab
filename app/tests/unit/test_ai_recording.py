"""AI Worker: запись обеих ног перевода в одну сессию и режим record (как у 1004)."""

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/services/ai-worker"))


class Recording(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        token = Path(cls.temp.name) / "token"
        token.write_text("unit-test-token", encoding="ascii")
        env = {}
        for line in (ROOT / "app/config/lab.env").read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key] = value.strip('"')
        env.update(SERVICE_CONTROL_TOKEN_FILE=str(token), VOICE_AGENT_URL="http://localhost")
        cls.environment = patch.dict(os.environ, env)
        cls.environment.start()
        with patch("socket.socket"):
            from ims_ai import (
                api,
                lifecycle,
                runtime,
                segmentation,
                settings,
                transcription,
                utterances,
            )
        cls.lifecycle, cls.runtime, cls.settings = lifecycle, runtime, settings
        cls.segmentation, cls.transcription = segmentation, transcription
        cls.utterances = utterances
        cls.client = api.api.test_client()
        cls.headers = {"Authorization": f"Bearer {runtime.control_token}"}

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temp.cleanup()

    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        for name, value in (
            ("recording_root", self.root),
            ("recording_enabled", True),
            ("transcript_normalization", "raw"),
        ):
            patcher = patch.object(self.settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ("record_legs", "record_sessions", "recordings"):
            getattr(self.runtime, name).clear()

    def register(self, session, legs):
        payload = {"session_call_id": session, "legs": legs}
        return self.client.post("/recordings", json=payload, headers=self.headers)

    def register_pair(self):
        legs = [
            {"call_id": "leg-a", "speaker": "caller"},
            {"call_id": "leg-b", "speaker": "callee"},
        ]
        return self.register("leg-a", legs)

    def turn(self, call_id, mode, transcript, language, stream="s1"):
        event = {"call_ids": [call_id], "source_stream_id": stream}
        result = {
            "service_mode": mode,
            "audio_duration_seconds": 0.02,
            "audio_sha256": "0" * 64,
            "detected_language": language,
        }
        self.transcription.record_transcript(b"\xff" * 160, event, result, transcript, language)

    def session_dir(self, call_id):
        return self.root / hashlib.sha256(call_id.encode()).hexdigest()[:20]

    def transcript_lines(self, call_id):
        text = (self.session_dir(call_id) / "transcript.txt").read_text(encoding="utf-8")
        return text.splitlines()

    def test_register_recording_maps_legs(self):
        self.assertEqual(self.register_pair().status_code, 202)
        self.assertEqual(self.runtime.record_legs["leg-b"]["session_call_id"], "leg-a")
        self.assertEqual(self.runtime.record_sessions["leg-a"], {"leg-a", "leg-b"})

    def test_invalid_recording_is_rejected(self):
        cases = [
            ("leg-a", [{"call_id": "leg-a", "speaker": "agent"}]),
            ("bad id", [{"call_id": "leg-a", "speaker": "caller"}]),
            ("leg-a", [{"call_id": f"leg-{n}", "speaker": "caller"} for n in range(3)]),
        ]
        for session, legs in cases:
            with self.subTest(session=session, legs=len(legs)):
                self.assertEqual(self.register(session, legs).status_code, 400)

    def test_both_legs_write_one_transcript(self):
        self.register_pair()
        self.turn("leg-a", "interpret_ru", "Привет", "ru")
        self.turn("leg-b", "interpret_en", "Hello", "en")
        lines = self.transcript_lines("leg-a")
        self.assertTrue(lines[0].startswith("[caller/ru]"))
        self.assertTrue(lines[1].startswith("[callee/en]"))
        self.assertFalse(self.session_dir("leg-b").exists())

    def test_unregistered_interpreter_leg_is_not_recorded(self):
        self.turn("ru-1", "interpret_ru", "Привет", "ru")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_pair_recording_closes_after_last_leg(self):
        self.register_pair()
        self.turn("leg-a", "interpret_ru", "Привет", "ru")
        self.turn("leg-b", "interpret_en", "Hello", "en")
        self.lifecycle.finalize_call("leg-a")
        self.assertFalse((self.session_dir("leg-a") / "completed.json").exists())
        self.lifecycle.finalize_call("leg-b")
        self.assertTrue((self.session_dir("leg-a") / "completed.json").exists())
        self.assertEqual(self.runtime.record_sessions, {})

    def test_record_mode_labels_two_streams(self):
        self.turn("rec-1", "record", "Привет", "ru", stream="s1")
        self.turn("rec-1", "record", "Hello", "en", stream="s2")
        lines = self.transcript_lines("rec-1")
        self.assertTrue(lines[0].startswith("[speaker_1/ru]"))
        self.assertTrue(lines[1].startswith("[speaker_2/en]"))

    def test_record_mode_is_known_everywhere(self):
        self.assertIn("record", self.settings.service_modes)
        self.assertTrue(self.segmentation.is_dialogue_mode("record"))
        self.assertIn("record", self.lifecycle.FINALIZED_RECORDING_MODES)
        self.assertIsNone(self.utterances.requested_language("record"))

    def test_transcribe_still_records_caller(self):
        self.turn("t-1", "transcribe", "Привет", "ru")
        self.assertTrue(self.transcript_lines("t-1")[0].startswith("[caller/ru]"))


if __name__ == "__main__":
    unittest.main()
