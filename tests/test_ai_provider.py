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
from utils.reply_formatter import FORMAT_MARKER


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
        client.get_response.assert_called_once()
        args = client.get_response.call_args.args
        self.assertEqual(args[:2], ("hello", "user-1"))
        self.assertIn("system", args[2])
        self.assertIn(FORMAT_MARKER, args[2])

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


    @patch("handlers.message.time.sleep")
    @patch("handlers.message.DeepSeekAI")
    def test_long_reply_is_split_into_multiple_bubbles(self, client_cls, sleep_mock):
        client_cls.return_value.get_response.return_value = (
            "\u591c\u73ed\u8981\u5230\u51e0\u70b9\u5440\u90a3\u73b0\u5728\u5077\u5077\u72af\u56f0"
            "\u8fd8\u662f\u7cbe\u795e\u8fd8\u4e0d\u9519 \u6211\u5e2e\u4f60\u76ef\u7740\u65f6\u95f4\u63d0\u9192\u4f60"
            "\u6d3b\u52a8\u4e00\u4e0b\u597d\u5566\u4e0d\u8fc7\u8bf4\u8d77\u6765 \u4f60\u5de5\u4f5c\u65f6\u4f1a\u559d\u8336"
            "\u8fd8\u662f\u5496\u5561\u63d0\u795e"
        )
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
        handler.user_queues["friend"] = {
            "messages": ["hello"],
            "sender_name": "friend",
            "username": "friend-id",
            "is_group": False,
        }

        handler.process_messages("friend")

        bubbles = [call.kwargs["msg"] for call in wechat.SendMsg.call_args_list]
        self.assertEqual(len(bubbles), 4)
        self.assertTrue(all(bubble[-1] in "\u3002\uff1f\uff01" for bubble in bubbles))
        self.assertEqual(sleep_mock.call_count, 3)

    def test_provider_requires_matching_credentials(self):
        with self.assertRaisesRegex(ValueError, "DEEPSEEK_API_KEY"):
            self.make_handler(api_key="")


if __name__ == "__main__":
    unittest.main()
