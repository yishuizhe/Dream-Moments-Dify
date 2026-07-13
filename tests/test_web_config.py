from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_config_web
from src.config import config


class WebConfigTests(unittest.TestCase):
    def test_polling_settings_are_exposed_and_saved(self):
        groups = run_config_web.parse_config_groups()
        self.assertIn("微信轮询配置", groups)
        self.assertIn("WECHAT_POLL_INTERVAL", groups["微信轮询配置"])

        submitted = {
            "LISTEN_LIST": ["好友"],
            "WECHAT_POLL_INTERVAL": 1.5,
            "AI_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "direct-key",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1/",
            "MODEL": "deepseek-chat",
            "MAX_TOKEN": 4096,
            "TEMPERATURE": 0.8,
            "DIFY_API_KEY": "test-key",
            "DIFY_BASE_URL": "https://api.dify.ai/v1/",
        }

        with patch.object(config, "save_config", return_value=True) as save_mock, patch(
            "run_config_web.importlib.reload"
        ):
            self.assertTrue(run_config_web.save_config(submitted))

        payload = save_mock.call_args.args[0]
        settings = payload["categories"]["wechat_settings"]["settings"]
        self.assertEqual(settings["poll_interval"]["value"], 1.5)
        self.assertEqual(
            settings["history_size"]["value"], config.wechat.history_size
        )
        self.assertEqual(settings["state_file"]["value"], config.wechat.state_file)
        self.assertEqual(
            settings["process_existing_on_start"]["value"],
            config.wechat.process_existing_on_start,
        )
        self.assertEqual(
            settings["exact_match"]["value"], config.wechat.exact_match
        )

        llm = payload["categories"]["llm_settings"]["settings"]
        self.assertEqual(llm["provider"]["value"], "deepseek")
        self.assertEqual(llm["model"]["value"], "deepseek-chat")
        self.assertEqual(llm["max_tokens"]["value"], 4096)
        self.assertEqual(llm["temperature"]["value"], 0.8)


if __name__ == "__main__":
    unittest.main()
