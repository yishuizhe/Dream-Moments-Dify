"""Bundled 50/100-message group summary plugin for Dream."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


class DreamChatSummaryPlugin:
    name = "ChatSummary"
    version = "1.0.0"

    def __init__(self, plugin_dir: str | Path, logger: logging.Logger | None = None) -> None:
        self.plugin_dir = Path(plugin_dir).resolve()
        self.logger = logger or logging.getLogger(__name__)
        self.history_store = None
        self.ai_responder: Callable[[str, str], str] | None = None

    def configure_services(self, *, history_store=None, ai_responder=None, **_: Any) -> None:
        self.history_store = history_store
        self.ai_responder = ai_responder if callable(ai_responder) else None

    def handle_message(self, message: dict[str, Any]) -> str | None:
        if not message.get("is_group") or message.get("is_self"):
            return None
        parsed = self._parse_command(
            str(message.get("content") or ""),
            str(message.get("bot_name") or ""),
        )
        if parsed is None:
            return None
        limit, member_name = parsed
        if self.history_store is None or self.ai_responder is None:
            return "\u804a\u5929\u603b\u7ed3\u670d\u52a1\u5c1a\u672a\u5b8c\u6210\u521d\u59cb\u5316\u3002"

        chat_id = str(message.get("chat_id") or "")
        rows = self.history_store.get_recent_messages(
            chat_id,
            min(limit + 20, 120),
            sender_name=member_name or None,
        )
        rows = [row for row in rows if not self._is_summary_command(str(row.get("content") or ""))]
        rows = rows[-limit:]
        if not rows:
            if member_name:
                return f"\u8fd1\u671f\u6ca1\u6709\u627e\u5230 {member_name} \u7684\u53ef\u603b\u7ed3\u53d1\u8a00\u3002"
            return "\u8fd1\u671f\u8fd8\u6ca1\u6709\u8db3\u591f\u7684\u7fa4\u804a\u8bb0\u5f55\u53ef\u4f9b\u603b\u7ed3\u3002"

        transcript = []
        for row in rows:
            created_at = row.get("created_at")
            time_text = created_at.strftime("%m-%d %H:%M") if isinstance(created_at, datetime) else ""
            name = str(row.get("sender_name") or row.get("sender_id") or "\u672a\u77e5\u6210\u5458")
            content = " ".join(str(row.get("content") or "").split())
            transcript.append(f"[{time_text}] {name}\uff1a{content}")

        scope = (
            f"\u53ea\u603b\u7ed3\u6210\u5458 {member_name} \u7684\u53d1\u8a00"
            if member_name else "\u603b\u7ed3\u6574\u4e2a\u7fa4\u804a"
        )
        prompt = (
            f"\u8bf7{scope}\uff0c\u8bb0\u5f55\u4e0a\u9650\u4e3a {limit} \u6761\u3002\n"
            "\u8bf7\u7b80\u6d01\u8f93\u51fa\uff1a1. \u4e3b\u8981\u8bdd\u9898\uff1b2. \u91cd\u8981\u89c2\u70b9/\u7ed3\u8bba\uff1b3. \u5f85\u529e\u3001\u65f6\u95f4\u70b9\u6216\u4e89\u8bae\uff08\u6ca1\u6709\u5c31\u7701\u7565\uff09\u3002"
            "\u9700\u533a\u5206\u4e0d\u540c\u6210\u5458\uff0c\u4e0d\u8981\u865a\u6784\u3002\n\n"
            + "\n".join(transcript)
        )
        try:
            return str(self.ai_responder(prompt, chat_id) or "").strip() or "\u603b\u7ed3\u751f\u6210\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"
        except Exception as exc:
            self.logger.error("ChatSummary failed (%s)", type(exc).__name__)
            return "\u603b\u7ed3\u751f\u6210\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"

    @classmethod
    def _parse_command(cls, content: str, bot_name: str = "") -> tuple[int, str] | None:
        text = " ".join(str(content or "").strip().split())
        if bot_name:
            text = re.sub(rf"@{re.escape(bot_name)}\s*", "", text).strip()
        direct = re.fullmatch(r"\u603b\u7ed3(?:\u7fa4\u804a)?\s*(?:\u6700\u8fd1)?\s*(50|100)\s*\u6761", text)
        if direct:
            return int(direct.group(1)), ""
        member = re.fullmatch(
            r"\u603b\u7ed3(?:\u7fa4\u804a)?\s+@?(.+?)\s+(?:\u6700\u8fd1)?\s*(50|100)\s*\u6761",
            text,
        )
        if member:
            name = member.group(1).strip().lstrip("@").strip()
            return int(member.group(2)), name
        return None

    @classmethod
    def _is_summary_command(cls, content: str) -> bool:
        return cls._parse_command(content) is not None


def create_plugin(plugin_dir: str | Path, logger: logging.Logger | None = None) -> DreamChatSummaryPlugin:
    return DreamChatSummaryPlugin(plugin_dir=plugin_dir, logger=logger)
