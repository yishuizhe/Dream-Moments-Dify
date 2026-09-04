from __future__ import annotations

import sys
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.database import Base, HistoryStore, make_identity_key, resolve_identity


class HistoryMemoryTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.store = HistoryStore(sessionmaker(bind=engine))

    def test_group_member_memories_are_isolated(self):
        first = make_identity_key("group-a", "member-1", True)
        second = make_identity_key("group-a", "member-2", True)
        self.store.remember_user_message(
            identity_key=first, chat_id="group-a", sender_id="member-1",
            sender_name="A", content="\u6211\u559c\u6b22\u559d\u8336"
        )
        self.store.remember_user_message(
            identity_key=second, chat_id="group-a", sender_id="member-2",
            sender_name="B", content="\u6211\u559c\u6b22\u559d\u5496\u5561"
        )
        self.assertEqual(self.store.get_memory_items(first), ["\u6211\u559c\u6b22\u559d\u8336"])
        self.assertEqual(self.store.get_memory_items(second), ["\u6211\u559c\u6b22\u559d\u5496\u5561"])

    def test_summary_commands_are_not_saved_as_memory(self):
        identity = make_identity_key("group-a", "member-1", True)
        self.store.remember_user_message(
            identity_key=identity, chat_id="group-a", sender_id="member-1",
            sender_name="A", content="@Bot \u603b\u7ed3 @\u5f20\u4e09 \u6700\u8fd150\u6761"
        )
        self.assertEqual(self.store.get_memory_items(identity), [])

    def test_bare_wake_words_and_greetings_are_not_saved_as_memory(self):
        identity = make_identity_key("group-a", "member-1", True)
        for content in ("娜娜", "@娜娜？", "在吗", "你好！", "hello"):
            self.store.remember_user_message(
                identity_key=identity,
                chat_id="group-a",
                sender_id="member-1",
                sender_name="A",
                content=content,
            )

        self.assertEqual(self.store.get_memory_items(identity), [])

    def test_history_can_filter_one_group_member(self):
        for sender, name, content in [
            ("1", "A", "a1"), ("2", "B", "b1"), ("1", "A", "a2")
        ]:
            self.store.record_message(
                chat_id="g", sender_id=sender, sender_name=name, role="user",
                content=content, is_group=True
            )
        rows = self.store.get_recent_messages("g", 50, sender_name="A")
        self.assertEqual([row["content"] for row in rows], ["a1", "a2"])

    def test_group_rename_migrates_history_and_member_memory(self):
        old_key = make_identity_key("旧群名", "member-1", True)
        self.store.record_message(
            chat_id="旧群名", sender_id="member-1", sender_name="A",
            role="user", content="改名前的消息", is_group=True,
        )
        self.store.remember_user_message(
            identity_key=old_key, chat_id="旧群名", sender_id="member-1",
            sender_name="A", content="改名前的记忆",
        )

        stable = self.store.register_chat_identity(
            "room@chatroom", "新群名", aliases=["旧群名"], is_group=True,
        )

        self.assertEqual(stable, "room@chatroom")
        self.assertEqual(
            [row["content"] for row in self.store.get_recent_messages(stable, 10)],
            ["改名前的消息"],
        )
        self.assertEqual(
            self.store.get_memory_items(make_identity_key(stable, "member-1", True)),
            ["改名前的记忆"],
        )
        self.assertEqual(self.store.get_chat_display_name(stable), "新群名")

    def test_configured_aliases_share_one_identity_and_previous_memory(self):
        aliases = ["我=私聊名=群昵称"]
        private_key, private_aliases = resolve_identity(
            "私聊名", "private-id", "私聊名", False, aliases
        )
        group_key, group_aliases = resolve_identity(
            "group-a", "group-id", "群昵称", True, aliases
        )
        self.assertEqual(private_key, "person:我")
        self.assertEqual(group_key, private_key)
        self.store.remember_user_message(
            identity_key=make_identity_key("私聊名", "private-id", False),
            chat_id="私聊名", sender_id="private-id", sender_name="私聊名",
            content="我喜欢喝茶",
        )
        self.store.remember_user_message(
            identity_key=group_key, chat_id="group-a", sender_id="group-id",
            sender_name="群昵称", content="群里也记得这件事",
        )
        self.assertEqual(
            self.store.get_memory_items_for_aliases(group_key, group_aliases),
            ["我喜欢喝茶", "群里也记得这件事"],
        )
        self.assertEqual(private_aliases, ["我", "私聊名", "群昵称"])


if __name__ == "__main__":
    unittest.main()
