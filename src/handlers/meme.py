"""Context-aware meme (梗图) selection for chat replies.

The picker keeps a small local index (``memes/index.json``) produced by
``tools/collect_memes.py``. Each entry carries free-form Chinese tags; a reply
is matched against the current user message plus the generated reply, so the
image follows the topic instead of being purely random.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from collections import deque
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")

FAMILY_KEYWORDS = {
    "claude": ("claude", "克劳德", "大小姐", "anthropic", "小克"),
    "deepseek": ("deepseek", "深度求索", "大肥鱼", "鲸鱼", "白饭", "token"),
    "gpt": ("gpt", "chatgpt", "openai", "奥特曼"),
    "gemini": ("gemini", "谷歌", "谷歌娘"),
    "kimi": ("kimi", "月之暗面"),
}


class MemeHandler:
    """Pick a meme whose tags overlap with the current conversation."""

    def __init__(
        self,
        root_dir: str | os.PathLike[str],
        avatar_dir: str = "data/avatars/Claude",
        *,
        cooldown_seconds: float = 300.0,
        max_per_hour: int = 6,
        probability: float = 0.35,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.avatar_root = (self.root_dir / avatar_dir).resolve()
        self.meme_root = self.avatar_root / "memes"
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.max_per_hour = max(1, int(max_per_hour))
        self.probability = min(1.0, max(0.0, float(probability)))
        self.entries: list[dict] = []
        self._last_sent_at: dict[str, float] = {}
        self._sent_history: dict[str, deque[float]] = {}
        self._recent_picks: deque[str] = deque(maxlen=12)
        self.reload()

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------
    def reload(self) -> None:
        self.entries = []
        index_path = self.meme_root / "index.json"
        if index_path.is_file():
            try:
                payload = json.loads(index_path.read_text(encoding="utf-8"))
                for entry in payload.get("entries", []):
                    relative = str(entry.get("file") or "").replace("\\", "/")
                    if not relative:
                        continue
                    path = (self.avatar_root / relative).resolve()
                    if not path.is_file():
                        continue
                    tags = entry.get("tags") or []
                    if isinstance(tags, str):
                        tags = [item for item in tags.split(",") if item]
                    self.entries.append({
                        "path": str(path),
                        "family": str(entry.get("family") or "meme"),
                        "tags": [str(tag).strip() for tag in tags if str(tag).strip()],
                        "caption": str(entry.get("caption") or ""),
                    })
            except Exception as exc:  # noqa: BLE001 - a broken index must not stop chat
                logger.warning("读取梗图索引失败: %s", exc)
        if self.entries:
            return
        # Fallback: whatever images actually exist on disk.
        for path in self.meme_root.rglob("*"):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                self.entries.append({
                    "path": str(path),
                    "family": path.parent.name,
                    "tags": [],
                    "caption": path.stem,
                })
        logger.info("梗图库已加载: %s 张", len(self.entries))

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize(text: str) -> str:
        return str(text or "").lower()

    def score(self, entry: dict, text: str) -> float:
        haystack = self._normalize(text)
        if not haystack:
            return 0.0
        score = 0.0
        for tag in entry["tags"]:
            if tag and tag.lower() in haystack:
                score += max(1.0, min(3.0, len(tag) / 2.0))
        family = entry.get("family") or ""
        for word in FAMILY_KEYWORDS.get(family, ()):
            if word.lower() in haystack:
                score += 1.5
        caption = entry.get("caption") or ""
        if caption and caption in text:
            score += 2.0
        return score

    def is_explicit_request(self, text: str) -> bool:
        keywords = ("来个梗图", "来点梗图", "斗图", "发个表情包", "来个表情包", "表情包呢")
        return any(keyword in str(text or "") for keyword in keywords)

    def _rate_limited(self, chat_id: str, now: float) -> bool:
        key = str(chat_id or "")
        if not key:
            return False
        if now - self._last_sent_at.get(key, 0.0) < self.cooldown_seconds:
            return True
        history = self._sent_history.setdefault(key, deque(maxlen=self.max_per_hour * 4))
        while history and now - history[0] > 3600:
            history.popleft()
        return len(history) >= self.max_per_hour

    def _remember(self, chat_id: str, path: str, now: float) -> None:
        key = str(chat_id or "")
        if key:
            self._last_sent_at[key] = now
            self._sent_history.setdefault(key, deque(maxlen=self.max_per_hour * 4)).append(now)
        self._recent_picks.append(path)

    def pick(
        self,
        text: str,
        chat_id: str = "",
        *,
        explicit: bool = False,
        probability: Optional[float] = None,
    ) -> Optional[str]:
        if not self.entries:
            return None
        now = time.monotonic()
        if self._rate_limited(chat_id, now):
            logger.debug("梗图冷却/限流中，跳过: %s", chat_id)
            return None
        chance = self.probability if probability is None else probability
        if not explicit and random.random() > chance:
            return None

        scored = [
            (self.score(entry, text), entry)
            for entry in self.entries
            if entry["path"] not in self._recent_picks
        ]
        scored = [(value, entry) for value, entry in scored if value > 0]
        if not scored:
            if not explicit:
                return None
            scored = [(1.0, entry) for entry in self.entries if entry["path"] not in self._recent_picks]
        if not scored:
            return None
        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = scored[:5]
        weights = [max(1.0, score) for score, _ in top]
        _, chosen = random.choices(top, weights=weights, k=1)[0]
        self._remember(chat_id, chosen["path"], now)
        logger.info("选择梗图: %s (%s)", Path(chosen["path"]).name, chosen.get("caption", ""))
        return chosen["path"]
