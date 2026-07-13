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


    def test_group_plugin_command_needs_no_at_and_bypasses_llm_queue(self):
        import main

        class FakeWeChat:
            def __init__(self):
                self.sent = []

            def get_my_name(self):
                return "\u673a\u5668\u4eba"

            def send_text(self, chat_name, text):
                self.sent.append((chat_name, text))

        class FakePluginManager:
            def __init__(self):
                self.calls = []

            def handle_group_message(self, **message):
                self.calls.append(message)
                return "\u3010\u4eca\u65e5\u6c34\u738b\u3011"

        class FakeMessage:
            sender = "\u7fa4\u6210\u5458"
            content = "\u4eca\u65e5\u6c34\u738b"
            is_self = False

        class FakeMessageHandler:
            def add_to_queue(self, **kwargs):
                raise AssertionError("plugin command must bypass the LLM queue")

        wechat = FakeWeChat()
        plugins = FakePluginManager()
        bot = main.ChatBot(FakeMessageHandler(), object(), wechat, plugin_manager=plugins)
        bot.handle_wxauto_message(FakeMessage(), "\u6d4b\u8bd5\u7fa4", is_group=True)

        self.assertEqual(wechat.sent, [("\u6d4b\u8bd5\u7fa4", "\u3010\u4eca\u65e5\u6c34\u738b\u3011")])
        self.assertEqual(len(plugins.calls), 1)
        self.assertEqual(bot.user_queues, {})

    def test_plain_group_message_is_observed_by_plugin_without_triggering_llm(self):
        import main

        class FakeWeChat:
            def get_my_name(self):
                return "\u673a\u5668\u4eba"

        class FakePluginManager:
            def __init__(self):
                self.calls = []

            def handle_group_message(self, **message):
                self.calls.append(message)
                return None

        class FakeMessage:
            sender = "\u7fa4\u6210\u5458"
            content = "\u666e\u901a\u7fa4\u804a"
            is_self = False

        class FakeMessageHandler:
            def add_to_queue(self, **kwargs):
                raise AssertionError("untriggered group message must not reach the LLM")

        plugins = FakePluginManager()
        bot = main.ChatBot(FakeMessageHandler(), object(), FakeWeChat(), plugin_manager=plugins)
        bot.handle_wxauto_message(FakeMessage(), "\u6d4b\u8bd5\u7fa4", is_group=True)

        self.assertEqual(len(plugins.calls), 1)
        self.assertEqual(plugins.calls[0]["content"], "\u666e\u901a\u7fa4\u804a")
        self.assertEqual(bot.user_queues, {})

    def test_quote_reply_to_bot_triggers_group_ai_without_at(self):
        import main

        class FakeTimer:
            def __init__(self, *args, **kwargs):
                self.started = False

            def start(self):
                self.started = True

            def cancel(self):
                pass

        class FakeWeChat:
            def get_my_name(self):
                return "\u673a\u5668\u4eba"

        class FakePluginManager:
            def handle_group_message(self, **message):
                return None

        class FakeMessage:
            sender = "\u7fa4\u6210\u5458"
            content = "\u7ee7\u7eed\u8bf4"
            is_self = False
            is_quote = True
            quoted_sender = "\u673a\u5668\u4eba"
            quoted_content = "\u4e0a\u4e00\u6761\u56de\u590d"

        class FakeMessageHandler:
            def add_to_queue(self, **kwargs):
                pass

        with patch.object(main.threading, "Timer", FakeTimer):
            bot = main.ChatBot(
                FakeMessageHandler(), object(), FakeWeChat(), plugin_manager=FakePluginManager()
            )
            bot.handle_wxauto_message(FakeMessage(), "\u6d4b\u8bd5\u7fa4", is_group=True)

        self.assertIn("\u6d4b\u8bd5\u7fa4", bot.user_queues)
        self.assertIn("\u7ee7\u7eed\u8bf4", bot.user_queues["\u6d4b\u8bd5\u7fa4"]["messages"][0])

    def test_quote_reply_matches_recent_bot_text_when_group_alias_differs(self):
        import main

        class FakeTimer:
            def __init__(self, *args, **kwargs):
                self.started = False

            def start(self):
                self.started = True

            def cancel(self):
                pass

        class FakeWeChat:
            def get_my_name(self):
                return "机器人"

            def is_recent_sent_text(self, chat_name, text):
                return chat_name == "测试群" and text == "上一条回复"

        class FakePluginManager:
            def handle_group_message(self, **message):
                return None

        class FakeMessage:
            sender = "群成员"
            content = "继续说"
            is_self = False
            is_quote = True
            quoted_sender = "机器人在本群的昵称"
            quoted_content = "上一条回复"

        class FakeMessageHandler:
            def add_to_queue(self, **kwargs):
                pass

        with patch.object(main.threading, "Timer", FakeTimer):
            bot = main.ChatBot(
                FakeMessageHandler(), object(), FakeWeChat(), plugin_manager=FakePluginManager()
            )
            bot.handle_wxauto_message(FakeMessage(), "测试群", is_group=True)

        self.assertIn("测试群", bot.user_queues)
        self.assertIn("继续说", bot.user_queues["测试群"]["messages"][0])

    def test_quote_reply_to_other_member_does_not_trigger_group_ai(self):
        import main

        class FakeWeChat:
            def get_my_name(self):
                return "\u673a\u5668\u4eba"

        class FakePluginManager:
            def handle_group_message(self, **message):
                return None

        class FakeMessage:
            sender = "\u7fa4\u6210\u5458"
            content = "\u7ee7\u7eed\u8bf4"
            is_self = False
            is_quote = True
            quoted_sender = "\u5176\u4ed6\u4eba"

        class FakeMessageHandler:
            def add_to_queue(self, **kwargs):
                raise AssertionError("quote to another member must not trigger the bot")

        bot = main.ChatBot(
            FakeMessageHandler(), object(), FakeWeChat(), plugin_manager=FakePluginManager()
        )
        bot.handle_wxauto_message(FakeMessage(), "\u6d4b\u8bd5\u7fa4", is_group=True)
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
