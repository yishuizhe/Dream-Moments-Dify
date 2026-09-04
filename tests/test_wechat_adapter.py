from __future__ import annotations

import sys
import json
import sqlite3
import tempfile
import time
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wechat.adapter import WxAuto4PollingAdapter


@dataclass
class FakeSession:
    name: str
    content: str = ""
    time: str = ""
    isnew: bool = False
    new_count: int = 0
    username: str = ""


@dataclass
class FakeMessage:
    sender: str
    content: str
    type: str = "friend"
    attr: str = "friend"
    id: str = ""


class FakeWeChat:
    def __init__(
        self,
        chats: dict[str, list[FakeMessage]],
        chat_types: dict[str, str] | None = None,
    ) -> None:
        self.chats = chats
        self.chat_types = chat_types or {}
        self.current = ""
        self.open_calls: list[str] = []
        self.sent_messages: list[tuple[str, str]] = []
        self.sent_files: list[tuple[str, str]] = []

    def IsOnline(self):
        return True

    def GetMyInfo(self):
        return {"nickname": "机器人"}

    def ChatWith(self, who, exact=True):
        if who not in self.chats:
            return False
        self.open_calls.append(who)
        self.current = who
        return True

    def ChatInfo(self):
        return {"chat_type": self.chat_types.get(self.current, "friend")}

    def GetAllMessage(self):
        return list(self.chats[self.current])

    def SendMsg(self, msg, who=None, **kwargs):
        self.sent_messages.append((who or self.current, msg))
        return True

    def SendFiles(self, filepath, who=None, **kwargs):
        self.sent_files.append((who or self.current, filepath))
        return True


class SessionAwareFakeWeChat(FakeWeChat):
    def __init__(self, chats, sessions, chat_types=None):
        super().__init__(chats, chat_types=chat_types)
        self.sessions = sessions

    def GetSession(self):
        return list(self.sessions)


class ReplicaFakeWeChat(SessionAwareFakeWeChat):
    backend_name = "wechatauto-replica"


class RenamedGroupFakeWeChat(FakeWeChat):
    def __init__(self):
        super().__init__({"旧群名": [FakeMessage("成员", "旧消息")]}, {"旧群名": "group"})
        self.preview = "旧消息"

    def ResolveContactId(self, name):
        return "room@chatroom" if name == "旧群名" else ""

    def BindContactId(self, name, username):
        pass

    def ChatInfo(self):
        return {"chat_type": "group", "chat_name": "新群名", "chat_id": "room@chatroom"}

    def GetSession(self):
        return [FakeSession("新群名", self.preview, "10:00", username="room@chatroom")]


class WxAuto4PollingAdapterTests(unittest.TestCase):
    def make_adapter(self, fake, state_path=None, **kwargs):
        return WxAuto4PollingAdapter(
            ["好友"],
            state_path=state_path,
            wechat_factory=lambda: fake,
            **kwargs,
        )

    def test_session_polling_does_not_reopen_chat_without_changes(self):
        friend = "好友"
        fake = SessionAwareFakeWeChat(
            {friend: [FakeMessage(friend, "old message")]},
            [FakeSession(friend, "old message", "10:00")],
        )
        adapter = self.make_adapter(fake)

        adapter.poll_once()
        fake.open_calls.clear()
        self.assertEqual(adapter.poll_once(), [])
        self.assertEqual(adapter.poll_once(), [])

        self.assertEqual(fake.open_calls, [])

    def test_group_rename_is_matched_by_stable_session_id(self):
        fake = RenamedGroupFakeWeChat()
        adapter = WxAuto4PollingAdapter(["旧群名"], wechat_factory=lambda: fake)
        self.assertEqual(adapter.poll_once(), [])
        self.assertEqual(adapter.poll_once(), [])

        fake.preview = "娜娜在吗"
        fake.chats["旧群名"].append(FakeMessage("成员", "娜娜在吗"))
        messages = adapter.poll_once()

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].chat_name, "新群名")
        self.assertEqual(messages[0].chat_id, "room@chatroom")
        self.assertEqual(messages[0].configured_name, "旧群名")

    def test_old_token_state_keeps_contact_ids_but_rebuilds_snapshots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "wechat-state.json"
            state_path.write_text(json.dumps({
                "version": 4,
                "chats": {"旧群名": ["old-content-token"]},
                "contact_ids": {"旧群名": "room@chatroom"},
            }), encoding="utf-8")
            adapter = WxAuto4PollingAdapter(
                ["旧群名"], state_path=state_path,
                wechat_factory=lambda: RenamedGroupFakeWeChat(),
            )
            self.assertEqual(adapter._snapshots, {})
            self.assertEqual(adapter._contact_ids["旧群名"], "room@chatroom")

    def test_session_polling_opens_only_changed_whitelisted_chat(self):
        friend = "friend"
        group = "group"
        fake = SessionAwareFakeWeChat(
            {
                friend: [FakeMessage(friend, "old friend message")],
                group: [FakeMessage("member", "old group message")],
            },
            [
                FakeSession(friend, "old friend message", "10:00"),
                FakeSession(group, "old group message", "10:00"),
                FakeSession("not-whitelisted", "other", "10:00", True, 1),
            ],
            chat_types={group: "group"},
        )
        adapter = WxAuto4PollingAdapter(
            [friend, group],
            wechat_factory=lambda: fake,
        )
        adapter.poll_once()
        adapter.poll_once()
        fake.open_calls.clear()

        fake.chats[group].append(FakeMessage("member", "new message"))
        fake.sessions[1] = FakeSession(group, "new message", "10:01", True, 1)
        messages = adapter.poll_once()

        self.assertEqual(fake.open_calls, [group])
        self.assertEqual([message.content for message in messages], ["new message"])

    def test_replica_backend_reads_database_when_session_preview_is_stale(self):
        friend = "好友"
        fake = ReplicaFakeWeChat(
            {friend: [FakeMessage(friend, "旧消息")]},
            [FakeSession(friend, "一直不变的预览", "10:00")],
        )
        adapter = self.make_adapter(fake)
        adapter.poll_once()
        fake.open_calls.clear()

        fake.chats[friend].append(FakeMessage(friend, "数据库里的新消息"))
        messages = adapter.poll_once()

        self.assertEqual(fake.open_calls, [friend])
        self.assertEqual([message.content for message in messages], ["数据库里的新消息"])

    def test_first_poll_only_builds_baseline(self):
        fake = FakeWeChat({"好友": [FakeMessage("好友", "旧消息")]})
        adapter = self.make_adapter(fake)

        self.assertEqual(adapter.poll_once(), [])

    def test_new_duplicate_text_is_not_lost(self):
        fake = FakeWeChat({"好友": [FakeMessage("好友", "哈哈")]})
        adapter = self.make_adapter(fake)
        adapter.poll_once()

        fake.chats["好友"].append(FakeMessage("好友", "哈哈"))
        messages = adapter.poll_once()

        self.assertEqual([message.content for message in messages], ["哈哈"])


    def test_ui_message_ids_can_change_between_chat_switches(self):
        fake = FakeWeChat(
            {"好友": [FakeMessage("好友", f"消息{i}", id=f"old-{i}") for i in range(5)]}
        )
        adapter = self.make_adapter(fake, history_size=5)
        adapter.poll_once()

        # wxauto4's UI id is recreated after switching chats. Stable content
        # overlap must still identify only the newly appended message.
        fake.chats["好友"] = [
            FakeMessage("好友", f"消息{i}", id=f"new-{i}") for i in range(1, 6)
        ]
        messages = adapter.poll_once()

        self.assertEqual([message.content for message in messages], ["消息5"])

    def test_self_messages_are_ignored_without_breaking_overlap(self):
        fake = FakeWeChat({"好友": [FakeMessage("好友", "你好")]})
        adapter = self.make_adapter(fake)
        adapter.poll_once()

        fake.chats["好友"].extend(
            [
                FakeMessage("机器人", "机器人回复", type="self", attr="self"),
                FakeMessage("好友", "继续说"),
            ]
        )
        messages = adapter.poll_once()

        self.assertEqual([message.content for message in messages], ["继续说"])

    def test_group_message_is_marked_as_group(self):
        fake = FakeWeChat(
            {"好友": [FakeMessage("群成员", "@机器人 在吗")]},
            chat_types={"好友": "group"},
        )
        adapter = self.make_adapter(fake, process_existing_on_start=True)

        messages = adapter.poll_once()

        self.assertEqual(len(messages), 1)
        self.assertTrue(messages[0].is_group)
        self.assertEqual(messages[0].chat_name, "好友")
        self.assertEqual(messages[0].sender, "群成员")


    def test_quote_message_extracts_reply_and_target_metadata(self):
        fake = FakeWeChat(
            {
                "\u597d\u53cb": [
                    FakeMessage(
                        "\u7fa4\u6210\u5458",
                        "\u7ee7\u7eed\u8bf4 \u5f15\u7528 \u673a\u5668\u4eba \u7684\u6d88\u606f: \u4e0a\u4e00\u6761\u56de\u590d",
                        type="quote",
                        attr="friend",
                    )
                ]
            },
            chat_types={"\u597d\u53cb": "group"},
        )
        adapter = self.make_adapter(fake, process_existing_on_start=True)

        messages = adapter.poll_once()

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, "\u7ee7\u7eed\u8bf4")
        self.assertTrue(messages[0].is_quote)
        self.assertEqual(messages[0].quoted_sender, "\u673a\u5668\u4eba")
        self.assertEqual(messages[0].quoted_content, "\u4e0a\u4e00\u6761\u56de\u590d")

    def test_private_chat_uses_chat_info_even_if_sender_name_differs(self):
        fake = FakeWeChat({"好友": [FakeMessage("真实昵称", "你好")]})
        adapter = self.make_adapter(fake, process_existing_on_start=True)

        messages = adapter.poll_once()

        self.assertEqual(len(messages), 1)
        self.assertFalse(messages[0].is_group)

    def test_all_contact_failures_request_reconnect(self):
        fake = FakeWeChat({})
        adapter = self.make_adapter(fake)

        with self.assertRaisesRegex(RuntimeError, "重新连接微信"):
            adapter.poll_once()

    def test_clipboard_poll_failure_discards_the_stale_client(self):
        class ClipboardBrokenWeChat(FakeWeChat):
            def ChatWith(self, who, exact=True):
                raise RuntimeError("Error calling OpenClipboard")

        adapter = self.make_adapter(ClipboardBrokenWeChat({"好友": []}))

        with self.assertRaisesRegex(RuntimeError, "重新连接微信"):
            adapter.poll_once()

        self.assertIsNone(adapter._client)

    def test_malformed_replica_snapshot_discards_the_stale_client(self):
        class MalformedDatabaseWeChat(FakeWeChat):
            def ChatWith(self, who, exact=True):
                raise sqlite3.DatabaseError("database disk image is malformed")

        adapter = self.make_adapter(MalformedDatabaseWeChat({"好友": []}))

        with self.assertRaisesRegex(RuntimeError, "重新连接微信"):
            adapter.poll_once()

        self.assertIsNone(adapter._client)

    def test_state_file_allows_restart_to_find_only_new_messages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "wechat-state.json"
            fake = FakeWeChat({"好友": [FakeMessage("好友", "第一条")]})
            first = self.make_adapter(fake, state_path=state_path)
            self.assertEqual(first.poll_once(), [])

            fake.chats["好友"].append(FakeMessage("好友", "第二条"))
            restarted = self.make_adapter(fake, state_path=state_path)
            messages = restarted.poll_once()

            self.assertEqual([message.content for message in messages], ["第二条"])

    def test_stale_state_rebuilds_baseline_without_replaying_downtime_messages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "wechat-state.json"
            fake = FakeWeChat({"好友": [FakeMessage("好友", "停机前")]})
            first = self.make_adapter(fake, state_path=state_path)
            self.assertEqual(first.poll_once(), [])

            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["saved_at"] = time.time() - 600
            state_path.write_text(json.dumps(state), encoding="utf-8")
            fake.chats["好友"].append(FakeMessage("好友", "停机期间"))

            restarted = self.make_adapter(fake, state_path=state_path)
            self.assertEqual(restarted.poll_once(), [])

    def test_discontinuous_window_rebaselines_instead_of_replaying_history(self):
        fake = FakeWeChat({"好友": [FakeMessage("好友", "第一批")]})
        adapter = self.make_adapter(fake)
        adapter.poll_once()

        fake.chats["好友"] = [FakeMessage("好友", "完全不同的可见历史")]
        self.assertEqual(adapter.poll_once(), [])

    def test_send_compatibility_methods_proxy_to_free_api(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "image.png"
            file_path.write_bytes(b"test")
            fake = FakeWeChat({"好友": []})
            adapter = self.make_adapter(fake)

            adapter.SendMsg(msg="回复", who="好友")
            adapter.SendFiles(filepath=str(file_path), who="好友")

            self.assertEqual(fake.sent_messages, [("好友", "回复")])
            self.assertEqual(fake.sent_files, [("好友", str(file_path.resolve()))])
            self.assertTrue(adapter.is_recent_sent_text("好友", "回复"))
            self.assertFalse(adapter.is_recent_sent_text("其他会话", "回复"))


if __name__ == "__main__":
    unittest.main()
