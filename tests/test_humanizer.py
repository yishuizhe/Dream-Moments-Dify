from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.humanizer import humanize_text


class HumanizerTests(unittest.TestCase):
    def test_removes_generic_cutesy_opening_and_wave(self):
        self.assertEqual(humanize_text("诶嘿，被你看出来啦～"), "")

    def test_keeps_specific_content_after_generic_praise(self):
        self.assertEqual(
            humanize_text("太厉害了，后面那个服务的响应还是偏慢。"),
            "后面那个服务的响应还是偏慢。",
        )

    def test_keeps_a_direct_natural_reply(self):
        self.assertEqual(humanize_text("这倒是，先看日志。"), "这倒是，先看日志。")


if __name__ == "__main__":
    unittest.main()
