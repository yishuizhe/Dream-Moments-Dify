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
import re
import time
from collections import deque
from pathlib import Path
from typing import Optional
from PIL import Image

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
        self._recent_picks: dict[str, deque[str]] = {}
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
                    if self.avatar_root not in path.parents or not self._usable_image(path):
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
        # Unindexed images have no meaning attached. Do not randomly send them.
        logger.info("梗图库已加载: %s 张", len(self.entries))

    @staticmethod
    def _usable_image(path: Path) -> bool:
        try:
            if path.suffix.lower() not in IMAGE_SUFFIXES or path.stat().st_size > 20_000_000:
                return False
            with Image.open(path) as image:
                if min(image.size) < 128:
                    return False
                image.verify()
            return True
        except (OSError, ValueError, Image.DecompressionBombError):
            return False

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
        identity_tags = {"claude", "克劳德", "大小姐", "anthropic", "小克", "deepseek",
                         "深度求索", "大肥鱼", "鲸鱼", "gpt", "chatgpt", "openai",
                         "奥特曼", "gemini", "谷歌", "谷歌娘", "kimi", "月之暗面"}
        for tag in entry["tags"]:
            # Single glyphs such as 编/听/钱 match unrelated sentences.
            # A character's name also says nothing about the picture's meaning.
            if len(tag) >= 2 and tag.lower() not in identity_tags and tag.lower() in haystack:
                hits = list(re.finditer(re.escape(tag.lower()), haystack))
                if any(not re.search(r"(?:不|没|别|不是|并不|不用|没有|不要)(?:太|再|很|想|会|那么|这么)?$",
                                     haystack[max(0, hit.start()-8):hit.start()]) for hit in hits):
                    score += max(1.0, min(3.0, len(tag) / 2.0))
        caption = entry.get("caption") or ""
        if len(caption) >= 2 and caption.lower() in haystack:
            hits = list(re.finditer(re.escape(caption.lower()), haystack))
            if any(not re.search(r"(?:不|没|别|不是|并不|不用|没有|不要)(?:太|再|很|想|会|那么|这么)?$",
                                 haystack[max(0, hit.start()-8):hit.start()]) for hit in hits):
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
        self._recent_picks.setdefault(key, deque(maxlen=8)).append(path)

    def pick(
        self,
        text: str,
        chat_id: str = "",
        *,
        explicit: bool = False,
        probability: Optional[float] = None,
        reply_text: str = "",
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

        recent = self._recent_picks.get(str(chat_id or ""), ())
        scored = [
            (self.score(entry, text) + 2 * self.score(entry, reply_text), entry)
            for entry in self.entries
            if entry["path"] not in recent
            and self._usable_image(Path(entry["path"]))
            and (not reply_text or explicit or self.score(entry, reply_text) > 0)
        ]
        scored = [(value, entry) for value, entry in scored if value > 0]
        if not scored:
            if not explicit:
                return None
            scored = [(1.0, entry) for entry in self.entries
                      if entry["path"] not in recent and self._usable_image(Path(entry["path"]))]
        if not scored:
            return None
        scored.sort(key=lambda pair: pair[0], reverse=True)
        # Randomness may vary equivalent pictures, never relax relevance.
        top = [pair for pair in scored if pair[0] >= scored[0][0] * 0.85]
        weights = [max(1.0, score) for score, _ in top]
        _, chosen = random.choices(top, weights=weights, k=1)[0]
        self._remember(chat_id, chosen["path"], now)
        logger.info("选择梗图: %s (%s)", Path(chosen["path"]).name, chosen.get("caption", ""))
        return chosen["path"]
