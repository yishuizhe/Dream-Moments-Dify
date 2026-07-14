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

from services.database import Base, HistoryStore, make_identity_key


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


if __name__ == "__main__":
    unittest.main()
