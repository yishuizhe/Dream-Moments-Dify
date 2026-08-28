from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from handlers.message import MessageHandler
from utils.reply_formatter import build_system_prompt


class ReplyNaturalnessTests(unittest.TestCase):
    def make_handler(self) -> MessageHandler:
        handler = MessageHandler.__new__(MessageHandler)
        handler._reply_lock = threading.Lock()
        handler._recent_chat_replies = {}
        return handler

    def test_same_group_answer_is_not_sent_verbatim_twice(self):
        handler = self.make_handler()
        answer = "嗯，买房是希望有稳定的住所呢。车嘛，方便就好。"

        self.assertEqual(
            handler._vary_repeated_reply("group", answer, is_group=True),
            answer,
        )
        varied = handler._vary_repeated_reply("group", answer, is_group=True)
        self.assertNotEqual(varied, answer)
        self.assertTrue("问过" in varied or "轮流" in varied)

    def test_repeat_tracking_is_scoped_to_one_chat(self):
        handler = self.make_handler()
        answer = "今天想喝绿茶。"

        handler._vary_repeated_reply("chat-a", answer, is_group=False)
        self.assertEqual(
            handler._vary_repeated_reply("chat-b", answer, is_group=False),
            answer,
        )

    def test_prompt_encourages_banter_instead_of_counselor_templates(self):
        prompt = build_system_prompt("persona", is_group=True)
        self.assertIn("先接住玩笑", prompt)
        self.assertIn("不要逐字重复旧答案", prompt)
        self.assertIn("能接梗就别上价值课", prompt)


if __name__ == "__main__":
    unittest.main()
