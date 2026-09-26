"""Working-tree shell bytes must remain executable in Linux containers."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/quality"))
from check_layout import shell_line_ending_error


class ShellLineEndingsTests(unittest.TestCase):
    def test_crlf_shebang_rejected(self):
        error = shell_line_ending_error(
            "app/tests/integration/gate.sh", b"#!/usr/bin/env bash\r\necho ok\r\n"
        )
        self.assertIn("CR line endings", error)

    def test_lf_shell_allowed(self):
        self.assertIsNone(
            shell_line_ending_error("scripts/gate.sh", b"#!/usr/bin/env bash\necho ok\n")
        )

    def test_other_source_crlf_ignored(self):
        self.assertIsNone(shell_line_ending_error("docs/notes.md", b"line\r\n"))


if __name__ == "__main__":
    unittest.main()
