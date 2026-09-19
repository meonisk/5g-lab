"""Protect the audio regression: whole phrases, independent calls, and BYE tails."""

import base64
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/services/ai-worker"))


class PhraseBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Synthetic test configuration uses no deployment credentials or model downloads.
        cls.temp = tempfile.TemporaryDirectory()
        token = Path(cls.temp.name) / "token"
        token.write_text("offline-unit-test-token", encoding="ascii")
        env = {}
        for line in (ROOT / "app/config/lab.env").read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key] = value.strip('"')
        env.update(SERVICE_CONTROL_TOKEN_FILE=str(token), VOICE_AGENT_URL="http://localhost")
        cls.environment = patch.dict(os.environ, env)
        cls.environment.start()
        from ims_ai import lifecycle, runtime, segmentation, settings

        cls.lifecycle, cls.runtime = lifecycle, runtime
        cls.segmentation, cls.settings = segmentation, settings

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temp.cleanup()

    def setUp(self):
        for name in (
            "buffers",
            "recordings",
            "conversations",
            "reply_counts",
            "turn_counts",
            "active_calls",
            "pending_utterances",
            "call_locks",
        ):
            getattr(self.runtime, name).clear()

    def event(self, audio, call="test-call", observed=100, mode="bilingual_test"):
        return {
            "call_ids": [call],
            "ssrc": 12,
            "service_mode": mode,
            "direction": "caller_to_core",
            "codec": "PCMU",
            "sample_rate_hz": 8000,
            "observed_at": observed,
            "audio_ulaw_b64": base64.b64encode(audio).decode(),
            "audio_sha256": hashlib.sha256(audio).hexdigest(),
        }

    def test_long_dialogue_phrase_survives_five_seconds(self):
        with patch.object(self.segmentation, "enqueue_utterance") as emitted:
            self.segmentation.process_event(self.event(b"\x00" * 8000 * 8))
            emitted.assert_not_called()
            self.segmentation.process_event(self.event(b"\xff" * 8000 * 2, observed=100.25))
            self.assertEqual(emitted.call_count, 1)
            self.assertEqual(emitted.call_args.args[3], "silence")
            self.assertGreater(len(emitted.call_args.args[0]), 8000 * 8)

    def test_suppressed_rtp_gap_finishes_previous_phrase(self):
        with patch.object(self.segmentation, "enqueue_utterance") as emitted:
            self.segmentation.process_event(self.event(b"\x00" * 8000))
            self.segmentation.process_event(self.event(b"\x00" * 8000, observed=110))
            self.assertEqual(emitted.call_count, 1)
            self.assertEqual(emitted.call_args.args[3], "stream-gap")

    def test_call_id_prevents_ssrc_reuse_from_mixing_calls(self):
        with patch.object(self.segmentation, "enqueue_utterance") as emitted:
            self.segmentation.process_event(self.event(b"\x00" * 8000, call="one"))
            self.segmentation.process_event(self.event(b"\x00" * 8000, call="two", observed=110))
            emitted.assert_not_called()
            self.assertEqual(len(self.runtime.buffers), 2)

    def test_bye_flushes_tail_and_removes_call_state(self):
        self.segmentation.process_event(self.event(b"\x00" * 8000))
        with patch.object(self.lifecycle, "enqueue_utterance") as emitted:
            self.lifecycle.finalize_call("test-call")
            self.assertEqual(emitted.call_count, 1)
            self.assertEqual(emitted.call_args.args[3], "call-ended")
            self.assertFalse(self.runtime.buffers)

    def test_invalid_audio_digest_is_rejected(self):
        event = self.event(b"\x00" * 8000)
        event["audio_sha256"] = "invalid"
        self.segmentation.process_event(event)
        self.assertFalse(self.runtime.buffers)

    def test_idle_rtp_finishes_without_next_sentence(self):
        with patch.object(self.segmentation, "enqueue_utterance") as emitted:
            self.segmentation.process_event(self.event(b"\x00" * 8000))
            state = next(iter(self.runtime.buffers.values()))
            self.segmentation.flush_idle_streams(state["last_seen"] + 0.25)
            emitted.assert_not_called()
            self.segmentation.flush_idle_streams(state["last_seen"] + 2)
            self.assertEqual(emitted.call_count, 1)
            self.assertEqual(emitted.call_args.args[3], "idle-gap")
            self.segmentation.flush_idle_streams(state["last_seen"] + 3)
            self.assertEqual(emitted.call_count, 1)

    def test_short_limit_remains_for_interactive_agent(self):
        with patch.object(self.segmentation, "enqueue_utterance") as emitted:
            self.segmentation.process_event(self.event(b"\x00" * 8000 * 6, mode="assistant"))
            self.assertEqual(emitted.call_count, 1)
            self.assertEqual(emitted.call_args.args[3], "maximum-duration")

    def test_last_voice_timestamp_excludes_trailing_silence(self):
        event = self.event(b"\x00" * 8000 + b"\xff" * 8000)
        event["audio_frame_received_at"] = [100 + index * 0.02 for index in range(100)]
        with patch.object(self.segmentation, "enqueue_utterance") as emitted:
            self.segmentation.process_event(event)
            self.assertAlmostEqual(emitted.call_args.args[1]["last_voice_packet_at"], 100.98)

    def test_llm_requests_preserve_residency_and_bounded_context(self):
        from ims_ai import llm

        with patch.object(llm, "request_json", return_value={"message": {"content": "OK"}}) as api:
            text, _ = llm.chat([{"role": "user", "content": "Test"}], 8)
            self.assertEqual(text, "OK")
            payload = api.call_args.kwargs["payload"]
            self.assertEqual(payload["keep_alive"], -1)
            self.assertEqual(payload["options"]["num_ctx"], 2048)

    def test_streaming_waits_for_agreement_and_releases_final_tail(self):
        from ims_ai.streaming import stable_prefix

        self.assertEqual(stable_prefix("", "Hello Alex"), [])
        self.assertEqual(stable_prefix("Hello Alex", "Hello Alex I hear you"), ["Hello", "Alex"])
        self.assertEqual(stable_prefix("Hello Alice", "Hello Alex I hear you"), ["Hello"])
        self.assertEqual(stable_prefix("Hello", "Hello Alex", final=True), ["Hello", "Alex"])

    def test_partial_snapshot_does_not_cut_audio_or_reset_phrase(self):
        with (
            patch.object(self.settings, "streaming_enabled", True),
            patch.object(self.segmentation, "enqueue_utterance") as emitted,
        ):
            self.segmentation.process_event(self.event(b"\x00" * 8000, mode="interpret_ru"))
            self.assertEqual(emitted.call_args.args[3], "stream-partial")
            state = next(iter(self.runtime.buffers.values()))
            self.assertEqual(len(state["utterance"]), 8000)
            self.assertTrue(state["in_speech"])


if __name__ == "__main__":
    unittest.main()
