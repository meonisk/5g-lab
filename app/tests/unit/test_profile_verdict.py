"""scripts/profile/verdict.py: какие настройки AI укладываются в 2 с и где узкое место."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts/lib"), str(ROOT / "scripts/profile")]
import verdict  # noqa: E402

CONTEXT = {"queue_ms": 10.0, "tts_ms": 290.0, "translation_ms": 400.0}
REFERENCE = {"model": "base", "threads": 2}


def row(model, threads, stt, accuracy, cpu, load="rfsim", streaming=0, translation=200.0):
    return {"load": load, "model": model, "threads": threads, "streaming": streaming,
            "stt_ms": stt, "translation_ms": translation, "accuracy": accuracy,
            "cpu_ms": cpu}  # fmt: skip


class Evaluate(unittest.TestCase):
    def test_estimate_is_pause_plus_stages_plus_queue(self):
        result = verdict.evaluate([row("base", 2, 1000.0, 0.9, 1800.0)], CONTEXT, REFERENCE)
        estimates = {c["silence_ms"]: c["estimate_ms"] for c in result["candidates"]}
        self.assertEqual(estimates, {700: 2200.0, 500: 2000.0, 300: 1800.0})
        self.assertEqual(result["load"], "rfsim")
        self.assertEqual(result["reference"]["accuracy"], 0.9)

    def test_fits_requires_limit_and_quality_within_ten_points(self):
        rows = [
            row("base", 2, 1000.0, 0.90, 1800.0),
            row("tiny", 2, 400.0, 0.85, 700.0),  # -5 п.п.: укладывается
            row("tiny", 1, 500.0, 0.75, 500.0),  # -15 п.п.: хуже эталона
            row("small", 4, 3000.0, 0.97, 9000.0),  # слишком долго
        ]
        result = verdict.evaluate(rows, CONTEXT, REFERENCE)
        fits = [(c["model"], c["threads"], c["silence_ms"]) for c in result["fits"]]
        # Один вариант на (модель, потоки) — с самой длинной паузой; порядок — по CPU.
        self.assertEqual(fits, [("tiny", 2, 700), ("base", 2, 500)])

    def test_at_most_three_and_sorted_by_cpu(self):
        rows = [row("base", 2, 100.0, 0.9, 900.0)]
        rows += [row("tiny", t, 100.0, 0.9, 100.0 * t) for t in (1, 2, 4, 8)]
        result = verdict.evaluate(rows, CONTEXT, REFERENCE)
        self.assertEqual([c["threads"] for c in result["fits"]], [1, 2, 4])

    def test_idle_rows_used_only_without_rfsim(self):
        rows = [row("base", 2, 1000.0, 0.9, 1.0, load="idle")]
        result = verdict.evaluate(rows, CONTEXT, REFERENCE)
        self.assertEqual(result["load"], "idle")
        self.assertIn("rfsim", result["note"])

    def test_missing_translation_falls_back_to_scenarios(self):
        result = verdict.evaluate([row("base", 2, 100.0, 0.9, 1.0, translation=None)],
                                  CONTEXT, REFERENCE)  # fmt: skip
        self.assertEqual(result["candidates"][0]["estimate_ms"], 100 + 400 + 290 + 10 + 700)

    def test_no_reference_means_nothing_fits(self):
        result = verdict.evaluate([row("tiny", 2, 100.0, 0.9, 1.0)], CONTEXT, REFERENCE)
        self.assertEqual(result["fits"], [])
        self.assertIn("эталон", result["note"])

    def test_streaming_rows_are_not_candidates(self):
        rows = [row("base", 2, 100.0, 0.9, 1.0), row("base", 2, 100.0, 0.9, 1.0, streaming=1)]
        result = verdict.evaluate(rows, CONTEXT, REFERENCE)
        self.assertTrue(all(c["streaming"] == 0 for c in result["candidates"]))


class Bottleneck(unittest.TestCase):
    def test_largest_stage_and_cpu_pressure(self):
        stages = {"vad_wait_ms": 700.0, "queue_wait_ms": 5.0, "stt_ms": 3600.0,
                  "translation_ms": 300.0, "tts_synthesis_ms": 290.0}  # fmt: skip
        cpu = {
            "ncpu": 12,
            "limits": {"lab-ai-worker": 2.0},
            "nodes": {
                "lab-ai-worker": {"p95": 1.95},
                "host": {"p95": 11.5},
                "rfsim-gnb": {"p95": 3.0},
            },  # fmt: skip
        }
        result = verdict.bottleneck(stages, cpu)
        self.assertEqual(result["stage"], "stt_ms")
        self.assertEqual(result["share"], 0.74)
        self.assertEqual(len(result["cpu"]), 2)
        self.assertIn("lab-ai-worker", result["cpu"][0])

    def test_without_data(self):
        self.assertIsNone(verdict.bottleneck({}, None)["stage"])


if __name__ == "__main__":
    unittest.main()
