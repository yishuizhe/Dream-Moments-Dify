from __future__ import annotations

import sys
import hashlib
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_config_web
from src.config import config


class WebConfigTests(unittest.TestCase):
    def test_password_hashes_are_salted_and_legacy_hashes_upgrade(self):
        first = run_config_web.hash_password("correct horse battery staple")
        second = run_config_web.hash_password("correct horse battery staple")

        self.assertTrue(first.startswith("scrypt$"))
        self.assertNotEqual(first, second)
        self.assertEqual(
            run_config_web.verify_password("correct horse battery staple", first),
            (True, None),
        )
        self.assertEqual(run_config_web.verify_password("wrong", first), (False, None))

        legacy = hashlib.sha256(b"legacy-password").hexdigest()
        valid, upgraded = run_config_web.verify_password("legacy-password", legacy)
        self.assertTrue(valid)
        self.assertIsNotNone(upgraded)
        self.assertTrue(upgraded.startswith("scrypt$"))

    def test_avatar_paths_cannot_escape_avatar_directory(self):
        safe = run_config_web.get_avatar_file("MONO")
        self.assertEqual(safe.name, "avatar.md")
        self.assertEqual(safe.parent.name, "MONO")

        for unsafe in ("../config", "..", "nested/avatar", "nested\\avatar", ""):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                run_config_web.get_avatar_file(unsafe)

    def test_polling_settings_are_exposed_and_saved(self):
        groups = run_config_web.parse_config_groups()
        self.assertIn("微信轮询配置", groups)
        for key in (
            "WECHAT_POLL_INTERVAL",
            "WECHAT_HISTORY_SIZE",
            "WECHAT_STATE_FILE",
            "WECHAT_PROCESS_EXISTING",
            "WECHAT_EXACT_MATCH",
        ):
            self.assertIn(key, groups["微信轮询配置"])
        self.assertIn("IDENTITY_ALIASES", groups["Prompt配置"])
        self.assertIn("图像生成配置", groups)
        for key in ("IMAGE_ENABLED", "IMAGE_API_KEY", "IMAGE_BASE_URL", "IMAGE_MODEL"):
            self.assertIn(key, groups["图像生成配置"])
        self.assertIn("Operit 手机控制", groups)
        for key in (
            "OPERIT_ENABLED",
            "OPERIT_BASE_URL",
            "OPERIT_BEARER_TOKEN",
            "OPERIT_ALLOWED_SENDERS",
            "OPERIT_ALLOW_GROUPS",
            "OPERIT_REQUIRE_CONFIRMATION",
        ):
            self.assertIn(key, groups["Operit 手机控制"])
        self.assertIn("娜娜自研手机端", groups)
        for key in (
            "NANA_PHONE_ENABLED",
            "NANA_PHONE_BASE_URL",
            "NANA_PHONE_PAIRING_TOKEN",
            "NANA_PHONE_TIMEOUT",
        ):
            self.assertIn(key, groups["娜娜自研手机端"])
        self.assertIn("AI 备用线路", groups)
        for index in range(1, 4):
            for suffix in (
                "ENABLED", "NAME", "BASE_URL", "API_KEY", "MODEL",
                "COMPLEX_ONLY", "MAX_TOKENS",
            ):
                self.assertIn(f"FALLBACK_{index}_{suffix}", groups["AI 备用线路"])

        submitted = {
            "LISTEN_LIST": ["好友"],
            "WECHAT_POLL_INTERVAL": 1.5,
            "WECHAT_HISTORY_SIZE": 80,
            "WECHAT_STATE_FILE": "data/custom_state.json",
            "WECHAT_PROCESS_EXISTING": True,
            "WECHAT_EXACT_MATCH": False,
            "AI_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "direct-key",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1/",
            "MODEL": "deepseek-chat",
            "MAX_TOKEN": 4096,
            "TEMPERATURE": 0.8,
            "FALLBACK_1_ENABLED": True,
            "FALLBACK_1_NAME": "free-backup",
            "FALLBACK_1_API_KEY": "backup-key",
            "FALLBACK_1_BASE_URL": "https://free.example.test/v1",
            "FALLBACK_1_MODEL": "free-model",
            "FALLBACK_1_COMPLEX_ONLY": False,
            "FALLBACK_1_MAX_TOKENS": 700,
            "DIFY_API_KEY": "test-key",
            "DIFY_BASE_URL": "https://api.dify.ai/v1/",
            "IMAGE_ENABLED": "true",
            "IMAGE_API_KEY": "image-test-key",
            "IMAGE_BASE_URL": "https://images.example.test/v1/",
            "IMAGE_MODEL": "example-image-model",
            "TEMP_IMAGE_DIR": "data/images/generated",
            "IDENTITY_ALIASES": ["我=私聊名|群昵称"],
            "OPERIT_ENABLED": True,
            "OPERIT_BASE_URL": "http://phone.test:8094",
            "OPERIT_BEARER_TOKEN": "operit-test-token",
            "OPERIT_ALLOWED_SENDERS": ["owner"],
            "OPERIT_ALLOWED_CHATS": ["owner-chat"],
            "OPERIT_ALLOW_GROUPS": False,
            "OPERIT_PREFIXES": ["手机：", "/phone "],
            "OPERIT_TIMEOUT": 240,
            "OPERIT_SHOW_FLOATING": True,
            "OPERIT_REQUIRE_CONFIRMATION": True,
            "OPERIT_CONFIRM_TTL": 90,
            "NANA_PHONE_ENABLED": True,
            "NANA_PHONE_BASE_URL": "http://phone.test:8765",
            "NANA_PHONE_PAIRING_TOKEN": "nana-phone-test-token-123456789012345",
            "NANA_PHONE_TIMEOUT": 15,
        }

        with patch.object(config, "save_config", return_value=True) as save_mock, patch(
            "run_config_web.importlib.reload"
        ):
            self.assertTrue(run_config_web.save_config(submitted))

        payload = save_mock.call_args.args[0]
        settings = payload["categories"]["wechat_settings"]["settings"]
        self.assertEqual(settings["poll_interval"]["value"], 1.5)
        self.assertEqual(settings["history_size"]["value"], 80)
        self.assertEqual(settings["state_file"]["value"], "data/custom_state.json")
        self.assertTrue(settings["process_existing_on_start"]["value"])
        self.assertFalse(settings["exact_match"]["value"])

        llm = payload["categories"]["llm_settings"]["settings"]
        self.assertEqual(llm["provider"]["value"], "deepseek")
        self.assertEqual(llm["model"]["value"], "deepseek-chat")
        self.assertEqual(llm["max_tokens"]["value"], 4096)
        self.assertEqual(llm["temperature"]["value"], 0.8)
        self.assertTrue(llm["fallback_1_enabled"]["value"])
        self.assertEqual(llm["fallback_1_name"]["value"], "free-backup")
        self.assertEqual(llm["fallback_1_api_key"]["value"], "backup-key")
        self.assertEqual(llm["fallback_1_base_url"]["value"], "https://free.example.test/v1")
        self.assertEqual(llm["fallback_1_model"]["value"], "free-model")
        self.assertFalse(llm["fallback_1_complex_only"]["value"])
        self.assertEqual(llm["fallback_1_max_tokens"]["value"], 700)

        image = payload["categories"]["media_settings"]["settings"]["image_generation"]
        self.assertTrue(image["enabled"]["value"])
        self.assertEqual(image["api_key"]["value"], "image-test-key")
        self.assertEqual(image["base_url"]["value"], "https://images.example.test/v1/")
        self.assertEqual(image["model"]["value"], "example-image-model")
        self.assertEqual(image["temp_dir"]["value"], "data/images/generated")

        context = payload["categories"]["behavior_settings"]["settings"]["context"]
        self.assertEqual(context["identity_aliases"]["value"], ["我=私聊名|群昵称"])

        operit = payload["categories"]["operit_settings"]["settings"]
        self.assertTrue(operit["enabled"]["value"])
        self.assertEqual(operit["base_url"]["value"], "http://phone.test:8094")
        self.assertEqual(operit["bearer_token"]["value"], "operit-test-token")
        self.assertEqual(operit["allowed_senders"]["value"], ["owner"])
        self.assertFalse(operit["allow_group_commands"]["value"])
        self.assertTrue(operit["require_confirmation"]["value"])

        nana_phone = payload["categories"]["nana_phone_settings"]["settings"]
        self.assertTrue(nana_phone["enabled"]["value"])
        self.assertEqual(nana_phone["base_url"]["value"], "http://phone.test:8765")
        self.assertEqual(nana_phone["pairing_token"]["value"], "nana-phone-test-token-123456789012345")
        self.assertEqual(nana_phone["request_timeout_seconds"]["value"], 15)

    def test_partial_save_preserves_unsubmitted_settings(self):
        original_model = config.llm.model
        original_url = config.llm.base_url
        original_avatar = config.behavior.context.avatar_dir

        with patch.object(config, "save_config", return_value=True) as save_mock, patch(
            "run_config_web.importlib.reload"
        ):
            self.assertTrue(run_config_web.save_config({"LISTEN_LIST": ["仅更新监听"]}))

        payload = save_mock.call_args.args[0]
        llm = payload["categories"]["llm_settings"]["settings"]
        context = payload["categories"]["behavior_settings"]["settings"]["context"]
        self.assertEqual(llm["model"]["value"], original_model)
        self.assertEqual(llm["base_url"]["value"], original_url)
        self.assertEqual(context["avatar_dir"]["value"], original_avatar)


if __name__ == "__main__":
    unittest.main()
