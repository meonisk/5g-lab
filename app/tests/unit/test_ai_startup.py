"""AI Worker отказывается стартовать в обход scripts/start.py, а start.py ставит метку."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/services/ai-worker"))
sys.path.insert(0, str(ROOT / "scripts"))

from ims_ai.startup import unapplied_mode_error  # noqa: E402


class StartupGuard(unittest.TestCase):
    def test_bare_compose_is_refused_with_hint(self):
        # Голый compose: lab.env говорит compact, но профиль режима не применён.
        error = unapplied_mode_error({"AI_MODE": "compact"})
        self.assertIn("AI_MODE=compact", error)
        self.assertIn("scripts/start.py", error)

    def test_empty_mark_counts_as_missing(self):
        # ${AI_MODE_APPLIED:-} в compose даёт пустую строку, а не отсутствие переменной.
        self.assertIsNotNone(unapplied_mode_error({"AI_MODE_APPLIED": ""}))

    def test_start_py_mark_allows_any_mode(self):
        # start.py --mode baseline при AI_MODE=compact — законный выбор, не ошибка.
        environ = {"AI_MODE": "compact", "AI_MODE_APPLIED": "baseline"}
        self.assertIsNone(unapplied_mode_error(environ))

    def test_compose_passes_mark_to_worker(self):
        compose = (ROOT / "app/infrastructure/compose/ai.yml").read_text(encoding="utf-8")
        self.assertIn("AI_MODE_APPLIED: ${AI_MODE_APPLIED:-}", compose)

    def test_start_py_sets_mark_for_every_mode(self):
        source = (ROOT / "scripts/start.py").read_text(encoding="utf-8")
        self.assertIn('"AI_MODE_APPLIED": args.mode', source)


if __name__ == "__main__":
    unittest.main()
