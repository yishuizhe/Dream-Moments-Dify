"""Identify non-conversation events before trusting their sender metadata."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET


def strip_transport_prefix(content: str) -> str:
    # Rendering only: the authenticated sender ID remains unchanged.
    return re.sub(r"^(?:wxid_[A-Za-z0-9_]+|[A-Za-z]\d{5,20}):\s*\n", "", str(content or ""))


def _xml_root(content: str):
    value = str(content or "").strip()
    # Legacy WeChat accounts may use an ordinary account name rather than wxid.
    # Strip transport framing only; this function never changes sender identity.
    value = re.sub(r"^[A-Za-z][A-Za-z0-9_-]{5,63}:\s*\n(?=<|<\?xml)", "", value)
    if not value.startswith("<") or len(value) > 131072 or "<!DOCTYPE" in value.upper():
        return None
    try:
        return ET.fromstring(value)
    except (ET.ParseError, ValueError):
        return None


def quote_metadata(content: str) -> dict:
    root = _xml_root(content)
    if root is None:
        return {}
    app = root if root.tag == "appmsg" else root.find("appmsg")
    if app is None or app.findtext("type") != "57":
        return {}
    ref = app.find("refermsg")
    return {"reply": app.findtext("title") or "",
            "sender": ref.findtext("displayname") or "" if ref is not None else "",
            "sender_id": ref.findtext("chatusr") or "" if ref is not None else "",
            "content": ref.findtext("content") or "" if ref is not None else ""}


def conversation_text(content: str) -> str:
    """Render transport XML as chat data without pretending to see media."""
    if is_poke_notice(content):
        return ""
    quote = quote_metadata(content)
    if quote:
        return f"{quote['reply']}（引用{quote['sender'] or '群友'}：{quote['content'][:300]}）"
    root = _xml_root(content)
    if root is None:
        return strip_transport_prefix(str(content or "")).strip()
    for tag, description in (("img", "[图片，未识别内容]"),
                             ("emoji", "[表情包，未识别内容]"),
                             ("voicemsg", "[语音，未转写]")):
        if root.find(tag) is not None:
            return description
    app = root if root.tag == "appmsg" else root.find("appmsg")
    if app is not None:
        title = app.findtext("title") or ""
        return f"[分享内容] {title}".strip()
    return "[系统或媒体消息，未解读内容]"


def is_poke_notice(content: str) -> bool:
    """WeChat encodes 拍一拍 as appmsg type 62, not always as system/notice.

    Sender indexes on these rows may point at unrelated contacts. Only the
    structured event type identifies them; a human discussing 拍一拍 stays text.
    """
    value = str(content or "").strip()
    if re.fullmatch(r'[“"].+?[”"]\s*拍了拍\s*[“"].+?[”"](?:\s*.*)?', value):
        return True
    if not value.startswith("<") and ":\n" in value:
        value = value.split(":\n", 1)[1].lstrip()
    if not value.startswith("<") or len(value) > 131072 or "<!DOCTYPE" in value.upper():
        return False
    try:
        root = ET.fromstring(value)
    except (ET.ParseError, ValueError):
        return False
    if root.tag == "sysmsg" and str(root.get("type") or "").lower() in {"pat", "poke"}:
        return True
    app = root if root.tag == "appmsg" else root.find("appmsg")
    return app is not None and str(app.findtext("type") or "").strip() == "62"
