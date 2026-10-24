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

from services.database import Base, HistoryStore, person_key_for


class PersonIdentityTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.store = HistoryStore(sessionmaker(bind=engine))

    def test_wxid_produces_one_person_key(self):
        self.assertEqual(person_key_for("wxid_abc", "小明"), "person:wxid_abc")
        self.assertEqual(
            person_key_for("wxid_abc", "群里的别名"), "person:wxid_abc"
        )

    def test_alias_rule_wins_over_display_names(self):
        key = person_key_for("", "阿哲", ["本人=阿哲=小哲"])
        self.assertEqual(key, "person:本人")

    def test_memory_merges_across_private_and_group(self):
        key = person_key_for("wxid_abc", "小明")
        self.store.remember_user_message(
            identity_key=key, chat_id="private:wxid_abc", sender_id="wxid_abc",
            sender_name="小明", content="我喜欢喝绿茶",
        )
        self.store.remember_user_message(
            identity_key=key, chat_id="group-1", sender_id="wxid_abc",
            sender_name="小明", content="我养了一只猫",
        )
        items = self.store.get_memory_items_for_person(key, sender_id="wxid_abc")
        self.assertIn("我喜欢喝绿茶", items)
        self.assertIn("我养了一只猫", items)

    def test_legacy_group_memory_is_visible_to_person(self):
        self.store.remember_user_message(
            identity_key="group:g1:member:wxid_abc",
            chat_id="g1", sender_id="wxid_abc", sender_name="小明",
            content="我上周去爬山了",
        )
        items = self.store.get_memory_items_for_person(
            "person:wxid_abc", sender_id="wxid_abc", sender_name="小明"
        )
        self.assertIn("我上周去爬山了", items)

    def test_profile_collects_chats_and_aliases(self):
        key = person_key_for("wxid_abc", "小明")
        self.store.register_person(key, "小明", chat_id="p1", chat_name="小明", is_group=False)
        self.store.register_person(key, "小明", chat_id="g1", chat_name="测试群", is_group=True, aliases=["阿明"])
        profile = self.store.get_person_profile(key)
        self.assertIsNotNone(profile)
        self.assertIn("阿明", profile["aliases"])
        self.assertEqual({item["chat_id"] for item in profile["chats"]}, {"p1", "g1"})

    def test_clear_person_memory_removes_legacy_rows(self):
        self.store.remember_user_message(
            identity_key="private:wxid_abc", chat_id="p", sender_id="wxid_abc",
            sender_name="小明", content="我喜欢喝绿茶",
        )
        self.store.clear_person_memory("person:wxid_abc", sender_id="wxid_abc")
        self.assertEqual(self.store.get_memory_items("private:wxid_abc"), [])


if __name__ == "__main__":
    unittest.main()
