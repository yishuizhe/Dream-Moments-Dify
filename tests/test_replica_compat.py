from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wechat.replica_compat import (
    ReplicaWeChatClient,
    _merge_search_ocr_rows,
    _ocr_name_similarity,
    _safe_ocr_name_matches,
    _select_search_result,
    _search_ocr_name_matches,
    _title_ocr_name_matches,
)


class ReplicaCompatibilityTests(unittest.TestCase):
    def make_client(self):
        db = MagicMock()
        db.get_self_info.return_value = {
            "username": "wxid_self",
            "nick_name": "娜娜",
            "remark": "",
        }
        with patch("wechatauto.WeChatDB", return_value=db):
            client = ReplicaWeChatClient()
        return client, db

    def test_reads_database_messages_in_chronological_order(self):
        client, db = self.make_client()
        db.search_contact.return_value = [
            {"username": "friend-id", "nick_name": "小明", "remark": ""}
        ]
        db.get_nickname.return_value = "小明"
        db.get_messages.return_value = [
            {"local_id": 2, "sort_seq": 20, "sender_id": 7, "type": "文本", "content": "后"},
            {"local_id": 1, "sort_seq": 10, "sender_id": 7, "type": "文本", "content": "前"},
        ]

        self.assertEqual(client.ChatWith("小明"), "小明")
        messages = client.GetAllMessage()
        self.assertEqual([item.content for item in messages], ["前", "后"])
        self.assertEqual(messages[0].sender, "小明")

    def test_persisted_id_follows_a_group_rename(self):
        client, db = self.make_client()
        client.BindContactId("旧群名", "room@chatroom")
        db.get_nickname.return_value = "新群名"

        self.assertEqual(client.ChatWith("旧群名"), "新群名")
        self.assertEqual(client.ChatInfo()["chat_id"], "room@chatroom")
        self.assertEqual(client.ChatInfo()["chat_name"], "新群名")

    def test_private_message_direction_matches_wechat_4_1_12_database(self):
        client, db = self.make_client()
        db.search_contact.return_value = [
            {"username": "friend-id", "nick_name": "小明", "remark": ""}
        ]
        db.get_nickname.return_value = "小明"
        db.get_messages.return_value = [
            {"local_id": 2, "sort_seq": 20, "sender_id": 1, "type": "文本", "content": "我发的"},
            {"local_id": 1, "sort_seq": 10, "sender_id": 2, "type": "文本", "content": "对方发的"},
        ]

        client.ChatWith("小明")
        incoming, outgoing = client.GetAllMessage()

        self.assertEqual(incoming.attr, "friend")
        self.assertEqual(outgoing.attr, "self")

    def test_group_sender_prefix_is_removed_and_resolved(self):
        client, db = self.make_client()
        db.search_contact.side_effect = lambda name: (
            [{"username": "room@chatroom", "nick_name": "测试群", "remark": ""}]
            if name == "测试群"
            else []
        )
        db.get_nickname.return_value = "小红"
        db.get_messages.return_value = [
            {
                "local_id": 3,
                "sort_seq": 30,
                "sender_id": 8,
                "sender_username": "wxid_red",
                "type": "文本",
                "content": "wxid_red:\n娜娜在吗",
            }
        ]

        client.ChatWith("测试群")
        message = client.GetAllMessage()[0]
        self.assertEqual(message.content, "娜娜在吗")
        self.assertEqual(message.sender, "小红")
        self.assertEqual(client.ChatInfo()["chat_type"], "group")

    def test_group_sender_prefix_overrides_ambiguous_self_direction(self):
        client, db = self.make_client()
        client.BindContactId("测试群", "room@chatroom")
        db.get_nickname.side_effect = lambda username: (
            "成员" if username == "wxid_member" else "测试群"
        )
        db.get_messages.return_value = [
            {
                "local_id": 4,
                "sort_seq": 40,
                "sender_id": 2,
                "sender_username": "",
                "type": "文本",
                "content": "wxid_member:\n娜娜，出来吧",
            }
        ]

        client.ChatWith("测试群")
        message = client.GetAllMessage()[0]

        self.assertEqual(message.attr, "friend")
        self.assertEqual(message.sender, "成员")
        self.assertEqual(message.content, "娜娜，出来吧")

    def test_group_sender_id_one_is_local_account(self):
        client, db = self.make_client()
        client.BindContactId("测试群", "room@chatroom")
        db.get_nickname.return_value = "测试群"
        db.get_messages.return_value = [
            {
                "local_id": 5,
                "sort_seq": 50,
                "sender_id": 1,
                "type": "文本",
                "content": "我在群里发的",
            }
        ]

        client.ChatWith("测试群")
        self.assertEqual(client.GetAllMessage()[0].attr, "self")

    def test_session_fields_match_polling_adapter(self):
        client, db = self.make_client()
        db.get_nickname.return_value = "小明"
        db.get_sessions.return_value = [
            {"username": "friend-id", "summary": "你好", "last_time": 123, "unread": 2}
        ]
        self.assertEqual(
            client.GetSession()[0],
            {
                "name": "小明",
                "username": "friend-id",
                "content": "你好",
                "time": 123,
                "unread_count": 2,
            },
        )

    def test_sidebar_ocr_accepts_one_clipped_group_name_edge(self):
        self.assertTrue(
            _safe_ocr_name_matches("以开心摸鱼小分", "开心摸鱼小分队")
        )
        self.assertFalse(_safe_ocr_name_matches("小明", "开心摸鱼小分队"))

    def test_search_ocr_accepts_one_wrong_character_but_not_another_chat(self):
        self.assertTrue(_search_ocr_name_matches("开芯摸鱼小分队", "开心摸鱼小分队"))
        self.assertFalse(_search_ocr_name_matches("小明", "开心摸鱼小分队"))

    def test_best_search_match_tolerates_multiple_long_name_ocr_errors(self):
        target = "开心摸鱼小分队"
        self.assertGreater(_ocr_name_similarity("开芯摸鱼小分対", target), 0.55)
        self.assertLess(_ocr_name_similarity("完全不同的群聊", target), 0.55)

    def test_search_ocr_scales_keep_clearer_text_and_missing_headings(self):
        merged = _merge_search_ocr_rows(
            [
                [("能@0问渠安", 87, 129, 32, 10)],
                [
                    ("问渠安", 88, 129, 12, 12),
                    ("群聊", 84, 275, 11, 10),
                ],
            ],
            "问渠安全实验室",
        )

        self.assertEqual(merged[0][0], "问渠安")
        self.assertIn(("群聊", 84, 275, 11, 10), merged)

    def test_title_match_tolerates_one_glyph_but_rejects_another_chat(self):
        self.assertTrue(_title_ocr_name_matches("开芯摸鱼小分队（8）", "开心摸鱼小分队"))
        self.assertFalse(_title_ocr_name_matches("完全不同的群聊", "开心摸鱼小分队"))

    def test_same_name_search_selects_group_from_member_preview(self):
        rows = [
            ("裴怡淼", 128, 117, 14, 12),
            ("包含：裴怡淼〔企业：问渠安全", 128, 142, 12, 11),
            ("@问渠安全实验室", 177, 215, 23, 11),
            ("企业：问渠安全实验室", 128, 238, 12, 11),
            ("群聊", 84, 275, 12, 11),
            ("能@0问渠安", 87, 321, 32, 10),
            ("搜索网络结果", 85, 372, 14, 10),
        ]

        selected = _select_search_result(
            rows,
            "问渠安全实验室",
            sidebar_right=261,
            render_h=815,
            expected_group=True,
        )
        self.assertEqual(selected, rows[5])

    def test_same_name_search_prefers_unique_group_in_most_used_section(self):
        rows = [
            ("最常便用", 84, 83, 12, 11),
            ("问渠安", 128, 129, 12, 12),
            ("包含：裴怡淼〔企业：", 128, 205, 12, 11),
            ("@问渠安全实验室", 177, 278, 23, 11),
            ("企业：问渠安全实验室", 128, 301, 12, 11),
            ("搜索网络结果", 84, 340, 14, 10),
        ]

        selected = _select_search_result(
            rows,
            "问渠安全实验室",
            sidebar_right=221,
            render_h=815,
            expected_group=True,
        )

        self.assertEqual(selected, rows[1])

    def test_same_name_search_selects_non_group_contact(self):
        rows = [
            ("@问渠安全实验室", 177, 215, 23, 11),
            ("企业：问渠安全实验室", 128, 238, 12, 11),
            ("群聊", 84, 275, 12, 11),
            ("问渠安全实验室", 128, 321, 12, 12),
        ]

        selected = _select_search_result(
            rows,
            "问渠安全实验室",
            sidebar_right=261,
            render_h=815,
            expected_group=False,
        )
        self.assertEqual(selected, rows[1])

    def test_multiple_same_name_groups_are_rejected(self):
        rows = [
            ("群聊", 84, 80, 40, 12),
            ("同名群聊", 100, 120, 40, 12),
            ("同名群聊", 100, 180, 40, 12),
            ("搜索网络结果", 84, 230, 40, 12),
        ]

        self.assertIsNone(
            _select_search_result(
                rows,
                "同名群聊",
                sidebar_right=261,
                render_h=815,
                expected_group=True,
            )
        )

    def test_text_send_requires_target_and_starts_database_audit(self):
        client, _db = self.make_client()
        sender = MagicMock()
        sender.open_chat.return_value = True
        sender._chat_is_open.return_value = True
        sender.right_pane_left = 200
        sender.render_h = 800
        sender.render_w = 1000
        sender.focus_input.return_value = True
        client._uia_sender = sender
        client._resolve_username = MagicMock(return_value="room@chatroom")

        self.assertTrue(client.SendMsg("你好", "测试群"))

        sender.open_chat.assert_called_once_with(
            "测试群", exact=True, expected_group=True
        )
        self.assertEqual(sender._chat_is_open.call_count, 3)

    def test_text_send_aborts_if_target_changes_before_enter(self):
        client, _db = self.make_client()
        sender = MagicMock()
        sender.open_chat.return_value = True
        sender._chat_is_open.side_effect = [True, True, False]
        sender.right_pane_left = 200
        sender.render_h = 800
        sender.render_w = 1000
        sender.focus_input.return_value = True
        client._uia_sender = sender
        client._resolve_username = MagicMock(return_value="room@chatroom")

        with self.assertRaisesRegex(RuntimeError, "输入过程中发生变化"):
            client.SendMsg("不能发错", "测试群")

        keys = sender._input.key.call_args_list
        self.assertGreaterEqual(len(keys), 5)
        self.assertNotIn(13, [call.args[0] for call in keys])

if __name__ == "__main__":
    unittest.main()
