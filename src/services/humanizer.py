"""Small, deterministic controls that make replies feel less automated."""

from __future__ import annotations

import os
import random
import re
import threading


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def should_reply(text: str, *, is_group: bool, forced: bool = False) -> bool:
    """Only explicit group triggers may reach the AI.

    The runtime now performs trigger recognition before invoking this helper.
    Keeping the policy here deterministic prevents future callers from
    reintroducing random group participation.
    """
    if forced:
        return True
    if not is_group:
        return True
    return False


def thinking_delay(text: str) -> float:
    """Return a small variable delay without blocking for an excessive time."""
    base = _env_float("DREAM_REPLY_DELAY_BASE", 0.8)
    per_char = _env_float("DREAM_REPLY_DELAY_PER_CHAR", 0.025)
    upper = _env_float("DREAM_REPLY_DELAY_MAX", 5.0)
    return max(0.0, min(upper, base + len(str(text or "")) * per_char + random.uniform(0.0, 0.9)))


def humanize_text(reply: str) -> str:
    """Remove common synthetic-chat markers without inventing a new persona."""
    value = re.sub(r"^(好的[，,。.]?\s*)", "", str(reply or "").strip())
    value = re.sub(r"作为AI[，,。:：]?", "", value, flags=re.I)
    value = re.sub(r"\s*(综上所述|总的来说)[，,：:]?\s*", "", value)
    value = re.sub(r"^(?:诶嘿|诶|哇|咦|嗯呢|哈哈)[，,、。！？!?~～\s]*", "", value)
    value = re.sub(
        r"^(?:被你(?:看出来|发现)啦|好有氛围|太厉害了|好棒|太棒了|真棒)"
        r"[，,、。！？!?~～\s]*",
        "",
        value,
    )
    value = value.replace("～", "")
    value = re.sub(r"([。！？!?])(?:[~～]+)", r"\1", value)
    value = re.sub(r"[ \t]{2,}", " ", value).strip()
    return value


def sleep_before_reply(text: str) -> None:
    delay = thinking_delay(text)
    if delay > 0:
        threading.Event().wait(delay)
