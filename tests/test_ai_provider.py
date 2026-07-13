from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from handlers.message import MessageHandler


class AIProviderTests(unittest.TestCase):
    def make_handler(self, **overrides):
        values = {
            "root_dir": tempfile.gettempdir(),
            "api_key": "direct-key",
            "base_url": "https://api.deepseek.com/v1/",
            "max_groups": 5,
            "robot_name": "bot",
            "prompt_content": "system",
            "image_handler": Mock(),
            "emoji_handler": Mock(),
            "voice_handler": Mock(),
            "dify_api_key": "dify-key",
            "dify_base_url": "https://api.dify.ai/v1/",
            "wechat": Mock(),
            "ai_provider": "deepseek",
            "model": "deepseek-chat",
            "max_tokens": 4096,
            "temperature": 0.8,
        }
        values.update(overrides)
        return MessageHandler(**values)

    @patch("handlers.message.DeepSeekAI")
    def test_deepseek_provider_uses_direct_openai_compatible_client(self, client_cls):
        client = client_cls.return_value
        client.get_response.return_value = "ok"

        handler = self.make_handler()

        client_cls.assert_called_once_with(
            api_key="direct-key",
            base_url="https://api.deepseek.com/v1/",
            model="deepseek-chat",
            max_token=4096,
            temperature=0.8,
            max_groups=5,
        )
        self.assertEqual(handler.get_api_response("hello", "user-1"), "ok")
        client.get_response.assert_called_once_with("hello", "user-1", "system")

    @patch("handlers.message.DifyAI")
    def test_dify_provider_remains_available(self, client_cls):
        handler = self.make_handler(ai_provider="dify")

        client_cls.assert_called_once_with(
            dify_api_key="dify-key",
            dify_base_url="https://api.dify.ai/v1/",
            max_groups=5,
        )
        self.assertEqual(handler.ai_provider, "dify")

    @patch("handlers.message.DeepSeekAI")
    def test_group_reply_does_not_mention_trigger_user(self, client_cls):
        client_cls.return_value.get_response.return_value = "plain reply"
        wechat = Mock()
        image_handler = Mock()
        image_handler.is_random_image_request.return_value = False
        image_handler.is_image_generation_request.return_value = False
        voice_handler = Mock()
        voice_handler.is_voice_request.return_value = False
        emoji_handler = Mock()
        emoji_handler.emotion_map = {}
        handler = self.make_handler(
            wechat=wechat,
            image_handler=image_handler,
            voice_handler=voice_handler,
            emoji_handler=emoji_handler,
        )
        handler.save_message = Mock()
        handler.user_queues["group"] = {
            "messages": ["hello"],
            "sender_name": "member",
            "username": "member-id",
            "is_group": True,
        }

        handler.process_messages("group")

        wechat.SendMsg.assert_called_once_with(msg="plain reply", who="group")

    def test_provider_requires_matching_credentials(self):
        with self.assertRaisesRegex(ValueError, "DEEPSEEK_API_KEY"):
            self.make_handler(api_key="")


if __name__ == "__main__":
    unittest.main()
