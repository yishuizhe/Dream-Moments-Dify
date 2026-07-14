from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_FILE = ROOT / "plugins" / "ChatSummary" / "dream_plugin.py"
spec = importlib.util.spec_from_file_location("chat_summary_test_plugin", PLUGIN_FILE)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
DreamChatSummaryPlugin = module.DreamChatSummaryPlugin


class FakeHistory:
    def __init__(self):
        self.calls = []

    def get_recent_messages(self, chat_id, limit, sender_name=None):
        self.calls.append((chat_id, limit, sender_name))
        return [
            {"sender_name": sender_name or "A", "sender_id": "1", "role": "user",
             "content": "\u4eca\u665a\u5341\u70b9\u5f00\u4f1a", "created_at": datetime(2026, 7, 14, 9, 0)}
        ]


class ChatSummaryPluginTests(unittest.TestCase):
    def test_parses_50_100_and_member_commands(self):
        self.assertEqual(DreamChatSummaryPlugin._parse_command("\u603b\u7ed3\u6700\u8fd150\u6761"), (50, ""))
        self.assertEqual(DreamChatSummaryPlugin._parse_command("\u603b\u7ed3\u7fa4\u804a100\u6761"), (100, ""))
        self.assertEqual(
            DreamChatSummaryPlugin._parse_command("\u603b\u7ed3 @\u5f20\u4e09 \u6700\u8fd150\u6761"),
            (50, "\u5f20\u4e09"),
        )

    def test_member_summary_filters_history_and_calls_ai(self):
        plugin = DreamChatSummaryPlugin(ROOT / "plugins" / "ChatSummary")
        history = FakeHistory()
        prompts = []
        plugin.configure_services(
            history_store=history,
            ai_responder=lambda prompt, chat_id: prompts.append((prompt, chat_id)) or "summary",
        )
        reply = plugin.handle_message({
            "is_group": True, "is_self": False, "chat_id": "g",
            "sender_name": "caller", "content": "\u603b\u7ed3 @\u5f20\u4e09 \u6700\u8fd1100\u6761", "bot_name": "bot"
        })
        self.assertEqual(reply, "summary")
        self.assertEqual(history.calls, [("g", 120, "\u5f20\u4e09")])
        self.assertIn("\u5f20\u4e09", prompts[0][0])


if __name__ == "__main__":
    unittest.main()
