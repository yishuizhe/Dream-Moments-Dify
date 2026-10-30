"""Ebbinghaus-style memory strength for the local chat memory store.

A stored memory keeps a stability ``S`` (in days). Its retrievability decays as
``R = exp(-age / S)``. Every recall reinforces the memory (spacing effect) by
growing ``S`` and resetting the age, which makes frequently used facts stick
while one-off small talk fades away.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Iterable

PERSONAL_MARKERS = (
    "我", "我的", "我叫", "我是", "住", "喜欢", "讨厌", "生日", "工作",
    "上班", "学校", "专业", "家", "猫", "狗", "游戏", "计划", "梦想",
    "老婆", "老公", "女朋友", "男朋友", "孩子", "妈妈", "爸爸",
)

EMOTION_MARKERS = ("！", "!", "呜呜", "哈哈", "好开心", "难过", "生气", "怕")


def _now() -> datetime:
    return datetime.now()


def parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def initial_importance(text: str) -> float:
    """A small, deterministic importance prior from the sentence itself."""

    value = str(text or "")
    importance = 0.45
    if any(marker in value for marker in PERSONAL_MARKERS):
        importance += 0.15
    if len(value) >= 40:
        importance += 0.12
    if any(marker in value for marker in EMOTION_MARKERS):
        importance += 0.08
    if re.search(r"\d{2,}|[一二三四五六七八九十]{2,}", value):
        importance += 0.06
    return round(min(1.0, max(0.2, importance)), 3)


def new_entry(text: str, now: datetime | None = None, *, stability: float = 1.0) -> dict:
    stamp = (now or _now()).isoformat(timespec="seconds")
    return {
        "text": str(text or "")[:300],
        "created_at": stamp,
        "last_seen": stamp,
        "hits": 1,
        "stability": max(0.5, float(stability)),
        "importance": initial_importance(text),
    }


def normalize_entry(raw: Any) -> dict | None:
    """Accept legacy plain strings as well as structured entries."""

    if isinstance(raw, str):
        text = raw.strip()
        return new_entry(text) if text else None
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or "").strip()
    if not text:
        return None
    created = parse_time(raw.get("created_at")) or _now()
    last_seen = parse_time(raw.get("last_seen")) or created
    try:
        hits = max(1, int(raw.get("hits") or 1))
    except (TypeError, ValueError):
        hits = 1
    try:
        stability = max(0.5, float(raw.get("stability") or 1.0))
    except (TypeError, ValueError):
        stability = 1.0
    try:
        importance = min(1.0, max(0.05, float(raw.get("importance") or 0.45)))
    except (TypeError, ValueError):
        importance = 0.45
    return {
        "text": text[:300],
        "created_at": created.isoformat(timespec="seconds"),
        "last_seen": last_seen.isoformat(timespec="seconds"),
        "hits": hits,
        "stability": stability,
        "importance": importance,
    }


def retention(entry: dict, now: datetime | None = None, *, half_life_days: float = 14.0) -> float:
    """``exp(-age/S)`` where ``S`` scales with repetition and importance."""

    current = now or _now()
    last_seen = parse_time(entry.get("last_seen")) or current
    age_days = max(0.0, (current - last_seen).total_seconds() / 86400.0)
    stability = float(entry.get("stability") or 1.0)
    stability *= max(0.5, float(half_life_days)) / 14.0
    stability *= 1.0 + 0.65 * max(0, int(entry.get("hits") or 1) - 1)
    stability *= 0.7 + 0.6 * float(entry.get("importance") or 0.45)
    return math.exp(-age_days / max(0.25, stability))


def score(entry: dict, now: datetime | None = None, *, half_life_days: float = 14.0) -> float:
    importance = float(entry.get("importance") or 0.45)
    return importance * retention(entry, now, half_life_days=half_life_days)


def reinforce(entry: dict, now: datetime | None = None) -> dict:
    current = now or _now()
    entry["hits"] = max(1, int(entry.get("hits") or 1)) + 1
    # Growth is fast for important memories and slower for trivia.
    growth = 1.25 + 0.35 * float(entry.get("importance") or 0.45)
    entry["stability"] = min(180.0, float(entry.get("stability") or 1.0) * growth)
    entry["last_seen"] = current.isoformat(timespec="seconds")
    return entry


def rank(
    entries: Iterable[dict],
    now: datetime | None = None,
    *,
    half_life_days: float = 14.0,
    min_strength: float = 0.12,
    limit: int = 8,
) -> list[dict]:
    """Return the strongest memories, dropping fully faded trivia."""

    current = now or _now()
    scored = []
    for entry in entries:
        value = score(entry, current, half_life_days=half_life_days)
        if value < min_strength:
            continue
        scored.append((value, entry))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in scored[: max(1, int(limit))]]


def prune(
    entries: list[dict],
    now: datetime | None = None,
    *,
    half_life_days: float = 14.0,
    min_strength: float = 0.12,
    max_items: int = 40,
) -> list[dict]:
    current = now or _now()
    kept = [entry for entry in entries if score(entry, current, half_life_days=half_life_days) >= min_strength]
    if len(kept) > max_items:
        kept.sort(key=lambda entry: score(entry, current, half_life_days=half_life_days), reverse=True)
        kept = kept[:max_items]
    kept.sort(key=lambda entry: entry.get("last_seen") or "")
    return kept
