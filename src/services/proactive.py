"""Whitelist-only unprompted messages (主动消息) with optional WeChat pokes.

The service never talks to a chat outside ``listen_list``, respects quiet
hours, keeps a persistent per-chat schedule and refuses to speak when the bot
itself replied moments ago.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ProactiveService:
    def __init__(
        self,
        *,
        wechat: Any,
        message_handler: Any,
        history_store: Any,
        settings: Any,
        quiet_time: Any,
        state_path: str | Path,
        is_group: Callable[[str], bool],
        logger_: logging.Logger | None = None,
    ) -> None:
        self.wx = wechat
        self.message_handler = message_handler
        self.history_store = history_store
        self.settings = settings
        self.quiet_time = quiet_time
        self.state_path = Path(state_path)
        self.is_group = is_group
        self.log = logger_ or logger
        self._lock = threading.Lock()
        self.state: dict[str, Any] = self._load_state()

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def _load_state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            self.log.warning("主动消息状态读取失败: %s", exc)
        return {"chats": {}, "day": "", "count": 0}

    def _save_state(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.state_path)
        except OSError as exc:
            self.log.warning("主动消息状态写入失败: %s", exc)

    def _reset_daily_counter(self, now: datetime) -> None:
        today = now.strftime("%Y-%m-%d")
        if self.state.get("day") != today:
            self.state["day"] = today
            self.state["count"] = 0

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_hhmm(value: str, fallback: str) -> tuple[int, int]:
        text = str(value or fallback)
        try:
            hour, minute = text.split(":", 1)
            return max(0, min(23, int(hour))), max(0, min(59, int(minute)))
        except (TypeError, ValueError):
            hour, minute = fallback.split(":", 1)
            return int(hour), int(minute)

    def in_quiet_hours(self, now: datetime | None = None) -> bool:
        current = now or datetime.now()
        start_h, start_m = self._parse_hhmm(getattr(self.quiet_time, "start", "22:00"), "22:00")
        end_h, end_m = self._parse_hhmm(getattr(self.quiet_time, "end", "08:00"), "08:00")
        start = current.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        end = current.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
        if start == end:
            return False
        if start < end:
            return start <= current < end
        return current >= start or current < end

    def _next_interval(self) -> float:
        low = max(5.0, float(getattr(self.settings, "min_minutes", 120.0)))
        high = max(low, float(getattr(self.settings, "max_minutes", 300.0)))
        return random.uniform(low, high) * 60.0

    def _due(self, chat: str, now: float) -> bool:
        entry = self.state["chats"].get(chat) or {}
        if "next_at" not in entry:
            entry["next_at"] = now + self._next_interval()
            self.state["chats"][chat] = entry
            return False
        return now >= float(entry.get("next_at") or 0.0)

    def _mark_sent(self, chat: str) -> None:
        now = time.time()
        entry = self.state["chats"].setdefault(chat, {})
        entry["last_sent"] = now
        entry["next_at"] = now + self._next_interval()
        self.state["count"] = int(self.state.get("count") or 0) + 1
        self._save_state()

    def _recent_bot_reply(self, chat: str, seconds: float = 600.0) -> bool:
        try:
            rows = self.history_store.get_recent_messages(chat, 3)
        except Exception:
            return False
        for row in rows:
            if str(row.get("role") or "") != "assistant":
                continue
            created = row.get("created_at")
            if isinstance(created, datetime) and (datetime.now() - created).total_seconds() < seconds:
                return True
        return False

    def _latest_message_age_minutes(self, chat: str) -> float | None:
        try:
            rows = self.history_store.get_recent_messages(chat, 1)
        except Exception:
            return None
        if not rows:
            return None
        created = rows[-1].get("created_at")
        if not isinstance(created, datetime):
            return None
        return max(0.0, (datetime.now() - created).total_seconds() / 60.0)

    def _transcript(self, chat: str, *, is_group: bool) -> str:
        try:
            return self.history_store.format_recent_transcript(
                chat, 30 if is_group else 12, within_hours=4.0 if is_group else 24.0
            )
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------
    def _pick_chat(self) -> tuple[str, bool] | None:
        now = time.time()
        targets = {
            str(item).strip()
            for item in (getattr(self.settings, "chat_targets", []) or [])
            if str(item).strip()
        }
        candidates: list[tuple[str, bool]] = []
        for chat in list(getattr(self.wx, "contacts", []) or []):
            name = str(chat or "").strip()
            if not name:
                continue
            if targets and name not in targets:
                continue
            group = bool(self.is_group(name))
            if group and not bool(getattr(self.settings, "group_enabled", True)):
                continue
            if not group and not bool(getattr(self.settings, "private_enabled", True)):
                continue
            if self._due(name, now):
                candidates.append((name, group))
        if not candidates:
            return None
        return random.choice(candidates)

    def run(self, stop_event: threading.Event) -> None:
        if not bool(getattr(self.settings, "enabled", False)):
            self.log.info("主动消息未启用")
            return
        self.log.info(
            "主动消息已启用（私聊 %s / 群聊 %s，间隔 %.0f-%.0f 分钟）",
            "开" if getattr(self.settings, "private_enabled", True) else "关",
            "开" if getattr(self.settings, "group_enabled", True) else "关",
            float(getattr(self.settings, "min_minutes", 120.0)),
            float(getattr(self.settings, "max_minutes", 300.0)),
        )
        targets = [
            str(item).strip()
            for item in (getattr(self.settings, "chat_targets", []) or [])
            if str(item).strip()
        ]
        if targets:
            self.log.info("主动消息仅限: %s", "、".join(targets))
        while not stop_event.is_set():
            try:
                self._tick()
            except Exception:
                self.log.exception("主动消息循环异常")
            stop_event.wait(60.0)

    def _tick(self) -> None:
        if not bool(getattr(self.settings, "enabled", False)):
            return
        now = datetime.now()
        self._reset_daily_counter(now)
        if self.in_quiet_hours(now):
            return
        if int(self.state.get("count") or 0) >= 8:
            # Hard daily safety cap across all chats.
            return
        picked = self._pick_chat()
        if picked is None:
            return
        chat, is_group = picked
        if self._recent_bot_reply(chat):
            return
        self._mark_sent(chat)
        age = self._latest_message_age_minutes(chat)
        mode = "join" if is_group and age is not None and age <= 45 else "start"
        transcript = self._transcript(chat, is_group=is_group)
        if not is_group and bool(getattr(self.settings, "poke_probability", 0.0)):
            if random.random() < float(getattr(self.settings, "poke_probability", 0.0)):
                ok = False
                try:
                    ok = bool(self.wx.poke(chat))
                except Exception:
                    ok = False
                if ok:
                    self.log.info("主动戳一戳: %s", chat)
                    return
        reply = self.message_handler.generate_proactive_message(
            chat,
            is_group=is_group,
            transcript=transcript,
            mode=mode,
        )
        reply = str(reply or "").strip()
        if not reply:
            return
        self.wx.send_text(chat, reply)
        try:
            self.history_store.record_message(
                chat_id=chat,
                sender_id="bot",
                sender_name="AI",
                role="assistant",
                content=reply,
                is_group=is_group,
            )
        except Exception:
            self.log.debug("记录主动消息失败", exc_info=True)
        self.log.info("主动消息已发送 -> %s: %s", chat, reply[:40])
