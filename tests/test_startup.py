from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config import Config
from handlers.image import ImageHandler


class StartupCompatibilityTests(unittest.TestCase):
    def test_old_config_without_wechat_or_dify_fields_uses_defaults(self):
        template = json.loads(
            (SRC / "config" / "config.json.template").read_text(encoding="utf-8")
        )
        template["categories"].pop("wechat_settings", None)
        llm = template["categories"]["llm_settings"]["settings"]
        llm.pop("dify_api_key", None)
        llm.pop("dify_base_url", None)
        llm.pop("provider", None)
        llm.pop("model", None)
        llm.pop("max_tokens", None)
        llm.pop("temperature", None)

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            template_path = Path(temp_dir) / "config.json.template"
            config_path.write_text(json.dumps(template), encoding="utf-8")
            template_path.write_text(json.dumps(template), encoding="utf-8")

            class TempConfig(Config):
                @property
                def config_path(self) -> str:
                    return str(config_path)

                @property
                def config_template_path(self) -> str:
                    return str(template_path)

            loaded = TempConfig()

        self.assertEqual(loaded.wechat.poll_interval, 2.0)
        self.assertEqual(loaded.wechat.history_size, 50)
        self.assertFalse(loaded.wechat.process_existing_on_start)
        self.assertEqual(loaded.llm.dify_api_key, "")
        self.assertEqual(loaded.llm.dify_base_url, "https://api.dify.ai/v1/")
        self.assertEqual(loaded.llm.provider, "deepseek")
        self.assertEqual(loaded.llm.model, "deepseek-chat")
        self.assertEqual(loaded.llm.max_tokens, 2000)
        self.assertEqual(loaded.llm.temperature, 1.0)

    def test_string_boolean_wechat_settings_are_parsed_safely(self):
        template = json.loads(
            (SRC / "config" / "config.json.template").read_text(encoding="utf-8")
        )
        settings = template["categories"]["wechat_settings"]["settings"]
        settings["process_existing_on_start"] = {"value": "false"}
        settings["exact_match"] = {"value": "true"}

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            template_path = Path(temp_dir) / "config.json.template"
            config_path.write_text(json.dumps(template), encoding="utf-8")
            template_path.write_text(json.dumps(template), encoding="utf-8")

            class TempConfig(Config):
                @property
                def config_path(self) -> str:
                    return str(config_path)

                @property
                def config_template_path(self) -> str:
                    return str(template_path)

            loaded = TempConfig()

        self.assertFalse(loaded.wechat.process_existing_on_start)
        self.assertTrue(loaded.wechat.exact_match)

    def test_group_messages_are_skipped_when_bot_name_is_unavailable(self):
        import main

        class FakeWeChat:
            def get_my_name(self):
                return ""

        class FakeMessageHandler:
            def add_to_queue(self, **kwargs):
                raise AssertionError("group message should have been skipped")

        class FakeMessage:
            sender = "group-member"
            content = "hello"

        bot = main.ChatBot(FakeMessageHandler(), object(), FakeWeChat())
        bot.handle_wxauto_message(FakeMessage(), "test-group", is_group=True)
        self.assertEqual(bot.user_queues, {})

    def test_wechat_startup_does_not_open_every_contact_for_validation(self):
        import main

        with patch.object(
            main.wechat_adapter, "is_online", return_value=True
        ), patch.object(main.wechat_adapter, "validate_contacts") as validate:
            result = main.initialize_wx_listener()

        self.assertIs(result, main.wechat_adapter)
        validate.assert_not_called()

    def test_fractional_auto_message_hours_are_converted_to_integer_seconds(self):
        import main

        with patch("main.random.randint", return_value=7200) as randint:
            result = main.get_random_countdown_time()

        self.assertEqual(result, 7200)
        lower, upper = randint.call_args.args
        self.assertIsInstance(lower, int)
        self.assertIsInstance(upper, int)
        self.assertEqual((lower, upper), (3600, 10800))

    def test_image_handler_does_not_require_openai_credentials_at_startup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            handler = ImageHandler(
                root_dir=temp_dir,
                api_key="",
                base_url="",
                image_model="test-model",
            )

            self.assertIsNone(handler.text_ai)
            with self.assertRaisesRegex(RuntimeError, "llm_settings.api_key"):
                handler._get_text_ai()


if __name__ == "__main__":
    unittest.main()
