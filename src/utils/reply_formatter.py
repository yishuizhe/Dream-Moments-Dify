"""AI 回复格式化：补齐基本标点并拆分过长微信气泡。"""

from __future__ import annotations

import re


FORMAT_MARKER = "## 回复格式硬性要求（优先级最高）"
FORMAT_INSTRUCTION = f"""

{FORMAT_MARKER}
- 使用正常的中英文标点，不要输出整段没有标点的长句。
- 日常聊天优先使用简短、自然的句子；问句使用问号，陈述句使用句号或合适的逗号。
- 不要使用反斜杠作为分段符，程序会自动处理微信气泡分段。
- 除非用户要求详细说明，单次日常回复尽量控制在 2 到 4 个自然句。
""".strip("\n")

_SENTENCE_END = "。！？!?；;"
_CLAUSE_END = "，,：:、"
_QUESTION_HINT = re.compile(
    r"(?:吗|呢|呀|么|几点|几时|什么时候|怎么|为什么|是否|能否|可否|还是|要不要|有没有|哪)"
)
_TRANSITION_RE = re.compile(
    r"(?<=[\u4e00-\u9fff])(?=(?:那现在|不过说起来|不过|但是|对了|另外|然后|所以|我帮你))"
)
_TRANSITION_PREFIX_RE = re.compile(
    r"^(不过说起来|不过|但是|对了|另外|然后|所以)(?![，,])"
)


def build_system_prompt(system_prompt: str) -> str:
    """把统一回复格式约束追加到角色提示词末尾。"""

    prompt = str(system_prompt or "").strip()
    if FORMAT_MARKER in prompt:
        return prompt
    return f"{prompt}\n\n{FORMAT_INSTRUCTION}" if prompt else FORMAT_INSTRUCTION


def normalize_reply_text(reply: str) -> str:
    """清理思考标记、旧反斜杠分隔符，并修复明显无标点长句。"""

    text = str(reply or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if "</think>" in text:
        text = text.split("</think>", 1)[1].strip()
    if not text:
        return ""

    # 兼容旧角色提示词中的 \ 或 \\ 气泡分隔符，但避免破坏 Windows 路径和代码。
    if "```" not in text:
        text = re.sub(r"(?<![A-Za-z0-9_:/])\\+(?![A-Za-z0-9_])", "\n", text)

    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    if _should_repair_unpunctuated_chinese(text):
        text = _repair_unpunctuated_chinese(text)

    return text.strip()


def split_reply_bubbles(reply: str, max_chars: int = 42) -> list[str]:
    """按换行和标点拆分回复，避免单个微信气泡过长。"""

    text = str(reply or "").strip()
    if not text:
        return []
    if "```" in text:
        return [text]
    limit = max(int(max_chars), 16)
    bubbles: list[str] = []
    for paragraph in (part.strip() for part in text.split("\n")):
        if not paragraph:
            continue
        if "http://" in paragraph or "https://" in paragraph or re.search(r"[A-Za-z]:\\", paragraph):
            bubbles.append(paragraph)
            continue
        sentence_parts = re.findall(rf".+?(?:[{re.escape(_SENTENCE_END)}]+|$)", paragraph)
        current = ""
        for sentence in (part.strip() for part in sentence_parts if part.strip()):
            if len(current) + len(sentence) <= limit:
                current += sentence
                continue
            if current:
                bubbles.append(current)
                current = ""
            long_parts = _split_long_piece(sentence, limit)
            if len(long_parts) > 1:
                bubbles.extend(long_parts[:-1])
                current = long_parts[-1]
            else:
                current = sentence
        if current:
            bubbles.append(current)
    return bubbles


def _should_repair_unpunctuated_chinese(text: str) -> bool:
    if len(text) < 24 or "```" in text or "http://" in text or "https://" in text:
        return False
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return False
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", compact))
    if cjk_count < 12 or cjk_count / len(compact) < 0.6:
        return False
    punctuation_count = sum(char in (_SENTENCE_END + _CLAUSE_END + "\n") for char in text)
    return punctuation_count <= 1


def _repair_unpunctuated_chinese(text: str) -> str:
    # 模型有时会用中文字符之间的空格代替句子边界。
    repaired = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "\n", text)
    repaired = _TRANSITION_RE.sub("\n", repaired)
    segments: list[str] = []
    pending_transition = ""
    for raw_segment in repaired.split("\n"):
        segment = re.sub(r"\s+", " ", raw_segment).strip()
        if not segment:
            continue
        if _TRANSITION_PREFIX_RE.fullmatch(segment):
            pending_transition = f"{segment}，"
            continue
        segment = _TRANSITION_PREFIX_RE.sub(r"\1，", segment)
        if pending_transition:
            segment = pending_transition + segment
            pending_transition = ""
        if segment[-1] not in (_SENTENCE_END + _CLAUSE_END):
            segment += "？" if _QUESTION_HINT.search(segment) else "。"
        segments.append(segment)
    if pending_transition:
        segments.append(pending_transition.rstrip("，") + "。")
    return "\n".join(segments)


def _split_long_piece(text: str, limit: int) -> list[str]:
    parts: list[str] = []
    remaining = text.strip()
    break_chars = set(_SENTENCE_END + _CLAUSE_END + " ")
    while len(remaining) > limit:
        window = remaining[:limit]
        candidates = [index + 1 for index, char in enumerate(window) if char in break_chars]
        cut = candidates[-1] if candidates and candidates[-1] >= limit // 2 else limit
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        parts.append(remaining)
    return parts
