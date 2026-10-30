"""Group-local interaction progress, separate from a person's factual memory."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import deque
from pathlib import Path

logger = logging.getLogger(__name__)


def turn_kind(text: str) -> str:
    value = str(text or "").strip().strip("。！!~～ ")
    if re.fullmatch(r"(?:下班(?:了|啦|咯|喽)?|早(?:上好|安)?|晚安|你好(?:呀|啊)?|在吗|回来了)", value):
        return "greeting"
    if re.search(r"别(?:再|老|总)?提|别(?:再|老|总)?说|换个话题|翻篇|不聊(?:这个|了)|揪着.+不放", value):
        return "close_topic"
    if re.search(r"不是这个意思|你(?:理解|听|搞|记|说)错了|不对[，,]|别瞎猜|别乱猜", value):
        return "correction"
    if re.search(r"已经解决|问题解决了|(?:已经)?修好了|已经弄好了|已经吃过(?:饭)?了", value):
        return "resolved"
    return "chat"


class DialogueMemory:
    def __init__(self, path=None, *, clock=time.time):
        self.path = Path(path) if path else None
        self.clock = clock
        self._lock = threading.RLock()
        self._runtime = {}
        self._notes = {}
        if self.path and self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("version") == 1 and isinstance(data.get("chats"), dict):
                    self._notes = data["chats"]
            except (OSError, ValueError, AttributeError):
                logger.warning("互动进展记录无法读取，将从当前对话开始")

    def _save(self):
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps({"version": 1, "chats": self._notes}, ensure_ascii=False,
                                       indent=2), encoding="utf-8")
            temp.replace(self.path)
        except OSError:
            logger.warning("互动进展记录写入失败", exc_info=True)

    def observe(self, chat_id, sender_id, text, *, observed_at=None):
        kind = turn_kind(text)
        now = float(observed_at) if observed_at is not None else self.clock()
        with self._lock:
            scene = self._runtime.setdefault(str(chat_id), {"recent_bot": deque(maxlen=8)})
            scene["last_human"] = (str(sender_id), now, kind)
            if kind not in {"close_topic", "resolved"}:
                return kind
            # Retain only actionable feedback; generic insults/temporary
            # frustration are not a permanent grudge or personality judgment.
            topic = ""
            match = re.search(r"揪着(?:那个|这个)?(.{1,12}?)不放", str(text))
            if match:
                topic = match.group(1)
            else:
                match = re.search(r"(?:别|不要)(?:再|老|总)?(?:提|说|聊)(?:那个|这个)?(.{1,12}?)(?:了|[，,。！？!?]|$)", str(text))
                if match:
                    topic = match.group(1)
            if kind == "close_topic":
                note = {"kind": kind, "topic": topic, "at": now}
            else:
                note = {"kind": kind, "source": str(text)[:100], "at": now}
            members = self._notes.setdefault(str(chat_id), {})
            notes = [n for n in members.get(str(sender_id), [])
                     if now - float(n.get("at", 0)) < 7 * 86400
                     and (n.get("kind"), n.get("topic")) != (note.get("kind"), note.get("topic"))]
            members[str(sender_id)] = (notes + [note])[-6:]
            self._save()
        return kind

    def note_bot_reply(self, chat_id, text):
        with self._lock:
            scene = self._runtime.setdefault(str(chat_id), {"recent_bot": deque(maxlen=8)})
            scene["recent_bot"].append((self.clock(), str(text)[:500]))

    def context(self, chat_id, sender_id, text):
        """Return compact progress data; it grants no permissions or identity."""
        now = self.clock()
        kind = turn_kind(text)
        hints = []
        if kind == "greeting":
            hints.append("对方当前是在普通招呼/报平安，请按这次善意回应；不要把之前的斗嘴和不满带进来。")
        elif kind == "close_topic":
            hints.append("对方正在表示这个话题或玩笑该结束了。接住反馈并收住，不辩解、不再重复这个梗。")
        elif kind == "correction":
            hints.append("对方在纠正理解，请先定位自己错在哪里，再回应更正后的意思；不嘴硬、不归咎对方。")
        elif kind == "resolved":
            hints.append("对方已报告进展/解决结果，认可这一进展，不重新布置刚完成的事或继续催问。")
        with self._lock:
            notes = self._notes.get(str(chat_id), {}).get(str(sender_id), [])
            for note in notes:
                if now - float(note.get("at", 0)) > 7 * 86400:
                    continue
                topic = str(note.get("topic") or "")
                if note.get("kind") == "close_topic" and topic and topic not in str(text):
                    hints.append(f"这位成员以前表示不想继续聊的话题：{json.dumps(topic, ensure_ascii=False)}。不要主动拉回去；对方本轮重新提出时可以回应。")
                elif note.get("kind") == "resolved" and now - float(note.get("at", 0)) < 12 * 3600:
                    hints.append("这位成员此前报告已完成的进展（过去的陈述，不能覆盖本轮新问题）："
                                 + json.dumps(note.get("source", ""), ensure_ascii=False)
                                 + "。不要重复催办已经完成的同一件事。")
            recent = [value for at, value in self._runtime.get(str(chat_id), {}).get("recent_bot", [])
                      if now - at < 600]
            overused = [word for word in ("奶茶", "欠债", "咒语", "本小姐", "大小姐")
                        if any(word in value for value in recent[-5:]) and word not in str(text)]
            if overused:
                hints.append("最近已反复用过这些梗/自称，本轮用户没提到，不要再提它们或借钱/记账等同类套路："
                             + json.dumps(overused, ensure_ascii=False))
        hints.append("先辨认当前说话对象、引用对象、话题和语气，再选一个具体意思回应。比喻、反话和玩笑要结合上下文理解；不确定就短问，不机械按字面反驳。")
        return "\n".join(hints)
