"""Helpers for downloading WeChat images and running vision recognition safely."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

IMAGE_PLACEHOLDERS = {
    "图片",
    "[图片]",
    "[image]",
    "image",
    "[Image]",
    "photo",
    "[Photo]",
    "[图片消息]",
}

RECOGNITION_FAIL_MARKERS = (
    "抱歉",
    "失败",
    "不存在",
    "不可用",
    "无法",
    "错误",
    "超时",
    "没能",
    "无效",
    "未配置",
    "IMAGE_RECOGNITION_FAILED",
)


def is_image_placeholder(content: str | None) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    lower = text.lower()
    if lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
        return True
    if text in IMAGE_PLACEHOLDERS or lower in IMAGE_PLACEHOLDERS:
        return True
    compact = re.sub(r"[\s\[\]【】]", "", text).lower()
    return compact in {"图片", "image", "photo", "img"}


def is_image_message(msg: Any, content: str | None = None) -> bool:
    if is_image_placeholder(content):
        return True
    raw = getattr(msg, "raw", None)
    if raw is None:
        raw = msg
    type_name = type(raw).__name__.lower()
    if "image" in type_name:
        return True
    kind = str(getattr(raw, "type", "") or getattr(msg, "message_type", "") or "").lower()
    if "image" in kind or kind in {"图片", "[图片]"}:
        return True
    return False


def _coerce_path(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, (list, tuple)):
        for item in value:
            path = _coerce_path(item)
            if path:
                return path
        return None
    if isinstance(value, dict):
        for key in ("path", "file", "filepath", "file_path", "save_path", "data"):
            if key in value:
                path = _coerce_path(value.get(key))
                if path:
                    return path
        return None
    text = str(value).strip()
    if not text:
        return None
    # WxResponse-like objects sometimes stringify as success message, not path.
    if os.path.exists(text) and os.path.isfile(text):
        return os.path.abspath(text)
    if text.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
        candidate = os.path.abspath(text)
        if os.path.exists(candidate):
            return candidate
    return None


def download_wechat_image(msg: Any, save_dir: str | Path) -> Optional[str]:
    """Try wxauto4 ImageMessage.download / related save helpers."""
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    raw = getattr(msg, "raw", None)
    if raw is None:
        raw = msg

    # 1) direct download on message object
    for obj in (raw, msg):
        downloader = getattr(obj, "download", None)
        if not callable(downloader):
            continue
        try:
            result = downloader()
            path = _coerce_path(result)
            if path:
                logger.info("Downloaded WeChat image via message.download: %s", path)
                return path
            # Some builds return WeChatImage-like object with save()
            saver = getattr(result, "save", None)
            if callable(saver):
                target = save_dir / f"wx_image_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
                try:
                    saved = saver(str(target))
                except TypeError:
                    saved = saver(dir_path=str(save_dir))
                path = _coerce_path(saved) or (str(target) if target.exists() else None)
                if path:
                    logger.info("Saved WeChat image via download().save: %s", path)
                    return path
        except Exception as exc:
            logger.warning("message.download failed: %s", type(exc).__name__)

    # 2) common alternate method names
    for obj in (raw, msg):
        for name in ("SaveImages", "save", "save_image", "download_image"):
            fn = getattr(obj, name, None)
            if not callable(fn):
                continue
            try:
                target = save_dir / f"wx_image_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
                try:
                    result = fn(str(target))
                except TypeError:
                    try:
                        result = fn(dir_path=str(save_dir))
                    except TypeError:
                        result = fn()
                path = _coerce_path(result) or (str(target) if target.exists() else None)
                if path:
                    logger.info("Saved WeChat image via %s: %s", name, path)
                    return path
            except Exception as exc:
                logger.warning("%s failed: %s", name, type(exc).__name__)
    return None


def recognition_failed(text: str | None) -> bool:
    value = str(text or "")
    if not value:
        # A bare @娜娜 is cleaned to an empty message before reply generation.
        # It is not an image-recognition failure.
        return False
    if "发送了图片：" not in value and "发送了表情包：" not in value and "IMAGE_RECOGNITION_FAILED" not in value:
        return False
    return any(marker in value for marker in RECOGNITION_FAIL_MARKERS)


def honest_image_failure_reply(detail: str = "") -> str:
    """Return a helpful reply without exposing configuration details to chat."""

    return "这张图这次没读出来，我先不乱猜。你可以再发一次，或者告诉我想看哪一部分。"
