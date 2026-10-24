from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.moments import MomentsService


class FakeWeChat:
    def __init__(self, feed):
        self.feed = feed
        self.likes = []
        self.comments = []
        self.posts = []

    def moment_feed(self, limit=20):
        return list(self.feed)

    def like_moment(self, publisher):
        self.likes.append(publisher)
        return True

    def comment_moment(self, publisher, text):
        self.comments.append((publisher, text))
        return True

    def publish_moment(self, text, images=None):
        self.posts.append(text)
        return True


class FakeHandler:
    def generate_auxiliary_text(self, prompt, *, context_key, is_group=True, task_type="moment"):
        return "这鱼看着真香"


class FakeHistory:
    def __init__(self):
        self.people = []

    def register_person(self, person_id, display_name="", **kwargs):
        self.people.append((person_id, display_name, kwargs.get("chat_id")))
        return person_id

    def get_person_profile(self, person_id):
        for pid, name, _chat in self.people:
            if pid == person_id:
                return {"person_id": pid, "display_name": name, "aliases": [name], "chats": []}
        return None

    def format_recent_transcript(self, *args, **kwargs):
        return ""


class MomentsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        now = int(time.time())
        self.feed = [{
            "id": "42", "username": "wxid_alice", "nickname": "Alice",
            "text": "今天吃了开心大米饭", "create_time": now,
        }]
        self.wx = FakeWeChat(self.feed)
        self.history = FakeHistory()

    def tearDown(self):
        self.temp.cleanup()

    def make_service(self, **overrides):
        values = dict(
            enabled=True,
            whitelist_only=True,
            like_probability=1.0,
            comment_probability=1.0,
            publish_enabled=True,
            publish_probability=1.0,
            max_actions_per_run=3,
            browse_interval_minutes=1.0,
        )
        values.update(overrides)
        return MomentsService(
            wechat=self.wx,
            message_handler=FakeHandler(),
            history_store=self.history,
            settings=SimpleNamespace(**values),
            state_path=Path(self.temp.name) / "moments.json",
            contacts=["Alice"],
        )

    def test_like_and_comment_whitelisted_post(self):
        service = self.make_service()
        service._tick()
        self.assertEqual(self.wx.likes, ["Alice"])
        self.assertEqual(self.wx.comments[0], ("Alice", "这鱼看着真香"))
        self.assertEqual(self.history.people[0][0], "person:wxid_alice")

    def test_non_whitelisted_author_is_skipped(self):
        self.wx.feed[0]["nickname"] = "陌生人"
        service = self.make_service()
        service._tick()
        self.assertEqual(self.wx.likes, [])
        self.assertEqual(self.wx.comments, [])

    def test_publish_respects_enabled_switch(self):
        service = self.make_service(publish_enabled=False, like_probability=0, comment_probability=0)
        service._tick()
        self.assertEqual(self.wx.posts, [])


if __name__ == "__main__":
    unittest.main()
