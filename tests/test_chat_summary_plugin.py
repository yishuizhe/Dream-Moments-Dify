from __future__ import annotations

import importlib.util
import unittest
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
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
    def test_today_summary_excludes_old_poke_misattribution_other_groups_and_old_summaries(self):
        from unittest.mock import Mock
        store = Mock()
        store.get_messages_for_summary.return_value = [
            {'chat_id': 'target', 'sender_id': 'a', 'sender_name': '微信昵称', 'role': 'user',
             'content': '今天工资到账了'},
            {'chat_id': 'target', 'sender_id': 'outsider', 'sender_name': '外群成员甲', 'role': 'user',
             'content': '<msg><appmsg><title>"A" 拍了拍 "B"</title><type>62</type></appmsg></msg>'},
            {'chat_id': 'other', 'sender_id': 'b', 'sender_name': '另一群成员', 'role': 'user',
             'content': '其他群的真实发言'},
            {'chat_id': 'target', 'sender_name': 'Claude', 'role': 'assistant',
             'content': '【今日概览】旧总结把外群成员甲当成了本群成员'},
            {'chat_id': 'target', 'sender_name': 'Claude', 'role': 'assistant',
             'content': '恭喜，这月可以歇口气了'},
        ]
        responder = Mock(return_value='corrected summary')
        plugin = DreamChatSummaryPlugin(ROOT / 'plugins/ChatSummary')
        plugin._save_summary_record = Mock()
        directory = Mock(return_value=[{'username': 'a', 'group_nickname': '本群名片'}])
        plugin.configure_services(history_store=store, ai_responder=responder, member_directory=directory)
        self.assertEqual(plugin.handle_message({'is_group': True, 'chat_id': 'target',
                         'content': '今日总结', 'bot_name': 'Claude'}), 'corrected summary')
        prompt, chat = responder.call_args.args
        self.assertEqual(chat, 'target')
        self.assertIn('本群名片：今天工资到账了', prompt)
        self.assertIn('Claude：恭喜', prompt)
        self.assertNotIn('娜娜', prompt)
        self.assertNotIn('外群成员甲', prompt)
        self.assertNotIn('另一群成员', prompt)
        self.assertNotIn('其他群的真实发言', prompt)
        directory.assert_called_once_with('target')

    def test_mentions_accept_spaces_and_long_nicknames(self):
        for command, name in [("锐评 @张三", "张三"), ("锐评 @Viva La Vida 50条", "Viva La Vida"),
                              ("锐评价 @张三", "张三"), ("锐评Member 1234", "Member 1234")]:
            with self.subTest(command=command):
                self.assertEqual(DreamChatSummaryPlugin._parse_command(command)["member_name"], name)

    def test_aliases_link_legacy_history_but_real_same_names_are_ambiguous(self):
        from unittest.mock import MagicMock

        plugin = DreamChatSummaryPlugin(ROOT / "plugins" / "ChatSummary")
        store = MagicMock()
        store.get_summary_members.return_value = [
            {"username": "wxid_a", "sender_name": "旧名"},
            {"username": "群昵称", "sender_name": "群昵称"},
        ]
        directory = [{"username": "wxid_a", "nick_name": "微信昵称", "remark": "备注", "group_nickname": "群昵称"}]
        plugin.configure_services(history_store=store, member_directory=lambda chat: directory)
        for name in ["微信昵称", "群昵称", "旧名", "备注"]:
            identities, error = plugin._resolve_member("g", name)
            self.assertFalse(error)
            self.assertEqual(set(identities), {"wxid_a", "群昵称"})
        directory.append({"username": "wxid_b", "group_nickname": "群昵称"})
        identities, error = plugin._resolve_member("g", "群昵称")
        self.assertFalse(identities)
        self.assertIn("多个群成员", error)

    def test_self_request_filters_by_caller_id(self):
        from unittest.mock import MagicMock

        history = MagicMock()
        history.get_messages_for_summary.return_value = []
        plugin = DreamChatSummaryPlugin(ROOT / "plugins" / "ChatSummary")
        plugin.configure_services(history_store=history, ai_responder=lambda p, c: "unused")
        plugin.handle_message({"is_group": True, "chat_id": "g", "sender_id": "wxid_caller",
                               "sender_name": "来客", "content": "锐评一下我"})
        self.assertEqual(history.get_messages_for_summary.call_args.kwargs["member_ids"], ["wxid_caller"])

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
