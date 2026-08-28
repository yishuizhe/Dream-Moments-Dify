from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.ai.failover import FailoverAI


class AIFailoverTests(unittest.TestCase):
    def routes(self):
        return [
            {"name": "free-primary", "api_key": "a", "base_url": "https://a/v1", "model": "free"},
            {"name": "free-backup", "api_key": "b", "base_url": "https://b/v1", "model": "backup"},
        ]

    @patch("services.ai.failover.DeepSeekAI")
    def test_failure_switches_route_and_synchronizes_context(self, client_cls):
        primary = Mock()
        primary.get_response.side_effect = RuntimeError("429")
        primary.chat_contexts = {}
        backup = Mock()
        backup.get_response.return_value = "ok"
        backup.chat_contexts = {"u": [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "ok"}]}
        client_cls.side_effect = [primary, backup]
        ai = FailoverAI(self.routes(), max_groups=4, max_tokens=800, temperature=0.8)

        self.assertEqual(ai.get_response("hello", "u", "system"), "ok")
        self.assertEqual(ai.active_route_name, "free-backup")
        self.assertEqual(primary.chat_contexts["u"][-1]["content"], "ok")

    @patch("services.ai.failover.DeepSeekAI")
    def test_complex_only_paid_route_is_not_used_for_normal_chat(self, client_cls):
        primary = Mock()
        primary.get_response.side_effect = RuntimeError("offline")
        primary.chat_contexts = {}
        paid = Mock()
        paid.get_response.return_value = "paid"
        paid.chat_contexts = {"u": []}
        client_cls.side_effect = [primary, paid]
        routes = [self.routes()[0], {
            "name": "paid", "api_key": "p", "base_url": "https://p/v1",
            "model": "paid", "complex_only": True,
        }]
        ai = FailoverAI(routes, max_groups=4, max_tokens=800, temperature=0.8, cooldown_seconds=5)

        normal = ai.get_response("今天吃什么", "u", "system")
        self.assertNotEqual(normal, "paid")
        paid.get_response.assert_not_called()

        # Use a fresh router because the primary is now in cooldown.
        primary2 = Mock()
        primary2.get_response.side_effect = RuntimeError("offline")
        primary2.chat_contexts = {}
        paid2 = Mock()
        paid2.get_response.return_value = "paid"
        paid2.chat_contexts = {"u": [{"role": "assistant", "content": "paid"}]}
        client_cls.side_effect = [primary2, paid2]
        ai = FailoverAI(routes, max_groups=4, max_tokens=800, temperature=0.8)
        self.assertEqual(ai.get_response("请做一份完整方案并深入分析", "u", "system"), "paid")


if __name__ == "__main__":
    unittest.main()
