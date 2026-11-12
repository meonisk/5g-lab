"""scripts/profile/report.py: report.json и report.md из файлов прогона без стенда."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts/lib"), str(ROOT / "scripts/profile")]
import report  # noqa: E402

ROUND = {"speech_end_to_reply_rtp_ms": 4900.0, "speech_plus_pause_ms": 4200.0,
         "queue_wait_ms": 3.0, "stt_ms": 3600.0, "translation_ms": 250.0,
         "tts_synthesis_ms": 300.0, "vad_wait_ms": 720.0}  # fmt: skip
CPU = {"ncpu": 12, "cgroup": "v2", "limits": {"lab-ai-worker": 2.0},
       "nodes": {"host": {"n": 9, "mean": 3.0, "p95": 5.5, "max": 6.0},
                 "lab-ai-worker": {"n": 9, "mean": 1.2, "p95": 1.98, "max": 2.0}}}  # fmt: skip
SWEEP_ROW = {"load": "idle", "model": "base", "threads": 2, "streaming": 0, "stt_ms": 900.0,
             "translation_ms": 200.0, "accuracy": 0.9, "cpu_ms": 1700.0,
             "first_partial_ms": None, "n": 3}  # fmt: skip


def write(folder, name, data):
    path = Path(folder) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class Build(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        run = self.folder.name
        write(run, "meta.json", {"created": "20261112T100000Z", "ncpu": 12, "ai_mode": "compact"})
        write(run, "scenarios/S1.json", {"id": "S1", "title": "простой", "status": "done",
                                         "rounds": [], "cpu": CPU})  # fmt: skip
        write(run, "scenarios/S2.json", {"id": "S2", "title": "rfsim", "status": "skip",
                                         "reason": "нет rfsim"})  # fmt: skip
        write(run, "scenarios/S3.json", {"id": "S3", "title": "звонок", "status": "done",
                                         "rounds": [ROUND, ROUND], "cpu": CPU})  # fmt: skip
        write(run, "sweep-idle.json", {"load": "idle", "status": "done", "rows": [SWEEP_ROW],
                                       "models": {"small": {"status": "skip",
                                                           "reason": "нет модели"}}})  # fmt: skip
        self.report = report.build(Path(run), {"model": "base", "threads": 2})

    def test_scenarios_have_cpu_and_stage_summaries(self):
        s3 = self.report["scenarios"]["S3"]
        self.assertEqual(s3["stages"]["stt_ms"]["median"], 3600.0)
        self.assertEqual(s3["cpu"]["nodes"]["lab-ai-worker"]["p95"], 1.98)
        self.assertEqual(self.report["scenarios"]["S2"]["status"], "skip")

    def test_verdict_uses_call_scenario_for_tts_and_bottleneck(self):
        result = self.report["verdict"]
        self.assertEqual(result["source"], "S3")
        self.assertEqual(result["bottleneck"]["stage"], "stt_ms")
        self.assertEqual(result["evaluation"]["load"], "idle")
        # 700 + 900 + 200 + 300 + 3 = 2103 > 2000; 500 -> 1903 укладывается.
        self.assertEqual([c["silence_ms"] for c in result["evaluation"]["fits"]], [500])

    def test_markdown_has_all_sections(self):
        text = report.render(self.report)
        for needle in ("## Итог", "## CPU по сценариям", "## Задержка по этапам",
                       "## Перебор настроек AI", "SKIP", "нет rfsim", "small: нет модели",
                       "stt_ms", "lab-ai-worker", "1.2 / 1.98"):  # fmt: skip
            self.assertIn(needle, text)

    def test_nothing_fits_is_explicit(self):
        self.report["verdict"]["evaluation"]["fits"] = []
        self.assertIn("ни одна конфигурация не укладывается", report.render(self.report))

    def test_empty_run_still_renders(self):
        with tempfile.TemporaryDirectory() as empty:
            result = report.build(Path(empty), {"model": "base", "threads": 2})
        self.assertIsNone(result["verdict"]["source"])
        text = report.render(result)
        self.assertIn("## Итог", text)
        # Без перебора и звонка нечего оценивать: это не то же самое, что «не укладывается».
        self.assertIn("перебор не дал вариантов", text)
        self.assertIn("синтез и очередь не измерены", text)
        self.assertNotIn("None", text)


if __name__ == "__main__":
    unittest.main()
