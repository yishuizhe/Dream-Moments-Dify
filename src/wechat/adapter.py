"""基于免费版 wxauto4 的前台轮询适配器。

免费版只需要 ``ChatWith``、``GetAllMessage``、``SendMsg`` 和 ``SendFiles``。
监听通过轮流切换白名单会话并比较相邻消息快照实现，不依赖 Plus 的
``AddListenChat``/``GetListenMessage``。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IncomingMessage:
    """项目内部统一使用的微信消息对象。"""

    chat_name: str
    sender: str
    content: str
    message_type: str = "friend"
    is_group: bool = False
    is_self: bool = False
    is_quote: bool = False
    quoted_sender: str = ""
    quoted_content: str = ""
    raw: Any = None

    @property
    def type(self) -> str:
        """兼容旧版 ``wxauto`` 消息对象的 ``type`` 属性。"""

        return self.message_type


@dataclass(slots=True)
class _SnapshotMessage:
    token: str
    message: IncomingMessage
    incoming_human: bool


class WxAuto4PollingAdapter:
    """用免费版 wxauto4 实现发送、读取和轮询监听。

    ``wechat_factory`` 仅用于依赖注入和测试；生产环境会延迟导入
    ``wxauto4.WeChat``，因此单元测试不要求本机启动微信。
    """

    # Version 2 intentionally drops wxauto4's UI ``id`` from persisted tokens.
    # That id is recreated after switching chats and therefore is not suitable
    # for comparing snapshots across foreground polling rounds.
    STATE_VERSION = 2

    def __init__(
        self,
        contacts: Iterable[str],
        *,
        poll_interval: float = 2.0,
        history_size: int = 50,
        state_path: str | os.PathLike[str] | None = None,
        process_existing_on_start: bool = False,
        exact_match: bool = True,
        wechat_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.contacts = [str(item).strip() for item in contacts if str(item).strip()]
        self.poll_interval = max(float(poll_interval), 0.2)
        self.history_size = max(int(history_size), 5)
        self.process_existing_on_start = bool(process_existing_on_start)
        self.exact_match = bool(exact_match)
        self.state_path = Path(state_path).expanduser() if state_path else None
        self._factory = wechat_factory or self._default_factory
        self._client: Any = None
        self._my_name_cache = ""
        self._ui_lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._sent_lock = threading.Lock()
        self._recent_sent_texts: dict[str, deque[str]] = {}
        self._snapshots: dict[str, list[str]] = {}
        # GetSession() inspects the conversation list without opening chats.
        # Preview signatures also detect changes in the currently open chat.
        self._session_signatures: dict[str, str] = {}
        self._load_state()

    @staticmethod
    def _default_factory() -> Any:
        try:
            from .wxauto4_compat import create_wechat_client

            return create_wechat_client(ads=False)
        except ImportError as exc:
            raise RuntimeError(
                "未安装免费版 wxauto4，请先执行: python -m pip install wxauto4"
            ) from exc

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._factory()
        return self._client

    def reconnect(self) -> None:
        """丢弃失效实例，下一次操作时重新连接微信。"""

        with self._ui_lock:
            self._client = None
            self._my_name_cache = ""

    def is_online(self) -> bool:
        """尽可能使用免费版公开能力判断微信是否在线。"""

        with self._ui_lock:
            client = self.client
            checker = getattr(client, "IsOnline", None)
            if callable(checker):
                return bool(checker())

            getter = getattr(client, "GetSession", None)
            if callable(getter):
                getter()
                return True

            # 能成功创建实例时，旧/精简版本也可继续尝试 ChatWith。
            return True

    def get_my_name(self) -> str:
        """兼容 wxauto4 和旧 wxauto 的多种昵称字段。"""

        with self._ui_lock:
            if self._my_name_cache:
                return self._my_name_cache

            client = self.client
            getter = getattr(client, "GetMyInfo", None)
            if callable(getter):
                info = getter() or {}
                if isinstance(info, dict):
                    for key in ("nickname", "NickName", "name", "Name"):
                        if info.get(key):
                            self._my_name_cache = str(info[key])
                            return self._my_name_cache

            for attr in ("nickname", "name"):
                value = getattr(client, attr, None)
                if value:
                    self._my_name_cache = str(value)
                    return self._my_name_cache

            myinfo = getattr(client, "myinfo", None)
            if isinstance(myinfo, dict):
                for key in ("nickname", "NickName", "name", "Name"):
                    if myinfo.get(key):
                        self._my_name_cache = str(myinfo[key])
                        return self._my_name_cache

            # 兼容项目原先使用的 wxauto 3.x 字段。
            icon = getattr(client, "A_MyIcon", None)
            value = getattr(icon, "Name", None) if icon is not None else None
            if value:
                self._my_name_cache = str(value)
            return self._my_name_cache

    def open_chat(self, chat_name: str) -> Any:
        with self._ui_lock:
            method = getattr(self.client, "ChatWith")
            try:
                result = method(chat_name, exact=self.exact_match)
            except TypeError:
                result = method(chat_name)
            if result is False:
                raise RuntimeError(f"找不到微信会话: {chat_name}")
            return result

    def validate_contacts(self) -> list[str]:
        """逐个打开白名单会话，返回无法打开的会话名。"""

        failed: list[str] = []
        for contact in self.contacts:
            try:
                self.open_chat(contact)
            except Exception:
                logger.exception("无法打开微信会话: %s", contact)
                failed.append(contact)
        return failed

    def get_all_messages(self, chat_name: str) -> list[Any]:
        with self._ui_lock:
            self.open_chat(chat_name)
            messages = self.client.GetAllMessage() or []
            return list(messages)

    def send_text(self, chat_name: str, text: str, *, at: str | list[str] | None = None) -> Any:
        if not text:
            return None
        with self._ui_lock:
            method = self.client.SendMsg
            kwargs: dict[str, Any] = {
                "msg": text,
                "who": chat_name,
                "exact": self.exact_match,
            }
            if at:
                kwargs["at"] = at
            try:
                result = method(**kwargs)
            except TypeError:
                kwargs.pop("at", None)
                try:
                    result = method(**kwargs)
                except TypeError:
                    kwargs.pop("exact", None)
                    result = method(**kwargs)
            self._remember_sent_text(chat_name, text)
            return result

    def is_recent_sent_text(self, chat_name: str, text: str) -> bool:
        """判断被引用的文本是否是机器人最近在该会话发送的内容。

        群内设置了“我在本群的昵称”时，微信引用卡片中的发送者名称可能与
        ``get_my_name()`` 不一致，因此使用最近发送文本作为安全的兼容回退。
        记录仅保存在内存中，不写入日志或状态文件。
        """

        normalized = self._normalize_match_text(text)
        if not normalized:
            return False
        with self._sent_lock:
            return normalized in self._recent_sent_texts.get(str(chat_name), ())

    def _remember_sent_text(self, chat_name: str, text: str) -> None:
        normalized = self._normalize_match_text(text)
        if not normalized:
            return
        key = str(chat_name)
        with self._sent_lock:
            history = self._recent_sent_texts.setdefault(key, deque(maxlen=self.history_size))
            history.append(normalized)

    @staticmethod
    def _normalize_match_text(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    def send_file(self, chat_name: str, file_path: str | os.PathLike[str]) -> Any:
        path = str(Path(file_path).expanduser().resolve())
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        with self._ui_lock:
            method = self.client.SendFiles
            try:
                return method(
                    filepath=path,
                    who=chat_name,
                    exact=self.exact_match,
                )
            except TypeError:
                return method(filepath=path, who=chat_name)

    # 兼容现有 MessageHandler，后续可逐步迁移到 send_text/send_file。
    def SendMsg(self, msg: str, who: str, **kwargs: Any) -> Any:  # noqa: N802
        return self.send_text(who, msg, at=kwargs.get("at"))

    def SendFiles(self, filepath: str, who: str, **_: Any) -> Any:  # noqa: N802
        return self.send_file(who, filepath)

    def ChatWith(self, who: str, **_: Any) -> Any:  # noqa: N802
        return self.open_chat(who)

    def GetAllMessage(self) -> list[Any]:  # noqa: N802
        with self._ui_lock:
            return list(self.client.GetAllMessage() or [])

    def poll_once(self) -> list[IncomingMessage]:
        """Return new messages while minimizing foreground chat switches.

        Chats without a baseline are opened once. Later rounds use ``GetSession``
        and open only unread or preview-changed chats. Clients without this API
        keep the legacy full polling behavior.
        """

        missing_baselines = [
            contact for contact in self.contacts if contact not in self._snapshots
        ]
        if missing_baselines:
            contacts_to_read = missing_baselines
        else:
            changed_sessions = self._get_changed_session_contacts()
            contacts_to_read = (
                list(self.contacts) if changed_sessions is None else changed_sessions
            )

        result: list[IncomingMessage] = []
        changed = False
        failed_contacts: list[str] = []
        for contact in contacts_to_read:
            try:
                snapshot = self._read_snapshot(contact)
                tokens = [item.token for item in snapshot]
                previous = self._snapshots.get(contact)

                if previous is None:
                    new_items = snapshot if self.process_existing_on_start else []
                else:
                    overlap = self._suffix_prefix_overlap(previous, tokens)
                    if previous and tokens and overlap == 0:
                        # UI virtualization can replace the whole visible window.
                        # Rebuild the baseline instead of replaying old messages.
                        logger.warning("Chat %s lost message continuity; baseline rebuilt", contact)
                        new_items = []
                    else:
                        new_items = snapshot[overlap:]

                self._snapshots[contact] = tokens[-self.history_size :]
                changed = True
                result.extend(
                    item.message
                    for item in new_items
                    if item.incoming_human and not item.message.is_self
                )
            except Exception:
                logger.exception("Failed to poll WeChat chat: %s", contact)
                failed_contacts.append(contact)

        if changed:
            self._save_state()
        if contacts_to_read and len(failed_contacts) == len(contacts_to_read):
            raise RuntimeError("所有微信会话轮询均失败，请重新连接微信")
        return result

    def _get_changed_session_contacts(self) -> list[str] | None:
        """Return whitelisted sessions that need a foreground read.

        ``None`` means ``GetSession`` is unavailable and full polling is needed.
        An empty list means no chat changed, so the current window stays put.
        """

        with self._ui_lock:
            getter = getattr(self.client, "GetSession", None)
            if not callable(getter):
                return None
            sessions = list(getter() or [])

        wanted = set(self.contacts)
        changed: list[str] = []
        seen: set[str] = set()
        for session in sessions:
            name = self._session_value(session, "name", "Name", "who", "chat_name")
            if name not in wanted or name in seen:
                continue
            seen.add(name)

            content = self._session_value(session, "content", "text", "message")
            timestamp = self._session_value(session, "time", "timestamp")
            signature = hashlib.sha256(
                f"{content}\x1f{timestamp}".encode("utf-8")
            ).hexdigest()
            previous_signature = self._session_signatures.get(name)
            self._session_signatures[name] = signature

            unread_count = self._session_int(session, "new_count", "unread_count")
            is_new = self._session_bool(session, "isnew", "is_new", "unread")
            preview_changed = (
                previous_signature is not None and previous_signature != signature
            )
            if unread_count > 0 or is_new or preview_changed:
                changed.append(name)

        return changed

    @staticmethod
    def _session_value(session: Any, *names: str) -> str:
        for name in names:
            value = (
                session.get(name)
                if isinstance(session, dict)
                else getattr(session, name, None)
            )
            if value is not None and not callable(value):
                text = str(value).strip()
                if text:
                    return text
        return ""

    @classmethod
    def _session_int(cls, session: Any, *names: str) -> int:
        value = cls._session_value(session, *names)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _session_bool(cls, session: Any, *names: str) -> bool:
        value = cls._session_value(session, *names).lower()
        return value in {"1", "true", "yes", "y", "on"}

    def run(self, callback: Callable[[IncomingMessage], None], stop_event: threading.Event) -> None:
        """持续轮询，直到 ``stop_event`` 被设置。"""

        while not stop_event.is_set():
            for message in self.poll_once():
                try:
                    callback(message)
                except Exception:
                    logger.exception("处理微信消息失败: %s", message.chat_name)
            stop_event.wait(self.poll_interval)

    def _read_snapshot(self, chat_name: str) -> list[_SnapshotMessage]:
        # Message objects wrap live UI controls. Keep the UI lock until all
        # public attributes have been normalized, otherwise a concurrent send
        # could switch chats and invalidate those controls.
        with self._ui_lock:
            self.open_chat(chat_name)
            is_group_chat = self._current_chat_is_group()
            raw_messages = list(self.client.GetAllMessage() or [])

            normalized: list[_SnapshotMessage] = []
            for raw in raw_messages[-self.history_size :]:
                item = self._normalize_message(
                    chat_name,
                    raw,
                    is_group_chat=is_group_chat,
                )
                if item is not None:
                    normalized.append(item)
            return normalized

    def _current_chat_is_group(self) -> bool | None:
        """读取当前聊天类型；旧版客户端缺少该接口时返回 ``None``。"""

        getter = getattr(self.client, "ChatInfo", None)
        if not callable(getter):
            return None
        try:
            info = getter() or {}
        except Exception:
            logger.debug("读取当前微信会话类型失败", exc_info=True)
            return None
        if not isinstance(info, dict):
            return None
        chat_type = str(info.get("chat_type", "")).strip().lower()
        if chat_type == "group":
            return True
        if chat_type == "friend":
            return False
        return None

    def _normalize_message(
        self,
        chat_name: str,
        raw: Any,
        *,
        is_group_chat: bool | None = None,
    ) -> _SnapshotMessage | None:
        raw_content = self._first_text(raw, "content", "text", "raw")
        sender = self._first_text(raw, "sender", "sender_name", "name")
        kind = self._first_text(raw, "type", "attr") or raw.__class__.__name__
        attr = self._first_text(raw, "attr")

        if not raw_content:
            return None

        kind_lower = f"{kind} {attr} {raw.__class__.__name__}".lower()
        content, is_quote, quoted_sender, quoted_content = self._parse_quote_message(
            raw, raw_content, kind_lower
        )
        if not content:
            return None
        my_name = self.get_my_name()
        is_self = (
            any(marker in kind_lower for marker in ("selfmessage", " self", "sent", "outgoing"))
            or kind_lower.strip() in {"self", "selfmessage"}
            or bool(my_name and sender == my_name)
            or sender.lower() in {"self", "me", "我"}
        )
        is_system = any(marker in kind_lower for marker in ("systemmessage", "system", "time", "notice"))
        incoming_human = not is_self and not is_system and bool(sender)
        is_group = (
            is_group_chat
            if is_group_chat is not None
            else bool(sender and sender != chat_name)
        )

        # Do not use raw.id here. wxauto4 documents it as a UI identifier that
        # changes when the chat UI is switched. Foreground polling switches the
        # UI every round, so using it would make every snapshot look unrelated.
        token_source = json.dumps(
            {
                "sender": sender,
                "content": content,
                "kind": kind,
                "attr": attr,
                "is_quote": is_quote,
                "quoted_sender": quoted_sender,
                "quoted_content": quoted_content,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        token = hashlib.sha256(token_source.encode("utf-8")).hexdigest()
        message = IncomingMessage(
            chat_name=chat_name,
            sender=sender or chat_name,
            content=content,
            message_type="self" if is_self else (kind or "friend"),
            is_group=is_group,
            is_self=is_self,
            is_quote=is_quote,
            quoted_sender=quoted_sender,
            quoted_content=quoted_content,
            raw=raw,
        )
        return _SnapshotMessage(token=token, message=message, incoming_human=incoming_human)

    @classmethod
    def _parse_quote_message(
        cls, raw: Any, content: str, kind_lower: str
    ) -> tuple[str, bool, str, str]:
        """Extract the user's reply and quoted message metadata from wxauto4.

        wxauto4 exposes quote messages as ``QuoteMessage`` and currently formats
        their content as ``<reply> quote <sender>'s message: <quoted text>`` in
        the active UI language. Explicit attributes are preferred when a future
        wxauto4 build provides them; the regex is the compatibility fallback.
        """

        quoted_sender = cls._first_text(
            raw,
            "quoted_sender",
            "quote_sender",
            "reply_sender",
            "source_sender",
        )
        quoted_content = cls._first_text(
            raw,
            "quoted_content",
            "quote_content",
            "reply_content",
            "source_content",
        )
        is_quote = "quote" in kind_lower or bool(quoted_sender or quoted_content)
        reply_content = content.strip()

        # wxauto4 QuoteMessage.repattern for Simplified Chinese:
        # ^(.*)\s*引用\s+(.+?)\s+的消息\s*:\s*(.*)$
        match = re.match(
            r"^(.*?)\s*引用\s+(.+?)\s+的消息\s*[:：]\s*(.*)$",
            content,
            flags=re.DOTALL,
        )
        if match:
            is_quote = True
            reply_content = match.group(1).strip()
            quoted_sender = quoted_sender or match.group(2).strip()
            quoted_content = quoted_content or match.group(3).strip()

        return reply_content, is_quote, quoted_sender, quoted_content

    @staticmethod
    def _first_text(obj: Any, *names: str) -> str:
        for name in names:
            value = getattr(obj, name, None)
            if value is None or callable(value):
                continue
            if isinstance(value, str):
                text = value.strip()
            else:
                text = str(value).strip()
            if text:
                return text
        return ""

    @staticmethod
    def _suffix_prefix_overlap(previous: list[str], current: list[str]) -> int:
        max_size = min(len(previous), len(current))
        for size in range(max_size, 0, -1):
            if previous[-size:] == current[:size]:
                return size
        return 0

    def _load_state(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if data.get("version") != self.STATE_VERSION:
                return
            chats = data.get("chats", {})
            if isinstance(chats, dict):
                self._snapshots = {
                    str(chat): [str(token) for token in tokens][-self.history_size :]
                    for chat, tokens in chats.items()
                    if isinstance(tokens, list)
                }
        except Exception:
            logger.exception("读取微信轮询状态失败，将重新建立基线: %s", self.state_path)

    def _save_state(self) -> None:
        if self.state_path is None:
            return
        with self._state_lock:
            try:
                self.state_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
                payload = {"version": self.STATE_VERSION, "chats": self._snapshots}
                temp_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                os.replace(temp_path, self.state_path)
            except Exception:
                logger.exception("保存微信轮询状态失败: %s", self.state_path)


def sleep_poll_interval(adapter: WxAuto4PollingAdapter) -> None:
    """供旧式循环调用的轻量辅助函数。"""

    time.sleep(adapter.poll_interval)
