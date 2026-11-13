"""scripts/profile/sweep.py: план перебора, параметры контейнера сервиса и сводка без Docker."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts/lib"), str(ROOT / "scripts/profile"), str(ROOT / "scripts"),
                str(ROOT / "app/tests/fixtures")]  # fmt: skip
import dialogue  # noqa: E402
import sweep  # noqa: E402

INSPECT = {
    "Config": {
        "Image": "lab-ai-worker-cpu",
        "Env": [
            "AI_MODEL_CACHE=/models",
            "AI_TRANSLATION_MODEL_ROOT=/translation-models",
            "AI_STT_CPU_THREADS=2",
            "SERVICE_CONTROL_TOKEN_FILE=/run/lab-control/token",
            "LLM_SYSTEM_PROMPT=Ты помощник. Отвечай коротко.",
        ],
    },  # fmt: skip
    "HostConfig": {"NanoCpus": 2000000000, "Memory": 1610612736},
    "Mounts": [
        {"Type": "volume", "Name": "lab-docker_ai-model-cache", "Destination": "/models"},
        {
            "Type": "bind",
            "Source": "/srv/lab/local/models/opus-mt",
            "Destination": "/translation-models",
        },
        {
            "Type": "volume",
            "Name": "lab-docker_service-control-secret",
            "Destination": "/run/lab-control",
        },
        {
            "Type": "bind",
            "Source": "/srv/lab/local/private/recordings",
            "Destination": "/recordings",
        },
    ],  # fmt: skip
}


class Plan(unittest.TestCase):
    def test_threads_capped_by_nproc(self):
        self.assertEqual(sweep.plan_threads(12, 2, quick=False), [1, 2, 4, 8])
        self.assertEqual(sweep.plan_threads(4, 2, quick=False), [1, 2, 4])
        self.assertEqual(sweep.plan_threads(12, 2, quick=True), [2, 4])
        self.assertEqual(sweep.plan_threads(1, 2, quick=True), [1])

    def test_model_revisions_from_profiles_and_lab_env(self):
        profiles = {"compact": {"AI_MODEL_SIZE": "base", "AI_MODEL_REVISION": "b"},
                    "minimal": {"AI_MODEL_SIZE": "tiny", "AI_MODEL_REVISION": "t"},
                    "baseline": {}}  # fmt: skip
        settings = {"AI_MODEL_SIZE": "small", "AI_MODEL_REVISION": "s"}
        self.assertEqual(
            sweep.model_revisions(profiles, settings), {"tiny": "t", "base": "b", "small": "s"}
        )


class Service(unittest.TestCase):
    def test_spec_keeps_limits_and_model_mounts_only(self):
        spec = sweep.service_spec(INSPECT)
        self.assertEqual((spec["image"], spec["cpus"], spec["memory"]),
                         ("lab-ai-worker-cpu", 2.0, 1610612736))  # fmt: skip
        self.assertEqual(spec["stt_threads"], 2)
        self.assertEqual(
            spec["mounts"],
            ["type=volume,src=lab-docker_ai-model-cache,dst=/models,readonly",
             "type=bind,src=/srv/lab/local/models/opus-mt,dst=/translation-models,readonly"],
        )  # fmt: skip
        # Токен сервиса не монтируется: runtime получает пустышку из папки перебора.
        self.assertIn("SERVICE_CONTROL_TOKEN_FILE=/sweep/token", spec["env"])
        self.assertIn("HF_HUB_OFFLINE=1", spec["env"])
        self.assertNotIn("SERVICE_CONTROL_TOKEN_FILE=/run/lab-control/token", spec["env"])

    def test_no_cpu_limit(self):
        inspect = {**INSPECT, "HostConfig": {"NanoCpus": 0, "Memory": 0}}
        self.assertIsNone(sweep.service_spec(inspect)["cpus"])


class Aggregate(unittest.TestCase):
    def test_rows_per_model_and_threads(self):
        phrases = [{"id": "p1", "text": "добрый день"}, {"id": "p2", "text": "как дела"}]
        raw = {
            "runs": [
                {"model": "base", "threads": 2, "phrase": "p1", "stt_ms": 900.0, "cpu_ms": 1700.0,
                 "transcript": "Добрый день.", "translation_ms": 200.0},
                {"model": "base", "threads": 2, "phrase": "p2", "stt_ms": 1100.0, "cpu_ms": 1900.0,
                 "transcript": "как", "translation_ms": None},
            ],
            "streaming": [{"model": "base", "threads": 2, "phrase": "p1", "first_partial_ms": 1500.0},
                          {"model": "base", "threads": 2, "phrase": "p2",
                           "first_partial_ms": None}],
        }  # fmt: skip
        rows = sweep.aggregate(raw, phrases, "rfsim")
        self.assertEqual(rows[0], {"load": "rfsim", "model": "base", "threads": 2, "streaming": 0,
                                   "n": 2, "stt_ms": 1000.0, "translation_ms": 200.0,
                                   "accuracy": 0.75, "cpu_ms": 1800.0,
                                   "first_partial_ms": None})  # fmt: skip
        self.assertEqual(rows[1]["streaming"], 1)
        self.assertEqual(rows[1]["first_partial_ms"], 1500.0)
        self.assertIsNone(rows[1]["stt_ms"])


if __name__ == "__main__":
    unittest.main()


class PiperPhrases(unittest.TestCase):
    def test_phrase_wavs_creates_missing_folder(self):
        # S4 пишет фразу в local/rfsim/phrase, которого на чистом стенде ещё нет.
        with (
            tempfile.TemporaryDirectory() as root,
            mock.patch.object(dialogue, "run_inside") as run,
        ):
            folder = Path(root).resolve() / "rfsim/phrase"
            paths = dialogue.phrase_wavs(["Добрый день.", "Как дела?"], folder)
            texts = json.loads((folder / "phrases.json").read_text(encoding="utf-8"))
        self.assertEqual(texts, ["Добрый день.", "Как дела?"])
        self.assertEqual(paths, [folder / "p1.wav", folder / "p2.wav"])
        run.assert_called_once_with(folder / "phrases.json", folder, "--phrases")
