"""Per-call RTP attribution rules for the Media Adapter."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/services/media-adapter"))


class MediaRouting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        token = Path(cls.temp.name) / "token"
        token.write_text("offline-unit-test-token", encoding="ascii")
        env = {}
        for line in (ROOT / "app/config/lab.env").read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key] = value.strip('"')
        env.update(
            SERVICE_CONTROL_TOKEN_FILE=str(token),
            AI_WORKER_URL="http://localhost:8092",
        )
        cls.environment = patch.dict(os.environ, env)
        cls.environment.start()
        from ims_media import rtpengine
        from ims_media.publish import match_session

        cls.match_session = staticmethod(match_session)
        cls.rtpengine = rtpengine

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temp.cleanup()

    def test_forwarded_stream_matches_exact_call_port(self):
        active = {
            "call-one": {"rtpengine_port": 30010, "service_mode": "translate"},
            "call-two": {"rtpengine_port": 30020, "service_mode": "translate"},
        }
        self.assertEqual(self.match_session(30020, 41000, "caller_to_agent", active)[0], "call-two")

    def test_original_leg_is_rejected_when_multiple_calls_exist(self):
        active = {
            "call-one": {"rtpengine_port": 30010},
            "call-two": {"rtpengine_port": 30020},
        }
        self.assertIsNone(self.match_session(4000, 30022, "caller_to_core", active))

    def test_single_bilingual_session_keeps_original_leg(self):
        active = {"dialogue": {"rtpengine_port": None, "service_mode": "bilingual_test"}}
        self.assertEqual(self.match_session(4000, 30022, "caller_to_core", active)[0], "dialogue")

    def test_agent_audio_never_matches_subscriber_input(self):
        active = {"call": {"rtpengine_port": 30010}}
        self.assertIsNone(self.match_session(30010, 41000, "agent_to_caller", active))

    def test_original_leg_matches_resolved_subscriber_port(self):
        active = {
            "call-one": {"rtpengine_port": 30010, "subscriber_port": 30020},
            "call-two": {"rtpengine_port": 30012, "subscriber_port": 30022},
        }
        matched = self.match_session(4000, 30022, "caller_to_core", active)
        self.assertEqual(matched[0], "call-two")

    def test_rtpengine_query_selects_ims_subscriber_side(self):
        subscriber_ip = str(next(self.rtpengine.runtime.ims_ue_network.hosts())).encode("ascii")
        response = {
            b"result": b"ok",
            b"tags": {
                b"caller": {
                    b"medias": [
                        {
                            b"type": b"audio",
                            b"streams": [
                                {
                                    b"local port": 30022,
                                    b"flags": [b"RTP"],
                                    b"endpoint": {b"address": subscriber_ip},
                                }
                            ],
                        }
                    ]
                }
            },
        }
        with patch.object(self.rtpengine, "_query", return_value=response):
            self.assertEqual(self.rtpengine.resolve_subscriber_port("call"), 30022)

    def test_core_network_test_clients_count_as_subscribers(self):
        from ims_media import capture

        runtime = self.rtpengine.runtime
        client = os.environ["SIPUE1_IP"]
        self.assertTrue(runtime.is_subscriber(client))
        self.assertEqual(
            capture.packet_direction(client, os.environ["RTPENGINE_IP"]), "caller_to_core"
        )
        self.assertFalse(runtime.is_subscriber(os.environ["PCSCF_IP"]))

    def test_bencode_decoder_detects_trailing_data(self):
        value, end = self.rtpengine._decode(b"d6:result2:okejunk")
        self.assertEqual(value[b"result"], b"ok")
        self.assertNotEqual(end, len(b"d6:result2:okejunk"))


if __name__ == "__main__":
    unittest.main()
