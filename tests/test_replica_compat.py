from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wechat.replica_compat import ReplicaWeChatClient


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
        db.get_messages.return_value = [
            {"local_id": 2, "sort_seq": 20, "sender_id": 7, "type": "文本", "content": "后"},
            {"local_id": 1, "sort_seq": 10, "sender_id": 7, "type": "文本", "content": "前"},
        ]

        self.assertEqual(client.ChatWith("小明"), "小明")
        messages = client.GetAllMessage()
        self.assertEqual([item.content for item in messages], ["前", "后"])
        self.assertEqual(messages[0].sender, "小明")

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


if __name__ == "__main__":
    unittest.main()
