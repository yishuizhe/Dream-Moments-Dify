from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.ai import dify


class DifyPrivacyTests(unittest.TestCase):
    def make_client(self) -> dify.DifyAI:
        return dify.DifyAI("test-key", "https://dify.example/v1/", max_groups=3)

    def test_success_does_not_log_chat_content_and_uses_timeout(self):
        response = Mock(status_code=200, text='{"answer": "private reply"}')
        with patch.object(dify.requests, "post", return_value=response) as post, patch.object(
            dify, "logger"
        ) as logger:
            reply = self.make_client().get_response("private message", "person-1", "system prompt")

        self.assertEqual(reply, "private reply")
        self.assertEqual(post.call_args.kwargs["timeout"], 60)
        log_text = "\n".join(str(call) for call in logger.mock_calls)
        self.assertNotIn("private message", log_text)
        self.assertNotIn("private reply", log_text)
        self.assertNotIn("system prompt", log_text)

    def test_error_does_not_log_provider_response_body(self):
        response = Mock(status_code=500, text="provider returned private content")
        with patch.object(dify.requests, "post", return_value=response), patch.object(
            dify, "logger"
        ) as logger:
            self.make_client().get_response("private message", "person-1", "system prompt")

        log_text = "\n".join(str(call) for call in logger.mock_calls)
        self.assertNotIn("private message", log_text)
        self.assertNotIn("provider returned private content", log_text)


if __name__ == "__main__":
    unittest.main()
