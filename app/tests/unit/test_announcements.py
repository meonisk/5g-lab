"""Уведомление о записи: WAV µ-law от Voice Agent и команда play media в RTPengine."""

import base64
import importlib
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


class FakeSocket:
    """NG-сокет RTPengine: отвечает тем же cookie, что пришёл в запросе."""

    def __init__(self, reply=b"d6:result2:oke"):
        self.sent, self.reply = [], reply

    def settimeout(self, value):
        return None

    def sendto(self, data, address):
        self.sent.append((data, address))

    def recv(self, size):
        return self.sent[-1][0].split(b" ", 1)[0] + b" " + self.reply

    def close(self):
        return None


class Announcements(unittest.TestCase):
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
        for service in ("voice-agent", "media-adapter"):
            sys.path.insert(0, str(ROOT / "app/services" / service))
        with patch("socket.socket"):
            cls.voice_api = importlib.import_module("ims_voice.api")
            cls.audio = importlib.import_module("ims_voice.audio")
            cls.media_api = importlib.import_module("ims_media.api")
            cls.rtpengine = importlib.import_module("ims_media.rtpengine")
        cls.voice = cls.voice_api.api.test_client()
        cls.media = cls.media_api.api.test_client()
        cls.headers = {"Authorization": f"Bearer {cls.voice_api.runtime.control_token}"}
        cls.tts_voice = cls.voice_api.runtime.tts_voice

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temp.cleanup()

    def test_ulaw_wav_header(self):
        wav = self.audio.ulaw_wav(b"\x7f" * 10)
        self.assertEqual((wav[:4], wav[8:12], wav[12:16]), (b"RIFF", b"WAVE", b"fmt "))
        self.assertEqual(struct.unpack("<HHIIHH", wav[20:36]), (7, 1, 8000, 8000, 1, 8))
        self.assertEqual(struct.unpack("<I", wav[4:8])[0], len(wav) - 8)
        self.assertTrue(wav.endswith(b"data" + struct.pack("<I", 10) + b"\x7f" * 10))

    def test_announcement_returns_wav(self):
        with patch.object(self.voice_api, "synthesize", return_value=b"\xff" * 800) as tts:
            response = self.voice.post(
                "/announcements",
                json={"text": "Внимание", "voice": self.tts_voice},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        wav = base64.b64decode(response.get_json()["wav_base64"])
        self.assertEqual(wav[:4], b"RIFF")
        tts.assert_called_once_with("Внимание", self.tts_voice)

    def test_long_announcement_is_rejected(self):
        too_long = b"\xff" * (self.voice_api.runtime.announcement_max_bytes + 1)
        with patch.object(self.voice_api, "synthesize", return_value=too_long):
            response = self.voice.post(
                "/announcements", json={"text": "Внимание"}, headers=self.headers
            )
        self.assertEqual(response.status_code, 413)

    def test_unknown_voice_is_rejected(self):
        response = self.voice.post(
            "/announcements", json={"text": "Внимание", "voice": "xx"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 400)

    def test_reply_accepts_announcement_reason(self):
        self.voice_api.runtime.calls["ann-1"] = {}
        self.addCleanup(self.voice_api.runtime.calls.pop, "ann-1", None)
        with patch.object(self.voice_api, "enqueue_audio", return_value=True) as enqueue:
            response = self.voice.post(
                "/calls/ann-1/reply",
                json={"text": "Внимание", "voice": self.tts_voice, "reason": "announcement"},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 202)
        enqueue.assert_called_once_with("ann-1", "Внимание", "announcement", self.tts_voice, None)

    def test_reply_rejects_unknown_reason(self):
        self.voice_api.runtime.calls["ann-2"] = {}
        self.addCleanup(self.voice_api.runtime.calls.pop, "ann-2", None)
        response = self.voice.post(
            "/calls/ann-2/reply",
            json={"text": "Внимание", "reason": "greeting"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_encode_matches_decoder(self):
        encoded = self.rtpengine._encode({"command": "play media", "blob": b"ab", "n": 3})
        decoded, end = self.rtpengine._decode(encoded)
        self.assertEqual(end, len(encoded))
        self.assertEqual(decoded, {b"blob": b"ab", b"command": b"play media", b"n": 3})

    def test_command_checks_cookie_and_result(self):
        fake = FakeSocket()
        with patch.object(self.rtpengine.socket, "socket", return_value=fake):
            self.assertEqual(self.rtpengine._command({"command": "ping"}), {b"result": b"ok"})
        data, address = fake.sent[0]
        self.assertTrue(data.endswith(b" d7:command4:pinge"))
        runtime = self.rtpengine.runtime
        self.assertEqual(address, (runtime.rtpengine_ip, runtime.rtpengine_ng_port))
        failing = FakeSocket(reply=b"d6:result5:errore")
        with patch.object(self.rtpengine.socket, "socket", return_value=failing):
            with self.assertRaises(ValueError):
                self.rtpengine._command({"command": "ping"})

    def test_play_media_command(self):
        reply = {b"result": b"ok", b"duration": 2000}
        with patch.object(self.rtpengine, "_command", return_value=reply) as command:
            self.assertEqual(self.rtpengine.play_media("c1", "fa1", b"RIFF"), 2000)
        command.assert_called_once_with(
            {"command": "play media", "call-id": "c1", "from-tag": "fa1", "blob": b"RIFF"}
        )

    def test_announce_plays_to_each_party(self):
        parties = [
            {"tag": "fa1", "text": "Внимание", "voice": "ru"},
            {"tag": "tb1", "text": "Attention", "voice": "en-us"},
        ]
        with (
            patch.object(self.media_api, "fetch_announcement", return_value=b"RIFFwav"),
            patch.object(self.media_api, "play_media") as play,
        ):
            response = self.media.post(
                "/sessions/c1/announce", json={"parties": parties}, headers=self.headers
            )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            [call.args for call in play.call_args_list],
            [("c1", "fa1", b"RIFFwav"), ("c1", "tb1", b"RIFFwav")],
        )

    def test_announce_failure_is_502(self):
        parties = [{"tag": "fa1", "text": "Внимание", "voice": "ru"}]
        with (
            patch.object(self.media_api, "fetch_announcement", return_value=b"RIFFwav"),
            patch.object(self.media_api, "play_media", side_effect=ValueError("rtpengine")),
        ):
            response = self.media.post(
                "/sessions/c2/announce", json={"parties": parties}, headers=self.headers
            )
        self.assertEqual(response.status_code, 502)

    def test_announce_rejects_bad_tag(self):
        parties = [{"tag": "bad tag", "text": "Внимание", "voice": "ru"}]
        response = self.media.post(
            "/sessions/c3/announce", json={"parties": parties}, headers=self.headers
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
