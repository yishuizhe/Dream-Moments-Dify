from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.proactive import ProactiveService


class FakeWeChat:
    def __init__(self):
        self.contacts = ["私聊A", "群B"]
        self.sent = []
        self.pokes = []

    def send_text(self, chat, text):
        self.sent.append((chat, text))

    def poke(self, chat):
        self.pokes.append(chat)
        return True


class FakeHandler:
    def generate_proactive_message(self, chat_id, *, is_group, transcript="", mode="topic", sender_name=""):
        return f"我来冒个泡（{mode}）"


class FakeHistory:
    def get_recent_messages(self, chat_id, limit):
        return []

    def format_recent_transcript(self, chat_id, limit, within_hours=4.0):
        return ""

    def record_message(self, **kwargs):
        return None


class ProactiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.wx = FakeWeChat()

    def tearDown(self):
        self.temp.cleanup()

    def make_service(self, **overrides):
        settings = SimpleNamespace(
            enabled=True,
            private_enabled=True,
            group_enabled=True,
            min_minutes=1.0,
            max_minutes=1.0,
            poke_probability=1.0,
            chat_targets=[],
        )
        for key, value in overrides.items():
            setattr(settings, key, value)
        return ProactiveService(
            wechat=self.wx,
            message_handler=FakeHandler(),
            history_store=FakeHistory(),
            settings=settings,
            quiet_time=SimpleNamespace(start="00:00", end="00:00"),
            state_path=Path(self.temp.name) / "proactive.json",
            is_group=lambda name: name == "群B",
        )

    def test_quiet_hours_are_respected(self):
        service = self.make_service()
        self.assertFalse(service.in_quiet_hours())
        service.quiet_time = SimpleNamespace(start="00:00", end="23:59")
        self.assertTrue(service.in_quiet_hours())

    def test_group_name_is_never_used_as_a_poke_member(self):
        service = self.make_service()
        service.state["chats"]["群B"] = {"next_at": 0}
        service._tick()
        self.assertEqual(self.wx.pokes, [])
        self.assertEqual(len(self.wx.sent), 1)

    def test_disabled_service_cannot_send_even_when_tick_is_called(self):
        service = self.make_service(enabled=False)
        service.state["chats"]["群B"] = {"next_at": 0}
        service._tick()
        self.assertEqual(self.wx.pokes, [])
        self.assertEqual(self.wx.sent, [])

    def test_text_message_is_sent_when_poke_is_disabled(self):
        service = self.make_service(poke_probability=0.0)
        service.state["chats"]["私聊A"] = {"next_at": 0}
        service._tick()
        self.assertEqual(len(self.wx.sent), 1)
        self.assertEqual(self.wx.sent[0][0], "私聊A")
        self.assertIn("我来冒个泡", self.wx.sent[0][1])

    def test_chat_targets_restrict_sending_to_one_conversation(self):
        service = self.make_service(poke_probability=0.0, chat_targets=["群B"])
        service.state["chats"]["私聊A"] = {"next_at": 0}
        service.state["chats"]["群B"] = {"next_at": 0}
        service._tick()
        self.assertEqual(len(self.wx.sent), 1)
        self.assertEqual(self.wx.sent[0][0], "群B")


if __name__ == "__main__":
    unittest.main()
