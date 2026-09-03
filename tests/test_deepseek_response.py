from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.ai.deepseek import DeepSeekAI


class DeepSeekResponseValidationTests(unittest.TestCase):
    def setUp(self):
        self.ai = DeepSeekAI(
            api_key="test-key",
            base_url="https://example.invalid/v1/",
            model="custom-chat-model",
            max_token=32,
            temperature=0.1,
            max_groups=2,
        )

    def test_accepts_minimal_openai_compatible_response(self):
        response = {
            "choices": [
                {"message": {"role": "assistant", "content": "OK"}}
            ]
        }
        self.assertTrue(self.ai._validate_response(response))

    def test_accepts_provider_specific_optional_fields(self):
        response = {
            "model": "vendor/custom-model",
            "choices": [
                {
                    "finish_reason": "provider_specific_reason",
                    "message": {"content": "有效回复"},
                }
            ],
            "usage": {
                "prompt_tokens": 2,
                "completion_tokens": 2,
                "total_tokens": 99,
            },
        }
        self.assertTrue(self.ai._validate_response(response))

    def test_rejects_response_without_assistant_text(self):
        self.assertFalse(self.ai._validate_response({"choices": []}))
        self.assertFalse(
            self.ai._validate_response(
                {"choices": [{"message": {"content": "   "}}]}
            )
        )

    def test_zhipu_chat_disables_thinking_to_preserve_reply_tokens(self):
        ai = DeepSeekAI(
            api_key="test-key",
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            model="glm-4.7-flash",
            max_token=64,
            temperature=0.2,
            max_groups=2,
        )
        response = Mock()
        response.model_dump.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "正常"}}]
        }
        response.choices = [Mock(message=Mock(content="正常"))]
        ai.client.chat.completions.create = Mock(return_value=response)

        self.assertEqual(ai.get_response("你好", "u", "system"), "正常")
        request = ai.client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["extra_body"], {"thinking": {"type": "disabled"}})

    def test_non_zhipu_chat_does_not_receive_vendor_specific_thinking(self):
        response = Mock()
        response.model_dump.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "OK"}}]
        }
        response.choices = [Mock(message=Mock(content="OK"))]
        self.ai.client.chat.completions.create = Mock(return_value=response)

        self.assertEqual(self.ai.get_response("hello", "u", "system"), "OK")
        request = self.ai.client.chat.completions.create.call_args.kwargs
        self.assertNotIn("extra_body", request)

    def test_deepseek_v4_flash_disables_thinking_for_fast_chat(self):
        ai = DeepSeekAI(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            max_token=64,
            temperature=0.2,
            max_groups=2,
        )
        response = Mock()
        response.model_dump.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "收到"}}]
        }
        response.choices = [Mock(message=Mock(content="收到"))]
        ai.client.chat.completions.create = Mock(return_value=response)

        self.assertEqual(ai.get_response("在吗", "u", "system"), "收到")
        request = ai.client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["extra_body"], {"thinking": {"type": "disabled"}})


if __name__ == "__main__":
    unittest.main()
