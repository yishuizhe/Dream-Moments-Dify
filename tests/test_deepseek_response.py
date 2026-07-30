from __future__ import annotations

import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
