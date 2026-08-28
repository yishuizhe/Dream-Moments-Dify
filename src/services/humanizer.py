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
    """Remove robotic markers while preserving light, characterful warmth."""
    value = re.sub(r"^(好的[，,。.]?\s*)", "", str(reply or "").strip())
    value = re.sub(r"作为AI[，,。:：]?", "", value, flags=re.I)
    value = re.sub(r"\s*(综上所述|总的来说)[，,：:]?\s*", "", value)
    # A single playful opening or wave can sound human; only collapse excess.
    value = re.sub(r"([~～])\1+", r"\1", value)
    value = re.sub(r"([!！?？])\1{2,}", r"\1\1", value)
    value = re.sub(r"[ \t]{2,}", " ", value).strip()
    return value


def warm_short_reply(reply: str, user_text: str, sender_name: str = "") -> str:
    """Warm up only unmistakably cold acknowledgements and greetings."""
    value = str(reply or "").strip()
    incoming = re.sub(r"[@＠\s\u2005]+", "", str(user_text or "")).lower()
    incoming = incoming.replace("娜娜", "")
    compact_reply = re.sub(r"[\s，,。.!！?？~～]+", "", value)
    familiar = "易师傅" if str(sender_name or "").strip() == "易水哲" else ""

    if re.fullmatch(r"(?:在吗|在么|在不在|人呢|在哪)", incoming):
        if compact_reply in {"在", "在呢", "嗯在呢", "我在", "在的"}:
            if familiar:
                return random.choice((
                    "在呀，易师傅一叫我就冒泡啦～",
                    "在呢，怎么突然来点我名呀？",
                ))
            return random.choice(("在呀，怎么突然来点我名啦～", "在呢，你说嘛。"))

    if re.fullmatch(r"(?:你好|嗨|早上好|早安|晚上好|晚安)", incoming):
        if len(compact_reply) <= 6:
            return random.choice(("你好呀，今天也来找我啦～", "我在呢，今天过得怎么样呀？"))
    return value


def sleep_before_reply(text: str) -> None:
    delay = thinking_delay(text)
    if delay > 0:
        threading.Event().wait(delay)
