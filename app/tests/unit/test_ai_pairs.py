"""AI Worker: явная пара ног от SIP AS вместо поиска единственной противоположной ноги."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/services/ai-worker"))


class Pairs(unittest.TestCase):
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
            from ims_ai import api, interpretation, lifecycle, runtime
        cls.interpretation, cls.lifecycle, cls.runtime = interpretation, lifecycle, runtime
        cls.client = api.api.test_client()
        cls.headers = {"Authorization": f"Bearer {runtime.control_token}"}

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.runtime.pairs.clear()
        self.runtime.active_calls.clear()

    def post_pair(self, first, second):
        legs = [{"call_id": first[0], "language": first[1]}]
        legs.append({"call_id": second[0], "language": second[1]})
        return self.client.post("/pairs", json={"legs": legs}, headers=self.headers)

    def test_pair_routes_each_leg_to_its_partner(self):
        self.assertEqual(self.post_pair(("leg-a", "ru"), ("leg-b", "en")).status_code, 202)
        self.assertEqual(self.interpretation.delivery_call("leg-a", "interpret_ru"), "leg-b")
        self.assertEqual(self.interpretation.delivery_call("leg-b", "interpret_en"), "leg-a")

    def test_two_pairs_at_once(self):
        self.post_pair(("a1", "ru"), ("b1", "en"))
        self.post_pair(("a2", "ru"), ("b2", "en"))
        for call_id, mode in (("a1", "interpret_ru"), ("b1", "interpret_en")):
            self.runtime.active_calls[call_id] = {"service_mode": mode}
        for call_id, mode in (("a2", "interpret_ru"), ("b2", "interpret_en")):
            self.runtime.active_calls[call_id] = {"service_mode": mode}
        self.assertEqual(self.interpretation.delivery_call("a1", "interpret_ru"), "b1")
        self.assertEqual(self.interpretation.delivery_call("b2", "interpret_en"), "a2")

    def test_invalid_pairs_are_rejected(self):
        cases = [
            (("leg-a", "ru"), ("leg-b", "ru")),
            (("leg-a", "ru"), ("leg-a", "en")),
            (("leg-a", "ru"), ("bad id", "en")),
            (("leg-a", "ru"), ("leg-b", "de")),
        ]
        for first, second in cases:
            with self.subTest(first=first, second=second):
                self.assertEqual(self.post_pair(first, second).status_code, 400)
        single = {"legs": [{"call_id": "leg-a", "language": "ru"}]}
        response = self.client.post("/pairs", json=single, headers=self.headers)
        self.assertEqual(response.status_code, 400)

    def test_unpaired_interpreter_legs_keep_old_rule(self):
        self.runtime.active_calls["ru-1"] = {"service_mode": "interpret_ru"}
        self.runtime.active_calls["en-1"] = {"service_mode": "interpret_en"}
        self.assertEqual(self.interpretation.delivery_call("ru-1", "interpret_ru"), "en-1")

    def test_paired_legs_are_not_candidates_for_others(self):
        self.post_pair(("leg-a", "ru"), ("leg-b", "en"))
        self.runtime.active_calls["leg-b"] = {"service_mode": "interpret_en"}
        self.runtime.active_calls["ru-1"] = {"service_mode": "interpret_ru"}
        with self.assertRaises(RuntimeError):
            self.interpretation.delivery_call("ru-1", "interpret_ru")

    def test_delete_removes_both_directions(self):
        self.post_pair(("leg-a", "ru"), ("leg-b", "en"))
        response = self.client.delete("/pairs/leg-a", headers=self.headers)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.runtime.pairs, {})

    def test_call_end_drops_own_pair_entry(self):
        self.post_pair(("leg-a", "ru"), ("leg-b", "en"))
        self.lifecycle.clear_call_state("leg-a")
        self.assertNotIn("leg-a", self.runtime.pairs)
        self.assertEqual(self.runtime.pairs["leg-b"], "leg-a")


if __name__ == "__main__":
    unittest.main()
