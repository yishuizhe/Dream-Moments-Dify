from __future__ import annotations

import sys
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from handlers.message import MessageHandler


class FakeWX:
    def __init__(self):
        self.sent = []

    def SendMsg(self, msg, who):
        self.sent.append((who, msg))


class FakeHistory:
    def __init__(self):
        self.recorded = []

    def get_memory_items(self, identity_key):
        return ["B likes coffee"] if identity_key.endswith("member:b-id") else []

    def record_message(self, **kwargs):
        self.recorded.append(kwargs)


class GroupIdentityTests(unittest.TestCase):
    def test_group_batch_keeps_each_sender_label_and_latest_member_memory(self):
        handler = MessageHandler.__new__(MessageHandler)
        handler.queue_lock = threading.Lock()
        handler.user_queues = {
            "g": {
                "is_group": True,
                "messages": [
                    {"content": "first", "sender_name": "A", "sender_id": "a-id", "timestamp": datetime(2026, 7, 14, 9, 0)},
                    {"content": "second", "sender_name": "B", "sender_id": "b-id", "timestamp": datetime(2026, 7, 14, 9, 1)},
                ],
            }
        }
        handler.prompt_content = "persona"
        handler.robot_name = "Bot"
        handler.history_store = FakeHistory()
        handler.ai = Mock()
        handler.ai.get_response.return_value = "ok"
        handler.wx = FakeWX()
        handler.voice_handler = Mock()
        handler.voice_handler.is_voice_request.return_value = False
        handler.image_handler = Mock()
        handler.image_handler.is_random_image_request.return_value = False
        handler.image_handler.is_image_generation_request.return_value = False
        handler.emoji_handler = Mock()
        handler.emoji_handler.emotion_map = {}
        handler.save_message = Mock()

        handler.process_messages("g")

        message, context_key, system_prompt = handler.ai.get_response.call_args.args
        self.assertIn("A\uff1afirst", message)
        self.assertIn("B\uff1asecond", message)
        self.assertEqual(context_key, "group:g")
        self.assertIn("\u5f53\u524d\u89e6\u53d1\u8005\uff1aB", system_prompt)
        self.assertIn("B likes coffee", system_prompt)
        self.assertEqual(handler.wx.sent, [("g", "ok")])


if __name__ == "__main__":
    unittest.main()
