"""Контракты CPU-профилей: направление, отсутствие LLM fallback и честная транскрипция."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CpuTranslation(unittest.TestCase):
    def setUp(self):
        self.settings = types.SimpleNamespace(llm_response_max_chars=240, translation_beam_size=4)
        package = types.ModuleType("cpu_test")
        package.settings = self.settings
        self.modules = patch.dict(sys.modules, {"cpu_test": package})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.translation = load_module(
            "cpu_test.translation", ROOT / "app/services/ai-worker/ims_ai/translation.py"
        )
        self.models = {}
        for direction in ("ru-en", "en-ru"):
            translator, source, target = Mock(), Mock(), Mock()
            source.encode.return_value = ["input"]
            translator.translate_batch.return_value = [
                types.SimpleNamespace(hypotheses=[["output"]])
            ]
            target.decode.return_value = direction
            self.models[direction] = (translator, source, target)
        self.translation._models = self.models

    def test_each_leg_uses_correct_direction(self):
        for mode, direction in (
            ("translate", "ru-en"),
            ("interpret_ru", "ru-en"),
            ("interpret_en", "en-ru"),
        ):
            with self.subTest(mode=mode):
                text, elapsed = self.translation.translate("test", mode)
                self.assertEqual(text, direction)
                self.assertGreaterEqual(elapsed, 0)
                self.assertEqual(
                    self.models[direction][0].translate_batch.call_args.args[0], [["input", "</s>"]]
                )

    def test_assistant_is_not_silently_translated(self):
        with self.assertRaises(ValueError):
            self.translation.translate("test", "assistant")

    def test_multiple_sentences_are_all_submitted(self):
        self.models["ru-en"][0].translate_batch.return_value = [
            types.SimpleNamespace(hypotheses=[["first"]]),
            types.SimpleNamespace(hypotheses=[["second"]]),
        ]
        self.translation.translate("Здравствуйте! Встреча завтра.", "interpret_ru")
        self.assertEqual(self.models["ru-en"][1].encode.call_count, 2)
        self.assertEqual(len(self.models["ru-en"][0].translate_batch.call_args.args[0]), 2)

    def test_abbreviation_and_initial_do_not_split_sentence(self):
        self.assertEqual(
            self.translation.split_sentences("Dr. Smith is here. Please wait."),
            ["Dr. Smith is here.", "Please wait."],
        )
        self.assertEqual(
            self.translation.split_sentences("А. Иванов приехал."), ["А. Иванов приехал."]
        )

    def test_long_source_is_rejected_before_inference(self):
        self.models["ru-en"][1].encode.return_value = ["input"] * 512
        with self.assertRaises(ValueError):
            self.translation.translate("test", "interpret_ru")
        self.models["ru-en"][0].translate_batch.assert_not_called()

    def test_decoder_limit_is_not_delivered_as_complete_translation(self):
        self.models["ru-en"][0].translate_batch.return_value = [
            types.SimpleNamespace(hypotheses=[["x"] * 256])
        ]
        with self.assertRaises(ValueError):
            self.translation.translate("test", "interpret_ru")

    def test_tts_limit_does_not_truncate_translation(self):
        self.models["ru-en"][2].decode.return_value = "x" * 241
        with self.assertRaises(ValueError):
            self.translation.translate("test", "interpret_ru")

    def test_raw_transcription_never_calls_normalizer(self):
        self.settings.transcript_normalization = "raw"
        normalizer, save = Mock(), Mock(return_value=None)
        mocks = {
            "cpu_test.audio": types.SimpleNamespace(decode_pcm8=lambda x: x),
            "cpu_test.llm": types.SimpleNamespace(
                cyrillic_chars=Mock(), normalize_transcript=normalizer
            ),
            "cpu_test.recording": types.SimpleNamespace(
                recording_session=Mock(), save_recording_turn=save
            ),
        }
        with patch.dict(sys.modules, mocks):
            module = load_module(
                "cpu_test.transcription", ROOT / "app/services/ai-worker/ims_ai/transcription.py"
            )
            result = {"service_mode": "transcribe"}
            module.record_transcript(
                b"audio", {"call_ids": ["test"]}, result, "Я, я не согласен", "ru"
            )
        normalizer.assert_not_called()
        self.assertEqual(save.call_args.args[2], "Я, я не согласен")
        self.assertFalse(result["normalization_applied"])
        self.assertEqual(result["transcript_kind"], "raw_asr")


class CpuProfiles(unittest.TestCase):
    def test_profile_model_pairs_and_cpu_guarantees(self):
        module = load_module("compose_ai_test", ROOT / "scripts/compose_ai.py")
        modes = module.profiles()
        self.assertEqual(modes["balanced"]["AI_MODEL_SIZE"], "small")
        self.assertEqual(modes["compact"]["AI_MODEL_SIZE"], "base")
        self.assertEqual(modes["minimal"]["AI_MODEL_SIZE"], "tiny")
        for mode in ("balanced", "compact", "minimal"):
            self.assertEqual(modes[mode]["AI_TRANSLATION_BACKEND"], "opus-mt")
            self.assertEqual(modes[mode]["AI_TRANSCRIPT_NORMALIZATION"], "raw")
            self.assertEqual(len(modes[mode]["AI_MODEL_REVISION"]), 40)
        self.assertEqual(module.CPU_SETTINGS["AI_DEVICE"], "cpu")
        self.assertEqual(module.CPU_SETTINGS["AI_STREAMING_ENABLED"], "0")


if __name__ == "__main__":
    unittest.main()
