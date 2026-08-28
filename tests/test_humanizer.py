from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.humanizer import humanize_text, warm_short_reply


class HumanizerTests(unittest.TestCase):
    def test_preserves_light_cute_voice(self):
        self.assertEqual(
            humanize_text("诶嘿，被你看出来啦～～"),
            "诶嘿，被你看出来啦～",
        )

    def test_keeps_specific_content_after_generic_praise(self):
        self.assertEqual(
            humanize_text("太厉害了，后面那个服务的响应还是偏慢。"),
            "太厉害了，后面那个服务的响应还是偏慢。",
        )

    def test_keeps_a_direct_natural_reply(self):
        self.assertEqual(humanize_text("这倒是，先看日志。"), "这倒是，先看日志。")

    def test_warms_cold_presence_reply_for_familiar_user(self):
        warmed = warm_short_reply("嗯，在呢。", "@娜娜 在么", "易水哲")
        self.assertNotEqual(warmed, "嗯，在呢。")
        self.assertTrue("易师傅" in warmed or "点我名" in warmed)

    def test_does_not_rewrite_a_substantive_reply(self):
        reply = "在呢，我刚好想和你说件事。"
        self.assertEqual(warm_short_reply(reply, "在吗", "friend"), reply)


if __name__ == "__main__":
    unittest.main()
