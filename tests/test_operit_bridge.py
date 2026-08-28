from __future__ import annotations

import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.operit import (
    OperitBridge,
    OperitClient,
    OperitResult,
    OperitSessionStore,
    compact_phone_reply,
)


class FakeClient:
    def __init__(self) -> None:
        self.commands: list[tuple[str, str]] = []

    def health(self) -> str:
        return "Operit 在线（test）"

    def execute(self, command: str, chat_id: str = "") -> OperitResult:
        self.commands.append((command, chat_id))
        return OperitResult(text=f"完成：{command}", chat_id=chat_id or "phone-chat-1")


class FakeResponse:
    status_code = 200

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def json(self) -> dict:
        return self.payload


class FakeHttpSession:
    def __init__(self, response_payload: dict) -> None:
        self.response_payload = response_payload
        self.calls: list[dict] = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return FakeResponse(self.response_payload)


class OperitClientTests(unittest.TestCase):
    def test_health_accepts_operit_112_response_without_status_field(self):
        session = FakeHttpSession(
            {"enabled": True, "service_running": True, "version_name": "1.12.0"}
        )
        client = OperitClient(
            base_url="http://phone:8094",
            bearer_token="secret",
            session=session,
        )

        self.assertEqual(client.health(), "我的手机连着呢（系统 1.12.0）。")

    def test_existing_chat_is_reused_and_tool_markup_is_hidden(self):
        session = FakeHttpSession(
            {"success": True, "chat_id": "c1", "ai_response": "done"}
        )
        client = OperitClient(
            base_url="http://phone:8094/",
            bearer_token="secret",
            session=session,
        )

        result = client.execute("打开设置", chat_id="c1")

        self.assertEqual(result.text, "done")
        call = session.calls[0]
        self.assertEqual(call["url"], "http://phone:8094/api/external-chat")
        self.assertEqual(call["json"]["chat_id"], "c1")
        self.assertFalse(call["json"]["create_new_chat"])
        self.assertFalse(call["json"]["return_tool_status"])
        self.assertEqual(call["headers"]["Authorization"], "Bearer secret")


class OperitBridgeTests(unittest.TestCase):
    def make_bridge(self, root: Path, **kwargs) -> tuple[OperitBridge, FakeClient]:
        client = FakeClient()
        bridge = OperitBridge(
            client=client,
            session_store=OperitSessionStore(root / "sessions.json"),
            enabled=kwargs.pop("enabled", True),
            allowed_senders=kwargs.pop("allowed_senders", ["owner"]),
            **kwargs,
        )
        return bridge, client

    def collect_until(self, replies: list[str], event: threading.Event):
        def callback(text: str) -> None:
            replies.append(text)
            event.set()

        return callback

    def test_non_phone_message_is_not_consumed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge, _ = self.make_bridge(Path(temp_dir))
            handled = bridge.handle_message(
                chat_id="owner",
                sender_id="owner",
                sender_name="owner",
                content="今天天气如何",
                is_group=False,
                on_reply=lambda _text: None,
            )
        self.assertFalse(handled)

    def test_sender_allowlist_is_deny_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge, client = self.make_bridge(Path(temp_dir), allowed_senders=[])
            replies: list[str] = []
            handled = bridge.handle_message(
                chat_id="stranger",
                sender_id="stranger",
                sender_name="stranger",
                content="手机：打开设置",
                is_group=False,
                on_reply=replies.append,
            )
        self.assertTrue(handled)
        self.assertEqual(replies, ["这部手机只接受主人的控制指令。"])
        self.assertEqual(client.commands, [])

    def test_safe_command_runs_in_worker_and_persists_chat(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge, client = self.make_bridge(Path(temp_dir))
            replies: list[str] = []
            done = threading.Event()
            callback = self.collect_until(replies, done)

            handled = bridge.handle_message(
                chat_id="owner-chat",
                sender_id="owner",
                sender_name="owner",
                content="手机：打开设置",
                is_group=False,
                on_reply=callback,
            )
            self.assertTrue(done.wait(2))

            self.assertTrue(handled)
            self.assertEqual(replies, ["完成：打开设置"])
            self.assertEqual(client.commands, [("打开设置", "")])
            self.assertEqual(bridge.session_store.get("owner-chat"), "phone-chat-1")

    def test_sensitive_command_needs_matching_confirmation_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge, client = self.make_bridge(Path(temp_dir))
            replies: list[str] = []
            common = dict(
                chat_id="owner-chat",
                sender_id="owner",
                sender_name="owner",
                is_group=False,
                on_reply=replies.append,
            )
            bridge.handle_message(content="手机：给小明发短信说晚点到", **common)

            self.assertEqual(client.commands, [])
            match = re.search(r"手机确认 (\d{6})", replies[-1])
            self.assertIsNotNone(match)
            done = threading.Event()
            common["on_reply"] = self.collect_until(replies, done)
            bridge.handle_message(content=f"手机确认 {match.group(1)}", **common)
            self.assertTrue(done.wait(2))

            self.assertEqual(client.commands[0][0], "给小明发短信说晚点到")

    def test_natural_owned_phone_phrase_triggers_without_command_prefix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge, client = self.make_bridge(Path(temp_dir))
            replies: list[str] = []
            done = threading.Event()
            handled = bridge.handle_message(
                chat_id="owner-chat",
                sender_id="owner",
                sender_name="owner",
                content="娜娜，帮我用你的手机打开设置看看",
                is_group=False,
                on_reply=self.collect_until(replies, done),
            )
            self.assertTrue(done.wait(2))

        self.assertTrue(handled)
        self.assertEqual(client.commands[0][0], "娜娜，帮我用你的手机打开设置看看")

    def test_owned_phone_brand_question_reads_real_device_info(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge, client = self.make_bridge(Path(temp_dir))
            done = threading.Event()
            handled = bridge.handle_message(
                chat_id="owner-chat",
                sender_id="owner",
                sender_name="owner",
                content="你的手机是什么牌子呀",
                is_group=False,
                on_reply=lambda _text: done.set(),
            )
            self.assertTrue(done.wait(2))
        self.assertTrue(handled)
        self.assertIn("实际调用手机系统能力读取本机设备信息", client.commands[0][0])
        self.assertIn("你的手机是什么牌子呀", client.commands[0][0])

    def test_bare_owned_phone_battery_question_triggers_device(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge, client = self.make_bridge(Path(temp_dir))
            replies: list[str] = []
            done = threading.Event()
            handled = bridge.handle_message(
                chat_id="owner-chat",
                sender_id="owner",
                sender_name="owner",
                content="你手机还有多少电啊",
                is_group=False,
                on_reply=self.collect_until(replies, done),
            )
            self.assertTrue(done.wait(2))

        self.assertTrue(handled)
        self.assertIn("实际调用手机系统能力读取当前电池状态", client.commands[0][0])
        self.assertIn("你手机还有多少电啊", client.commands[0][0])

    def test_owned_phone_configuration_question_triggers_device(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge, client = self.make_bridge(Path(temp_dir))
            done = threading.Event()
            handled = bridge.handle_message(
                chat_id="owner-chat",
                sender_id="owner",
                sender_name="owner",
                content="你手机什么配置啊",
                is_group=False,
                on_reply=lambda _text: done.set(),
            )
            self.assertTrue(done.wait(2))
        self.assertTrue(handled)
        self.assertIn("实际调用手机系统能力读取本机设备信息", client.commands[0][0])

    def test_owned_phone_download_request_needs_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge, client = self.make_bridge(Path(temp_dir))
            replies: list[str] = []
            handled = bridge.handle_message(
                chat_id="owner-chat",
                sender_id="owner",
                sender_name="owner",
                content="有抖音么，你在手机上下载个抖音",
                is_group=False,
                on_reply=replies.append,
            )
        self.assertTrue(handled)
        self.assertEqual(client.commands, [])
        self.assertIn("手机确认", replies[0])

        followup_replies: list[str] = []
        handled_followup = bridge.handle_message(
            chat_id="owner-chat",
            sender_id="owner",
            sender_name="owner",
            content="安装吧，安装个抖音",
            is_group=False,
            on_reply=followup_replies.append,
        )
        self.assertTrue(handled_followup)
        self.assertIn("手机确认", followup_replies[0])

    def test_result_processor_runs_before_plain_text_cleanup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge, _client = self.make_bridge(Path(temp_dir))
            replies: list[str] = []
            done = threading.Event()
            bridge.handle_message(
                chat_id="owner-chat",
                sender_id="owner",
                sender_name="owner",
                content="手机：查看电量",
                is_group=False,
                on_reply=self.collect_until(replies, done),
                process_result=lambda _command, _raw: "## 结果\n**还有 80% 电量。**",
            )
            self.assertTrue(done.wait(2))

        self.assertIn("结果\n还有 80% 电量。", replies)

    def test_markdown_fallback_is_compacted(self):
        raw = "## 执行结果\n- **微信已打开**\n- `状态`: success"
        self.assertEqual(compact_phone_reply(raw), "执行结果\n微信已打开\n状态: success")

    def test_group_commands_are_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge, client = self.make_bridge(Path(temp_dir))
            replies: list[str] = []
            bridge.handle_message(
                chat_id="group",
                sender_id="owner",
                sender_name="owner",
                content="手机：打开设置",
                is_group=True,
                on_reply=replies.append,
            )
        self.assertEqual(replies, ["这部手机只接受主人的控制指令。"])
        self.assertEqual(client.commands, [])

    def test_unauthorized_natural_phone_question_gets_natural_refusal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge, client = self.make_bridge(Path(temp_dir))
            replies: list[str] = []
            bridge.handle_message(
                chat_id="group",
                sender_id="stranger",
                sender_name="stranger",
                content="娜娜，你手机还有多少电呀",
                is_group=True,
                on_reply=replies.append,
            )
        self.assertEqual(replies, ["这个我先不帮你查啦。"])
        self.assertEqual(client.commands, [])


if __name__ == "__main__":
    unittest.main()
