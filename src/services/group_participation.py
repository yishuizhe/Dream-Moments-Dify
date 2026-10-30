"""Message-driven group participation. No timers that start conversations."""

from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, fields
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class GroupPolicySettings:
    enabled: bool = False
    repeat_enabled: bool = True
    novelty_repeat_enabled: bool = True
    sample_probability: float = 0.25
    cooldown_seconds: float = 60.0
    decision_interval_seconds: float = 20.0
    max_per_hour: int = 6
    repeat_window_seconds: float = 120.0
    max_message_age_seconds: float = 30.0
    followup_window_seconds: float = 180.0
    followup_cooldown_seconds: float = 0.0
    followup_max_per_minute: int = 6
    followup_max_per_hour: int = 60

    @classmethod
    def load(cls, path):
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            allowed = {f.name for f in fields(cls)}
            # Bad or hand-edited settings disable participation instead of
            # producing an unbounded reply loop.
            settings = cls(**{k: v for k, v in payload.items() if k in allowed})
            for key in ("enabled", "repeat_enabled", "novelty_repeat_enabled"):
                if not isinstance(getattr(settings, key), bool):
                    raise ValueError(key)
            for key in allowed - {"enabled", "repeat_enabled", "novelty_repeat_enabled"}:
                if not isinstance(getattr(settings, key), (int, float)) or getattr(settings, key) < 0:
                    raise ValueError(key)
            return settings
        except (OSError, ValueError, TypeError, AttributeError):
            return cls()


class GroupParticipation:
    def __init__(self, settings=None, *, clock=time.monotonic, rng=random.random):
        self.settings = settings or GroupPolicySettings()
        self.clock, self.rng = clock, rng
        self._lock = threading.RLock()
        self._worker = threading.BoundedSemaphore(1)
        self._groups = {}
        self._followup_pending = {}
        self._followup_running = set()

    def _state(self, chat_id):
        return self._groups.setdefault(str(chat_id), {
            "messages": deque(maxlen=32), "sent": deque(), "repeated": {},
            "last_bot": None, "last_decision": None, "generation": 0,
            "last_target": "", "continuations": deque(),
        })

    @staticmethod
    def repeatable(text):
        value = str(text or "").strip()
        return bool(2 <= len(value) <= 120 and not re.search(
            r"https?://|wxid_|@|拍了拍|拍一拍|撤回|<[^>]+>|[\r\n]|^[/／]|"
            r"^\[(图片|动画表情|语音|视频|文件|链接)\]$|"
            r"(?:\d[ -]?){7,}|验证码|密码|身份证|银行卡", value
        ))

    def note_bot_reply(self, chat_id, text, *, sender_id="", kind="chat"):
        with self._lock:
            state = self._state(chat_id)
            state["last_bot"] = self.clock()
            state["generation"] += 1
            state["messages"].append((self.clock(), "bot", "机器人", str(text)[:300]))
            # Automated repeats do not become an invitation to a new thread.
            state["last_target"] = str(sender_id) if kind == "chat" else ""

    def _allowed(self, state, now):
        while state["sent"] and now - state["sent"][0] >= 3600:
            state["sent"].popleft()
        return (len(state["sent"]) < self.settings.max_per_hour
                and (state["last_bot"] is None
                     or now - state["last_bot"] >= self.settings.cooldown_seconds))

    def _followup_allowed(self, state, now):
        history = state["continuations"]
        while history and now - history[0] >= 3600:
            history.popleft()
        return (len(history) < self.settings.followup_max_per_hour
                and sum(now - at < 60 for at in history) < self.settings.followup_max_per_minute
                and state["last_bot"] is not None
                and self.settings.followup_cooldown_seconds <= now - state["last_bot"]
                <= self.settings.followup_window_seconds)

    def observe(self, chat_id, sender_id, sender_name, text, *, explicit=False, reply_to_other=False):
        """Return repeat/chat candidate metadata, keeping each group independent."""
        if not self.settings.enabled or not sender_id:
            return None
        text = str(text or "").strip()
        now = self.clock()
        with self._lock:
            state = self._state(chat_id)
            state["generation"] += 1
            previous = list(state["messages"])
            state["messages"].append((now, sender_id, sender_name, text[:300]))
            state["repeated"] = {k: v for k, v in state["repeated"].items() if now - v < 600}
            if explicit:
                self._followup_pending.pop(str(chat_id), None)
                return None
            repeat_allowed = self._allowed(state, now)
            can_repeat = self.repeatable(text)
            normalized = re.sub(r"\s+", " ", text)
            if normalized in state["repeated"]:
                return None
            if can_repeat and repeat_allowed and self.settings.repeat_enabled and previous:
                last = previous[-1]
                if (now - last[0] <= self.settings.repeat_window_seconds
                        and last[1] not in {"bot", sender_id}
                        and re.sub(r"\s+", " ", last[3]) == normalized):
                    return {"action": "repeat", "text": text, "time": now,
                            "generation": state["generation"]}
            # Follow-up conversation has its own budget; the spontaneous
            # intervention cooldown and eight-character gate do not apply.
            target = state["last_target"]
            direct_continuation = (target == str(sender_id) or bool(
                target and state["last_bot"] is not None and now - state["last_bot"] < 45
                and re.match(r"^(?:你|那你|所以你|然后呢|为什么|怎么|所以呢|继续)", text)))
            if (not reply_to_other and direct_continuation and 2 <= len(text) <= 4000
                    and not re.search(r"@|<[^>]+>|^[/／]", text)
                    and self._followup_allowed(state, now)
                    and not re.fullmatch(r"[嗯哦好哈呵啊]+[。！!~～]*", text)):
                transcript = "\n".join(f"{name}：{content}" for at, _, name, content in state["messages"]
                                       if now - at <= 300)
                return {"action": "decide", "mode": "followup", "text": text,
                        "transcript": transcript, "time": now, "sender_id": str(sender_id),
                        "generation": state["generation"]}
            if not can_repeat or not repeat_allowed or reply_to_other:
                return None
            # No model calls for acknowledgements or low-information fragments.
            if len(text) < 8 or re.fullmatch(r"[哈啊哦嗯好笑草艹？！!?。\s]+", text):
                return None
            last_decision = state["last_decision"]
            if last_decision is not None and now - last_decision < self.settings.decision_interval_seconds:
                return None
            novelty = bool(re.search(r"猎奇|离谱|逆天|抽象|绷不住|震惊|居然|竟然", text))
            followup = state["last_bot"] is not None and now - state["last_bot"] < 180
            if not novelty and not followup and self.rng() >= self.settings.sample_probability:
                return None
            state["last_decision"] = now
            transcript = "\n".join(
                f"{name}：{content}" for at, _, name, content in state["messages"]
                if now - at <= 180
            )
            return {"action": "decide", "text": text, "transcript": transcript,
                    "time": now, "generation": state["generation"]}

    def commit(self, chat_id, candidate, action):
        """Recheck after model latency; a newer message/reply invalidates the job."""
        with self._lock:
            state = self._state(chat_id)
            now = self.clock()
            followup = candidate.get("mode") == "followup"
            if followup and action != "chat":
                return False
            allowed = self._followup_allowed(state, now) if followup else self._allowed(state, now)
            if (not self.settings.enabled or not allowed
                    or candidate["generation"] != state["generation"]
                    or now - candidate["time"] > self.settings.max_message_age_seconds):
                return False
            if action == "repeat":
                if not self.settings.repeat_enabled:
                    return False
                normalized = re.sub(r"\s+", " ", candidate["text"])
                if normalized in state["repeated"]:
                    return False
                state["repeated"][normalized] = now
            if followup:
                state["continuations"].append(now)
            else:
                state["sent"].append(now)
            state["last_bot"] = now
            return True

    def is_current(self, chat_id, generation):
        with self._lock:
            return self.settings.enabled and self._state(chat_id)["generation"] == generation

    def submit(self, chat_id, candidate, decide, on_action):
        """One background decision at a time, leaving WeChat polling responsive."""
        if candidate.get("mode") == "followup":
            return self._submit_followup(chat_id, candidate, decide, on_action)
        needs_model = candidate["action"] == "decide"
        if needs_model and not self._worker.acquire(blocking=False):
            return False

        def run():
            try:
                action = candidate["action"]
                if action == "decide":
                    action = decide(candidate["transcript"], candidate["text"])
                    if action == "repeat" and not self.settings.novelty_repeat_enabled:
                        action = "pass"
                if action in {"chat", "repeat"} and self.commit(chat_id, candidate, action):
                    on_action(action)
            except Exception:
                logger.exception("群聊参与任务失败: %s", chat_id)
            finally:
                if needs_model:
                    self._worker.release()

        threading.Thread(target=run, daemon=True, name="group-participation").start()
        return True

    def _submit_followup(self, chat_id, candidate, decide, on_action):
        """Coalesce short successive turns; never lose the latest while busy."""
        key = str(chat_id)
        with self._lock:
            self._followup_pending[key] = (candidate, decide, on_action)
            if key in self._followup_running:
                return True
            self._followup_running.add(key)

        def run():
            try:
                while True:
                    # A short batching window catches "怎么样" / "怎么用"
                    # instead of abandoning the second line during inference.
                    time.sleep(0.8)
                    with self._lock:
                        job = self._followup_pending.pop(key, None)
                        if job is None:
                            self._followup_running.discard(key)
                            return
                    current, gate, callback = job
                    action = gate(current["transcript"], current["text"])
                    if action == "chat" and self.commit(key, current, "chat"):
                        callback("chat")
                    with self._lock:
                        if key not in self._followup_pending:
                            self._followup_running.discard(key)
                            return
            except Exception:
                logger.exception("群聊续聊任务失败: %s", key)
                with self._lock:
                    self._followup_running.discard(key)
                    self._followup_pending.pop(key, None)

        threading.Thread(target=run, daemon=True, name="group-followup").start()
        return True
