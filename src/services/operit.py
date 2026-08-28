"""Secure WeChat-to-Operit bridge built on Operit's external HTTP chat API."""

from __future__ import annotations

import json
import logging
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests


class OperitError(RuntimeError):
    """An expected Operit connectivity or response error."""


@dataclass(slots=True)
class OperitResult:
    text: str
    chat_id: str = ""


@dataclass(slots=True)
class PendingConfirmation:
    command: str
    code: str
    expires_at: float


class OperitSessionStore:
    """Persist one Operit chat id for each authorized WeChat conversation."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self._lock = threading.RLock()
        self._sessions: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return
            except (OSError, ValueError, TypeError):
                return
            if isinstance(payload, dict):
                self._sessions = {
                    str(key): str(value)
                    for key, value in payload.items()
                    if str(key).strip() and str(value).strip()
                }

    def get(self, key: str) -> str:
        with self._lock:
            return self._sessions.get(str(key), "")

    def set(self, key: str, chat_id: str) -> None:
        if not str(chat_id).strip():
            return
        with self._lock:
            self._sessions[str(key)] = str(chat_id)
            self._save_locked()

    def reset(self, key: str) -> bool:
        with self._lock:
            existed = self._sessions.pop(str(key), None) is not None
            if existed:
                self._save_locked()
            return existed

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(self._sessions, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)


class OperitClient:
    """Small, non-retrying client for Operit's external chat endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str,
        timeout_seconds: float = 180.0,
        show_floating: bool = True,
        session: requests.Session | None = None,
    ) -> None:
        normalized_url = str(base_url or "").strip().rstrip("/")
        parsed = urlparse(normalized_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Operit base_url must be a valid http/https URL")
        self.base_url = normalized_url
        self.bearer_token = str(bearer_token or "").strip()
        self.timeout_seconds = max(5.0, float(timeout_seconds))
        self.show_floating = bool(show_floating)
        self.session = session or requests.Session()

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.bearer_token}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        }

    def health(self) -> str:
        payload = self._request_json("GET", "/api/health")
        healthy = str(payload.get("status", "")).lower() == "ok" or (
            bool(payload.get("enabled")) and bool(payload.get("service_running"))
        )
        if not healthy:
            raise OperitError("Operit 健康检查未返回 ok")
        version = str(payload.get("version_name", "")).strip()
        return f"我的手机连着呢{f'（系统 {version}）' if version else ''}。"

    def execute(self, command: str, chat_id: str = "") -> OperitResult:
        content = str(command or "").strip()
        if not content:
            raise OperitError("手机指令为空")
        body = {
            "request_id": str(uuid.uuid4()),
            "message": content,
            "response_mode": "sync",
            "show_floating": self.show_floating,
            "return_tool_status": False,
            "create_new_chat": not bool(chat_id),
            "create_if_none": True,
            "stop_after": False,
        }
        if chat_id:
            body["chat_id"] = str(chat_id)
        payload = self._request_json("POST", "/api/external-chat", json_body=body)
        if not bool(payload.get("success")):
            error = str(payload.get("error", "Operit 执行失败")).strip()
            raise OperitError(error or "Operit 执行失败")
        text = str(payload.get("ai_response", "")).strip() or "手机任务已完成。"
        return OperitResult(text=text, chat_id=str(payload.get("chat_id", "")).strip())

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
    ) -> dict:
        if not self.bearer_token:
            raise OperitError("尚未配置 Operit Bearer Token")
        try:
            response = self.session.request(
                method,
                self.base_url + path,
                headers=self.headers,
                json=json_body,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise OperitError(f"无法连接 Operit：{type(exc).__name__}") from exc
        if response.status_code == 401:
            raise OperitError("Operit 鉴权失败，请检查 Bearer Token")
        try:
            payload = response.json()
        except ValueError as exc:
            raise OperitError(f"Operit 返回了非 JSON 响应（HTTP {response.status_code}）") from exc
        if response.status_code >= 400:
            detail = str(payload.get("error", "")).strip()
            raise OperitError(detail or f"Operit HTTP {response.status_code}")
        if not isinstance(payload, dict):
            raise OperitError("Operit 返回格式不正确")
        return payload


class OperitBridge:
    """Recognize authorized phone commands and execute them outside the poll loop."""

    STATUS_COMMANDS = {"/手机状态", "手机状态", "/phone status"}
    RESET_COMMANDS = {"/手机新会话", "手机新会话", "/phone new"}
    CANCEL_COMMANDS = {"手机取消", "/手机取消", "/phone cancel"}
    CONFIRM_PREFIXES = ("手机确认", "/手机确认", "/phone confirm")
    NATURAL_PHONE_MARKERS = (
        "你的手机",
        "你手机",
        "用你的手机",
        "用你手机",
        "在你的手机上",
        "在你手机上",
        "打开你的手机",
        "看看你的手机",
        "看下你的手机",
        "看一下你的手机",
        "操作你的手机",
        "拿你的手机",
        "娜娜的手机",
        "在手机上",
        "手机上",
    )
    OWNED_PHONE_RE = re.compile(
        r"你(?:现在)?(?:用的|有的)?什么手机|你(?:现在)?电量多少|"
        r"你(?:现在)?还有多少电"
    )
    PHONE_FOLLOWUP_RE = re.compile(
        r"^(?:那|那就|就|继续|好|好的|行|可以|嗯)?[，,\s]*"
        r"(?:打开|启动|看看|查看|点击|点|输入|填写|返回|回到|"
        r"安装|下载|卸载|删除|搜索|找|滑|发|发送|拨打)"
    )
    NATURAL_ACTION_RE = re.compile(
        r"打开|看看|看下|看一下|查看|查找|搜索|用|操作|启动|关闭|播放|暂停|下载|安装|"
        r"导航|拍照|截图|读取|发|发送|拨打|安装|卸载|删除|设置|告诉|找一下"
    )
    NATURAL_STATE_RE = re.compile(
        r"电量|多少电|还有多少电|有没有电|充电|电池|"
        r"通知|未读|联网|网络|信号|存储|剩余空间|内存|温度|"
        r"当前位置|定位|音量|亮度|正在播放|屏幕上|手机屏幕|当前界面|当前页面|页面上|界面上|"
        r"型号|机型|品牌|牌子|设备名称|手机信息|系统版本|安卓版本|Android版本|"
        r"配置|处理器|CPU|运行内存|多大内存|容量"
    )
    BATTERY_QUERY_RE = re.compile(r"电量|多少电|还有多少电|有没有电|充电|电池")
    DEVICE_INFO_QUERY_RE = re.compile(
        r"型号|机型|品牌|牌子|设备名称|手机信息|系统版本|安卓版本|Android版本|"
        r"配置|处理器|CPU|运行内存|多大内存|容量"
    )
    SENSITIVE_MARKERS = (
        "付款", "支付", "转账", "红包", "购买", "下单", "退款",
        "删除", "清空", "卸载", "格式化", "恢复出厂", "修改密码",
        "安装", "下载", "授权", "登录", "退出登录", "发短信", "发消息",
        "发微信", "拨打", "打电话", "发送邮件", "提交", "发布",
    )

    def __init__(
        self,
        *,
        client: OperitClient,
        session_store: OperitSessionStore,
        enabled: bool = False,
        allowed_senders: list[str] | None = None,
        allowed_chats: list[str] | None = None,
        allow_group_commands: bool = False,
        command_prefixes: list[str] | None = None,
        require_confirmation: bool = True,
        confirmation_ttl_seconds: float = 120.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.client = client
        self.session_store = session_store
        self.enabled = bool(enabled)
        self.allowed_senders = {str(item).strip() for item in (allowed_senders or []) if str(item).strip()}
        self.allowed_chats = {str(item).strip() for item in (allowed_chats or []) if str(item).strip()}
        self.allow_group_commands = bool(allow_group_commands)
        # Preserve intentional trailing spaces in slash commands so `/phonebook`
        # cannot be mistaken for the `/phone ` control prefix.
        self.command_prefixes = tuple(
            str(value) for value in (command_prefixes or []) if str(value).strip()
        ) or ("手机：", "手机:", "/手机 ", "/phone ")
        self.require_confirmation = bool(require_confirmation)
        self.confirmation_ttl_seconds = max(30.0, float(confirmation_ttl_seconds))
        self.logger = logger or logging.getLogger(__name__)
        self._pending: dict[str, PendingConfirmation] = {}
        self._pending_lock = threading.RLock()
        self._recent_phone_context: dict[str, float] = {}
        self.phone_context_ttl_seconds = 300.0

    def handle_message(
        self,
        *,
        chat_id: str,
        sender_id: str,
        sender_name: str,
        content: str,
        is_group: bool,
        on_reply: Callable[[str], None],
        process_result: Callable[[str, str], str] | None = None,
    ) -> bool:
        text = str(content or "").strip()
        session_key = self._session_key(chat_id, sender_id, is_group)
        command = self._extract_command(text)
        if command is None and self._is_recent_phone_followup(session_key, text):
            command = text
        is_control = self._is_control_command(text)
        if command is None and not is_control:
            return False
        if not self.enabled:
            on_reply("手机控制功能尚未启用。")
            return True
        if not self._is_authorized(chat_id, sender_id, sender_name, is_group):
            self.logger.warning(
                "Rejected Operit command from chat=%s sender=%s group=%s",
                chat_id,
                sender_id or sender_name,
                is_group,
            )
            if self._is_explicit_command(text) or is_control:
                on_reply("这部手机只接受主人的控制指令。")
            else:
                on_reply("这个我先不帮你查啦。")
            return True

        if command is not None:
            with self._pending_lock:
                self._recent_phone_context[session_key] = time.monotonic()
        lowered = text.lower()
        if lowered in {item.lower() for item in self.STATUS_COMMANDS}:
            self._start_worker(lambda: self.client.health(), on_reply)
            return True
        if lowered in {item.lower() for item in self.RESET_COMMANDS}:
            self.session_store.reset(session_key)
            with self._pending_lock:
                self._pending.pop(session_key, None)
            on_reply("已为这个微信会话创建新的手机任务上下文。")
            return True
        if lowered in {item.lower() for item in self.CANCEL_COMMANDS}:
            with self._pending_lock:
                cancelled = self._pending.pop(session_key, None) is not None
            on_reply("已取消待确认的手机指令。" if cancelled else "当前没有待确认的手机指令。")
            return True

        confirmed_command = self._consume_confirmation(session_key, text)
        if confirmed_command is not None:
            self._dispatch(session_key, confirmed_command, on_reply, process_result)
            return True
        if self._looks_like_confirmation(text):
            on_reply("确认码无效或已过期，请重新发送原手机指令。")
            return True
        if command is None or not command.strip():
            on_reply("请在“手机：”后面写明要执行的操作。")
            return True
        if self.require_confirmation and self._is_sensitive(command):
            code = f"{secrets.randbelow(1_000_000):06d}"
            with self._pending_lock:
                self._pending[session_key] = PendingConfirmation(
                    command=command,
                    code=code,
                    expires_at=time.monotonic() + self.confirmation_ttl_seconds,
                )
            on_reply(
                "这件事会真的改动或发送内容，我先没动。"
                f"\n要继续就在 {int(self.confirmation_ttl_seconds)} 秒内回复：手机确认 {code}"
                "\n不做了就回复：手机取消"
            )
            return True

        self._dispatch(session_key, command, on_reply, process_result)
        return True

    def _dispatch(
        self,
        session_key: str,
        command: str,
        on_reply: Callable[[str], None],
        process_result: Callable[[str, str], str] | None = None,
    ) -> None:
        def work() -> str:
            operit_command = self._prepare_operit_command(command)
            self.logger.info(
                "Operit task started: session=%s command_type=%s",
                session_key,
                self._command_type(command),
            )
            result = self.client.execute(operit_command, self.session_store.get(session_key))
            if result.chat_id:
                self.session_store.set(session_key, result.chat_id)
            raw_result = result.text
            self.logger.info(
                "Operit task returned: session=%s result_chars=%d",
                session_key,
                len(str(raw_result or "")),
            )
            if process_result is not None:
                try:
                    raw_result = process_result(command, raw_result)
                except Exception as exc:
                    self.logger.error(
                        "Failed to rewrite Operit result (%s)",
                        type(exc).__name__,
                        exc_info=True,
                    )
            return compact_phone_reply(raw_result)

        self._start_worker(work, on_reply)

    def _start_worker(self, work: Callable[[], str], on_reply: Callable[[str], None]) -> None:
        def target() -> None:
            try:
                reply = work()
            except OperitError:
                self.logger.warning("Operit task failed", exc_info=True)
                reply = "这次没办成，手机那边没有给出可用结果。"
            except Exception as exc:
                self.logger.error("Unexpected Operit bridge error (%s)", type(exc).__name__, exc_info=True)
                reply = "我这边没弄成，处理时出了点问题。"
            try:
                on_reply(str(reply).strip() or "手机任务已完成。")
            except Exception:
                self.logger.error("Failed to send Operit result to WeChat", exc_info=True)

        threading.Thread(target=target, name="operit-bridge", daemon=True).start()

    def _is_explicit_command(self, text: str) -> bool:
        lowered = str(text or "").strip().lower()
        return any(lowered.startswith(prefix.lower()) for prefix in self.command_prefixes)

    def _command_type(self, command: str) -> str:
        if self.BATTERY_QUERY_RE.search(command):
            return "battery"
        if self.DEVICE_INFO_QUERY_RE.search(command):
            return "device_info"
        if self.NATURAL_STATE_RE.search(command):
            return "device_state"
        return "action"

    def _prepare_operit_command(self, command: str) -> str:
        """Turn casual questions into grounded device tasks for fresh Operit chats."""
        original = str(command or "").strip()
        if self.BATTERY_QUERY_RE.search(original):
            return (
                "请务必实际调用手机系统能力读取当前电池状态，不要凭聊天内容猜测。"
                "明确返回当前电量百分比；如果系统没有读到，就明确说未读取到。"
                f"用户原话：{original}"
            )
        if self.DEVICE_INFO_QUERY_RE.search(original):
            return (
                "请务必实际调用手机系统能力读取本机设备信息，不要使用占位符或猜测。"
                "只返回真实读取到的品牌、型号和对方询问的系统信息；读不到就明确说明。"
                f"用户原话：{original}"
            )
        if self.NATURAL_STATE_RE.search(original):
            return (
                "请实际调用手机能力核实下面的问题，只返回真实读取到的当前状态；"
                "没有读到的数据不要推测。"
                f"用户原话：{original}"
            )
        return original

    def _extract_command(self, text: str) -> str | None:
        lowered = text.lower()
        for prefix in self.command_prefixes:
            if lowered.startswith(prefix.lower()):
                return text[len(prefix):].strip()
        refers_to_owned_phone = (
            any(marker in text for marker in self.NATURAL_PHONE_MARKERS)
            or bool(self.OWNED_PHONE_RE.search(text))
        )
        requests_real_action_or_state = (
            self.NATURAL_ACTION_RE.search(text) or self.NATURAL_STATE_RE.search(text)
        )
        if refers_to_owned_phone and requests_real_action_or_state:
            # Keep the complete natural request. Operit understands ordinary
            # instructions better than a brittle attempt to strip Chinese grammar.
            return text.strip(" \t，,。.!！?？")
        return None

    def _is_control_command(self, text: str) -> bool:
        lowered = text.lower()
        known = self.STATUS_COMMANDS | self.RESET_COMMANDS | self.CANCEL_COMMANDS
        return lowered in {item.lower() for item in known} or self._looks_like_confirmation(text)

    def _is_recent_phone_followup(self, session_key: str, text: str) -> bool:
        if not self.PHONE_FOLLOWUP_RE.search(str(text or "").strip()):
            return False
        now = time.monotonic()
        with self._pending_lock:
            last_at = self._recent_phone_context.get(session_key, 0.0)
            if not last_at or now - last_at > self.phone_context_ttl_seconds:
                self._recent_phone_context.pop(session_key, None)
                return False
        return True

    def _is_authorized(
        self,
        chat_id: str,
        sender_id: str,
        sender_name: str,
        is_group: bool,
    ) -> bool:
        if is_group and not self.allow_group_commands:
            return False
        if self.allowed_chats and str(chat_id) not in self.allowed_chats:
            return False
        identities = {str(sender_id).strip(), str(sender_name).strip()}
        identities.discard("")
        return bool(self.allowed_senders and identities.intersection(self.allowed_senders))

    @staticmethod
    def _session_key(chat_id: str, sender_id: str, is_group: bool) -> str:
        return f"{chat_id}::member::{sender_id}" if is_group else str(chat_id)

    def _is_sensitive(self, command: str) -> bool:
        compact = "".join(str(command).lower().split())
        if any(marker in compact for marker in self.SENSITIVE_MARKERS):
            return True
        return bool(
            re.search(r"(?:给|向).{0,30}(?:发|发送|拨打|打电话|转账|付款)", compact)
        )

    def _looks_like_confirmation(self, text: str) -> bool:
        lowered = text.lower()
        return any(lowered.startswith(prefix.lower()) for prefix in self.CONFIRM_PREFIXES)

    def _consume_confirmation(self, session_key: str, text: str) -> str | None:
        parts = text.split()
        if len(parts) != 2 or not self._looks_like_confirmation(parts[0]):
            return None
        with self._pending_lock:
            pending = self._pending.get(session_key)
            if pending is None:
                return None
            if pending.expires_at <= time.monotonic() or not secrets.compare_digest(pending.code, parts[1]):
                if pending.expires_at <= time.monotonic():
                    self._pending.pop(session_key, None)
                return None
            self._pending.pop(session_key, None)
            return pending.command


def compact_phone_reply(value: str, max_chars: int = 240) -> str:
    """Turn model/tool output into short plain text suitable for WeChat."""

    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"```[^\n]*\n?", "", text)
    text = text.replace("```", "")
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"</?(?:tool|tool_result|status)[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip("，,；;：: ") + "……"
    return text or "手机上的事情处理好了。"
