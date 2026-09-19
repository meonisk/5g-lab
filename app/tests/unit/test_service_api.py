"""HTTP contracts and voice-queue lifecycle without Docker, models, or real audio."""

import importlib
import os
import queue
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from lab_common.http import create_api, json_object

ROOT = Path(__file__).resolve().parents[3]


class ServiceApi(unittest.TestCase):
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
        env.update(
            SERVICE_CONTROL_TOKEN_FILE=str(token),
            AI_WORKER_URL="http://localhost",
            VOICE_AGENT_URL="http://localhost",
        )
        cls.environment = patch.dict(os.environ, env)
        cls.environment.start()
        cls.modules = {}
        for service, package in (
            ("ai-worker", "ims_ai"),
            ("media-adapter", "ims_media"),
            ("voice-agent", "ims_voice"),
        ):
            sys.path.insert(0, str(ROOT / "app/services" / service))
            # Importing runtime must not bind the test machine to a lab address.
            with patch("socket.socket"):
                cls.modules[package] = importlib.import_module(package + ".api")

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temp.cleanup()

    def test_every_service_requires_token(self):
        paths = {"ims_ai": "/events", "ims_media": "/sessions", "ims_voice": "/status"}
        for name, module in self.modules.items():
            with self.subTest(service=name):
                client = module.api.test_client()
                self.assertEqual(client.get(paths[name]).status_code, 401)
                headers = {"Authorization": f"Bearer {module.runtime.control_token}"}
                self.assertEqual(client.get(paths[name], headers=headers).status_code, 200)

    def test_interpreter_keeps_translation_during_subscriber_speech(self):
        media = importlib.import_module("ims_voice.media")
        for mode in ("interpret_ru", "interpret_en", "assistant"):
            with self.subTest(mode=mode):
                call = {
                    "received_packets": 0,
                    "service_mode": mode,
                    "tts_active": True,
                    "tts_generation": 1,
                }
                media.update_call_from_audio(call, media.runtime.vad_rms + 1, 123.0)
                expected_generation = 2 if mode == "assistant" else 1
                self.assertEqual(call["tts_generation"], expected_generation)
                self.assertTrue(call["speech_seen"])

    def test_json_rejects_arrays_malformed_and_oversized_bodies(self):
        app = create_api("test-json", "token", max_body=32)

        @app.post("/data")
        def data():
            return json_object()

        client = app.test_client()
        headers = {"Authorization": "Bearer token"}
        for payload, expected in (("[]", 400), ("{", 413), ("{oops", 400), ("x" * 33, 413)):
            self.assertEqual(
                client.post("/data", data=payload, headers=headers).status_code, expected
            )

    def test_full_media_queue_returns_429(self):
        module = self.modules["ims_ai"]
        pending = queue.Queue(maxsize=1)
        pending.put({})
        with patch.object(module.runtime, "work", pending):
            response = module.api.test_client().post(
                "/observe",
                json={"packets": 1},
                headers={"Authorization": f"Bearer {module.runtime.control_token}"},
            )
        self.assertEqual(response.status_code, 429)

    def test_audio_cannot_inject_call_cleanup(self):
        module = self.modules["ims_ai"]
        response = module.api.test_client().post(
            "/observe",
            json={"control": "end_call", "call_id": "another-call"},
            headers={"Authorization": f"Bearer {module.runtime.control_token}"},
        )
        self.assertEqual(response.status_code, 400)

    def test_duplicate_call_creates_only_one_playback_worker(self):
        from ims_voice import calls, runtime

        runtime.calls.clear()
        runtime.reply_queues.clear()
        with patch.object(calls.threading, "Thread") as thread:
            for _ in range(2):
                self.assertTrue(calls.start_call("same-call", "127.0.0.1", 4000, "translate"))
            self.assertEqual(thread.call_count, 1)
            self.assertEqual(runtime.reply_queues["same-call"].qsize(), 1)
        calls.end_call("same-call")

    def test_full_playback_queue_can_be_closed(self):
        from ims_voice import calls, media, runtime

        pending = queue.Queue(maxsize=1)
        pending.put(("text", "test", "ru", None))
        runtime.calls["full-call"] = {"received_packets": 0}
        runtime.reply_queues["full-call"] = pending
        calls.end_call("full-call")
        with patch.object(media, "send_audio") as send:
            worker = threading.Thread(target=media.play_queued_audio, args=("full-call", pending))
            worker.start()
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive())
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
