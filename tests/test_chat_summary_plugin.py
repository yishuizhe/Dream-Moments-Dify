from __future__ import annotations

import importlib.util
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

    def get_messages_for_summary(self, chat_id, limit, *, member_name="", since=None, exclude_assistant=False):
        self.calls.append((chat_id, limit, member_name, since is not None))
        if member_name:
            return [
                {
                    "sender_name": member_name,
                    "sender_id": "1",
                    "role": "user",
                    "content": "今晚十点开会",
                    "created_at": datetime(2026, 7, 14, 9, 0),
                }
            ]
        return [
            {
                "sender_name": "A",
                "sender_id": "1",
                "role": "user",
                "content": "大家好",
                "created_at": datetime(2026, 7, 14, 9, 0),
            }
        ]


class ChatSummaryPluginTests(unittest.TestCase):
    def test_parses_50_100_and_member_commands(self):
        self.assertEqual(
            DreamChatSummaryPlugin._parse_command("总结最近50条"),
            {"kind": "group", "limit": 50, "member_name": "", "days": 0},
        )
        self.assertEqual(
            DreamChatSummaryPlugin._parse_command("总结群聊100条"),
            {"kind": "group", "limit": 100, "member_name": "", "days": 0},
        )
        parsed = DreamChatSummaryPlugin._parse_command("总结 @张三 最近50条")
        self.assertEqual(parsed["kind"], "member")
        self.assertEqual(parsed["limit"], 50)
        self.assertEqual(parsed["member_name"], "张三")
        days = DreamChatSummaryPlugin._parse_command("总结最近3天")
        self.assertEqual(days["kind"], "days")
        self.assertEqual(days["days"], 3)

    def test_member_summary_filters_history_and_calls_ai(self):
        plugin = DreamChatSummaryPlugin(ROOT / "plugins" / "ChatSummary")
        history = FakeHistory()
        prompts = []
        plugin.configure_services(
            history_store=history,
            ai_responder=lambda prompt, chat_id: prompts.append((prompt, chat_id)) or "summary",
        )
        reply = plugin.handle_message({
            "is_group": True,
            "is_self": False,
            "chat_id": "g",
            "sender_name": "caller",
            "content": "总结 @张三 最近100条",
            "bot_name": "bot",
        })
        self.assertEqual(reply, "summary")
        self.assertTrue(history.calls)
        self.assertEqual(history.calls[0][0], "g")
        self.assertEqual(history.calls[0][2], "张三")
        self.assertIn("张三", prompts[0][0])


if __name__ == "__main__":
    unittest.main()
