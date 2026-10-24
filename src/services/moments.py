"""WeChat Moments: browse the cached timeline, like/comment, optionally post."""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MomentsService:
    def __init__(
        self,
        *,
        wechat: Any,
        message_handler: Any,
        history_store: Any,
        settings: Any,
        state_path: str | Path,
        contacts: list[str],
        quiet_time: Any = None,
        logger_: logging.Logger | None = None,
    ) -> None:
        self.wx = wechat
        self.message_handler = message_handler
        self.history_store = history_store
        self.settings = settings
        self.state_path = Path(state_path)
        self.contacts = [str(item).strip() for item in contacts if str(item).strip()]
        self.quiet_time = quiet_time
        self.log = logger_ or logger
        self.state = self._load_state()

    def _in_quiet_hours(self) -> bool:
        if self.quiet_time is None:
            return False
        now = datetime.now()

        def parse(value: str, fallback: str) -> tuple[int, int]:
            try:
                hour, minute = str(value or fallback).split(":", 1)
                return max(0, min(23, int(hour))), max(0, min(59, int(minute)))
            except (TypeError, ValueError):
                hour, minute = fallback.split(":", 1)
                return int(hour), int(minute)

        start_h, start_m = parse(getattr(self.quiet_time, "start", "22:00"), "22:00")
        end_h, end_m = parse(getattr(self.quiet_time, "end", "08:00"), "08:00")
        start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
        if start == end:
            return False
        if start < end:
            return start <= now < end
        return now >= start or now < end

    def _load_state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            self.log.warning("朋友圈状态读取失败: %s", exc)
        return {"seen": {}, "liked": [], "day": "", "posts": 0}

    def _save_state(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.state_path)
        except OSError as exc:
            self.log.warning("朋友圈状态写入失败: %s", exc)

    # ------------------------------------------------------------------
    # Policy helpers
    # ------------------------------------------------------------------
    def _allowed_author(self, nickname: str, username: str) -> bool:
        if not bool(getattr(self.settings, "whitelist_only", True)):
            return True
        if nickname and nickname in self.contacts:
            return True
        # A person already registered from private/groups is trusted too.
        try:
            profile = self.history_store.get_person_profile(f"person:{username}")
        except Exception:
            profile = None
        if profile:
            aliases = {str(item) for item in profile.get("aliases") or []}
            return bool(nickname and nickname in aliases) or bool(
                self.contacts and aliases & set(self.contacts)
            )
        return False

    def _remember_person(self, feed: dict) -> None:
        username = str(feed.get("username") or "").strip()
        nickname = str(feed.get("nickname") or "").strip()
        if not username:
            return
        try:
            self.history_store.register_person(
                f"person:{username}",
                nickname,
                chat_id="moments",
                chat_name="朋友圈",
                is_group=False,
                aliases=[nickname],
            )
        except Exception:
            self.log.debug("朋友圈人物登记失败", exc_info=True)

    def _seen(self, tid: str) -> bool:
        return str(tid) in (self.state.get("seen") or {})

    def _mark_seen(self, tid: str) -> None:
        self.state.setdefault("seen", {})[str(tid)] = datetime.now().isoformat(timespec="seconds")
        # Keep the state file small.
        seen = self.state["seen"]
        if len(seen) > 800:
            for key in list(seen)[: len(seen) - 600]:
                seen.pop(key, None)
        self._save_state()

    # ------------------------------------------------------------------
    # Comment generation
    # ------------------------------------------------------------------
    def _comment_text(self, feed: dict) -> str:
        post = " ".join(str(feed.get("text") or "").split())[:300]
        author = str(feed.get("nickname") or "朋友")
        if not post:
            return ""
        prompt = (
            f"朋友圈里「{author}」发了一条动态：\n{post}\n\n"
            "请以你自己的身份写一句很短的评论，像熟人随口接话："
            "可以玩梗、吐槽、关心或接住对方情绪；不要客套，不要用‘哈哈哈’敷衍，"
            "不要提 AI、模型、系统，不要问超过一个的问题。只输出一句，最多 22 个字。"
        )
        try:
            text = self.message_handler.generate_auxiliary_text(
                prompt,
                context_key=f"moment-comment:{feed.get('id')}:{time.time_ns()}",
                is_group=False,
                task_type="moment",
            )
        except Exception:
            self.log.warning("生成朋友圈评论失败", exc_info=True)
            return ""
        return " ".join(str(text or "").split())[:60]

    def _publish_text(self) -> str:
        transcript = ""
        for chat in self.contacts:
            try:
                piece = self.history_store.format_recent_transcript(chat, 20, within_hours=24.0)
            except Exception:
                piece = ""
            if piece:
                transcript += f"\n[{chat}]\n{piece}"
            if len(transcript) > 1800:
                break
        prompt = (
            "你要发一条微信朋友圈。结合你最近和朋友的聊天、你自己的生活状态和一点小情绪，"
            "写一条 40 到 90 字的朋友圈文案：可以吐槽、发牢骚、晒心情或玩自己的梗，"
            "要像真人随手发的，不要写成总结，不要提 AI、模型、系统、API，不要用 Markdown。"
            + (f"\n\n最近的聊天（只作灵感，不要照抄）：\n{transcript}" if transcript else "")
        )
        try:
            text = self.message_handler.generate_auxiliary_text(
                prompt,
                context_key=f"moment-publish:{time.time_ns()}",
                is_group=False,
                task_type="moment",
            )
        except Exception:
            self.log.warning("生成朋友圈文案失败", exc_info=True)
            return ""
        return str(text or "").strip()[:300]

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------
    def run(self, stop_event: threading.Event) -> None:
        if not bool(getattr(self.settings, "enabled", False)):
            self.log.info("朋友圈功能未启用")
            return
        self.log.info(
            "朋友圈功能已启用（间隔 %.0f 分钟，点赞 %.0f%%，评论 %.0f%%，发布 %s）",
            float(getattr(self.settings, "browse_interval_minutes", 45.0)),
            float(getattr(self.settings, "like_probability", 0.35)) * 100,
            float(getattr(self.settings, "comment_probability", 0.12)) * 100,
            "开" if getattr(self.settings, "publish_enabled", False) else "关",
        )
        # Give the bot a quiet start: the first browse happens after a short
        # grace period instead of touching the WeChat UI during login.
        if stop_event.wait(300.0):
            return
        while not stop_event.is_set():
            try:
                self._tick()
            except Exception:
                self.log.exception("朋友圈循环异常")
            stop_event.wait(max(300.0, float(getattr(self.settings, "browse_interval_minutes", 45.0)) * 60.0))

    def _tick(self) -> None:
        if self._in_quiet_hours():
            return
        feed = self.wx.moment_feed(limit=20)
        if not feed:
            self.log.debug("朋友圈缓存为空或后端不支持")
            return
        actions = 0
        max_actions = max(1, int(getattr(self.settings, "max_actions_per_run", 3)))
        for item in feed:
            tid = str(item.get("id") or item.get("tid") or "")
            if not tid or self._seen(tid):
                continue
            username = str(item.get("username") or "")
            nickname = str(item.get("nickname") or username)
            created = int(item.get("create_time") or 0)
            if created and time.time() - created > 48 * 3600:
                self._mark_seen(tid)
                continue
            if not self._allowed_author(nickname, username):
                self._mark_seen(tid)
                continue
            self._remember_person(item)
            if actions >= max_actions:
                break
            text = str(item.get("text") or "")
            if text and random.random() < float(getattr(self.settings, "like_probability", 0.35)):
                if tid not in (self.state.get("liked") or []):
                    if self.wx.like_moment(nickname):
                        self.state.setdefault("liked", []).append(tid)
                        actions += 1
                        self.log.info("朋友圈点赞: %s", nickname)
            if text and random.random() < float(getattr(self.settings, "comment_probability", 0.12)):
                comment = self._comment_text(item)
                if comment and self.wx.comment_moment(nickname, comment):
                    actions += 1
                    self.log.info("朋友圈评论 %s: %s", nickname, comment)
            self._mark_seen(tid)
        self._maybe_publish()

    def _maybe_publish(self) -> None:
        if not bool(getattr(self.settings, "publish_enabled", False)):
            return
        today = datetime.now().strftime("%Y-%m-%d")
        if self.state.get("day") != today:
            self.state["day"] = today
            self.state["posts"] = 0
        if int(self.state.get("posts") or 0) >= 2:
            return
        if random.random() >= float(getattr(self.settings, "publish_probability", 0.02)):
            return
        text = self._publish_text()
        if not text:
            return
        if self.wx.publish_moment(text):
            self.state["posts"] = int(self.state.get("posts") or 0) + 1
            self._save_state()
            self.log.info("已尝试发布朋友圈: %s", text[:40])
