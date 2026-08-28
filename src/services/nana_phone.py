"""Deterministic client for the self-hosted NanaPhone Android companion."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Any

import requests

from services.operit import OperitError, OperitResult


class NanaPhoneClient:
    """Call NanaPhone's signed HTTP API and map common Chinese requests to actions."""

    BATTERY_RE = re.compile(r"电量|多少电|还有多少电|有没有电|充电|电池")
    DEVICE_RE = re.compile(
        r"型号|机型|品牌|牌子|设备名称|手机信息|系统版本|安卓版本|Android版本|"
        r"配置|处理器|CPU|运行内存|多大内存|容量",
        re.I,
    )
    NETWORK_RE = re.compile(r"联网|网络|信号|Wi-?Fi|流量", re.I)
    STORAGE_RE = re.compile(r"存储|剩余空间|磁盘|内存空间")
    SCREEN_RE = re.compile(r"屏幕上|当前界面|当前页面|页面上|界面上|手机屏幕|看屏幕")
    LAUNCH_RE = re.compile(
        r"(?:打开|启动)(?:一下|下)?(?:你的|你|娜娜的)?手机(?:上|里的)?(?:的)?(.+?)"
        r"(?:看看|看一下|看下)?[。.!！?？]*$"
    )
    SIMPLE_LAUNCH_RE = re.compile(r"(?:打开|启动)(?:一下|下)?(.+?)(?:看看|看一下|看下)?[。.!！?？]*$")
    CLICK_RE = re.compile(r"(?:点击|点一下|点下|按一下|按下)[“\"']?(.+?)[”\"']?[。.!！?？]*$")
    INPUT_RE = re.compile(r"(?:输入|填写|键入)[“\"']?(.+?)[”\"']?[。.!！?？]*$")

    def __init__(
        self,
        base_url: str,
        pairing_token: str,
        timeout_seconds: float = 20.0,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.pairing_token = str(pairing_token or "").strip()
        self.timeout_seconds = max(2.0, float(timeout_seconds))
        self.session = session or requests.Session()
        # This endpoint is a LAN/Tailscale device. System proxy settings (for
        # example Clash on 127.0.0.1) must never intercept local phone traffic.
        self.session.trust_env = False

    def health(self) -> str:
        data = self._request("GET", "/api/v1/health")
        accessibility = bool(data.get("accessibility"))
        suffix = "，无障碍已授权" if accessibility else "，无障碍尚未授权"
        return f"我的手机端在线（{data.get('version', '未知版本')}{suffix}）。"

    def execute(self, command: str, chat_id: str = "") -> OperitResult:
        original = self._original_request(command)
        action, args = self._parse_action(original)
        data = self._request("POST", "/api/v1/action", {"action": action, "args": args})
        result_text = json.dumps(
            {"source": "这部手机的实时系统结果", "action": action, "result": data},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return OperitResult(text=result_text, chat_id="")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.base_url:
            raise OperitError("还没有配置娜娜手机端地址")
        if len(self.pairing_token) < 32:
            raise OperitError("还没有配置有效的娜娜手机端配对密钥")
        body = "" if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(16)
        signing_text = "\n".join((timestamp, nonce, method.upper(), path, body))
        signature = hmac.new(
            self.pairing_token.encode("utf-8"),
            signing_text.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "X-Nana-Timestamp": timestamp,
            "X-Nana-Nonce": nonce,
            "X-Nana-Signature": signature,
            "Content-Type": "application/json; charset=utf-8",
        }
        try:
            response = self.session.request(
                method.upper(),
                self.base_url + path,
                data=body.encode("utf-8") if body else None,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise OperitError("暂时连接不上我的手机端") from exc
        try:
            envelope = response.json()
        except ValueError as exc:
            raise OperitError("手机端返回了无法识别的内容") from exc
        if response.status_code >= 400 or not envelope.get("success"):
            raise OperitError(str(envelope.get("error") or f"手机端 HTTP {response.status_code}"))
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise OperitError("手机端返回格式不正确")
        return data

    @staticmethod
    def _original_request(command: str) -> str:
        text = str(command or "").strip()
        marker = "用户原话："
        return text.rsplit(marker, 1)[-1].strip() if marker in text else text

    def _parse_action(self, text: str) -> tuple[str, dict[str, Any]]:
        compact = re.sub(r"^[\s@]*娜娜[，,:：\s]*", "", str(text or "").strip())
        launch_match = self.LAUNCH_RE.search(compact) or self.SIMPLE_LAUNCH_RE.search(compact)
        state_query = re.search(r"多少|什么|几|查看|查询|读取|告诉|有没有|状态", compact)
        if launch_match and not state_query:
            target = re.sub(
                r"^(?:你的|你|娜娜的)?手机(?:上|里的)?(?:的)?",
                "",
                launch_match.group(1),
            ).strip()
            if target:
                if "电池设置" in target:
                    return "open_settings", {"screen": "battery"}
                if target in {"设置", "系统设置", "手机设置"}:
                    return "open_settings", {"screen": "general"}
                return "launch_app", {"target": target}
        if self.BATTERY_RE.search(compact):
            return "battery", {}
        if self.DEVICE_RE.search(compact):
            return "device_info", {}
        if self.NETWORK_RE.search(compact):
            return "network", {}
        if self.STORAGE_RE.search(compact):
            return "storage", {}
        if self.SCREEN_RE.search(compact):
            return "ui_snapshot", {}
        if re.search(r"(?:返回|退回|回到上一页)", compact):
            return "global_action", {"name": "back"}
        if re.search(r"(?:回到|返回|去)(?:手机)?桌面|按主页|回主页", compact):
            return "global_action", {"name": "home"}
        if re.search(r"最近任务|任务列表|多任务", compact):
            return "global_action", {"name": "recents"}
        if re.search(r"通知栏|下拉通知", compact):
            return "global_action", {"name": "notifications"}
        match = self.CLICK_RE.search(compact)
        if match:
            return "click_text", {"text": match.group(1).strip()}
        match = self.INPUT_RE.search(compact)
        if match:
            return "input_text", {"text": match.group(1).strip()}
        if re.search(r"向上滑|上滑", compact):
            return "swipe", {"x1": 540, "y1": 1700, "x2": 540, "y2": 500, "durationMs": 450}
        if re.search(r"向下滑|下滑", compact):
            return "swipe", {"x1": 540, "y1": 500, "x2": 540, "y2": 1700, "durationMs": 450}
        match = launch_match
        if match:
            target = re.sub(r"^(?:你的|你|娜娜的)?手机(?:上|里的)?(?:的)?", "", match.group(1)).strip()
            if target:
                return "launch_app", {"target": target}
        raise OperitError("这个动作自研手机端暂时还不支持")


def format_nana_phone_result(raw_result: str) -> str | None:
    """Render NanaPhone's structured result without giving an LLM room to guess."""

    try:
        payload = json.loads(str(raw_result or ""))
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("source") != "这部手机的实时系统结果":
        return None
    action = str(payload.get("action") or "")
    result = payload.get("result")
    if not isinstance(result, dict):
        return "这次手机没有返回可用结果。"

    if action == "battery":
        percent = result.get("percent")
        if not isinstance(percent, (int, float)) or percent < 0:
            return "这次没读到我手机的电量。"
        charging = "正在充电" if bool(result.get("charging")) else "没在充电"
        return f"我手机现在 {int(percent)}% 电量，{charging}。"
    if action == "device_info":
        brand = str(result.get("brand") or result.get("manufacturer") or "").strip()
        model = str(result.get("model") or "").strip()
        android = str(result.get("androidVersion") or "").strip()
        pieces = [piece for piece in (brand, model) if piece]
        if not pieces:
            return "这次没读到我手机的型号。"
        suffix = f"，Android {android}" if android else ""
        return f"我的手机是 {' '.join(dict.fromkeys(pieces))}{suffix}。"
    if action == "network":
        if not bool(result.get("connected")):
            return "我手机现在没有联网。"
        names = {"wifi": "Wi-Fi", "cellular": "移动数据", "vpn": "VPN", "ethernet": "有线网络"}
        transport = names.get(str(result.get("transport") or ""), "网络")
        return f"我手机现在通过{transport}联网。"
    if action == "storage":
        total = result.get("totalBytes")
        available = result.get("availableBytes")
        if not isinstance(total, (int, float)) or not isinstance(available, (int, float)):
            return "这次没读到我手机的存储信息。"
        gb = 1024 ** 3
        return f"我手机存储共 {total / gb:.1f} GB，还剩 {available / gb:.1f} GB。"
    if action == "ui_snapshot":
        package_name = str(result.get("packageName") or "").strip()
        nodes = result.get("nodes") if isinstance(result.get("nodes"), list) else []
        visible: list[str] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            value = str(node.get("text") or node.get("description") or "").strip()
            if value and value not in visible:
                visible.append(value)
            if len(visible) >= 8:
                break
        page = f"当前界面（{package_name}）" if package_name else "当前界面"
        return f"我手机{page}上能看到：{' 、'.join(visible)}。" if visible else f"我读到了手机{page}，但没有读到可见文字。"
    if action == "launch_app":
        return "已经在我手机上打开了。" if bool(result.get("launched")) else "这次没能在我手机上打开它。"
    if action == "open_settings":
        return "我已经打开手机设置了。" if bool(result.get("opened")) else "这次没能打开手机设置。"
    if action in {"global_action", "click_text", "input_text", "swipe"}:
        return "手机上已经操作好了。" if bool(result.get("performed")) else "这次手机上没有操作成功。"
    return "手机返回了结果，但我暂时无法确认这个结果。"
