"""Bundled group chat summary / member evaluation plugin for Dream-Moments."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


class DreamChatSummaryPlugin:
    name = "ChatSummary"
    version = "2.2.0"

    KIND_GROUP = "group"
    KIND_TODAY = "today"
    KIND_MEMBER = "member"
    KIND_DAYS = "days"

    def __init__(self, plugin_dir: str | Path, logger: logging.Logger | None = None) -> None:
        self.plugin_dir = Path(plugin_dir).resolve()
        self.logger = logger or logging.getLogger(__name__)
        self.history_store = None
        self.ai_responder: Callable[[str, str], str] | None = None

    def configure_services(self, *, history_store=None, ai_responder=None, **_: Any) -> None:
        self.history_store = history_store
        self.ai_responder = ai_responder if callable(ai_responder) else None

    def handle_message(self, message: dict[str, Any]) -> str | None:
        if not message.get("is_group") or message.get("is_self"):
            return None

        parsed = self._parse_command(
            str(message.get("content") or ""),
            str(message.get("bot_name") or ""),
        )
        if parsed is None:
            return None

        kind = str(parsed.get("kind") or self.KIND_GROUP)
        limit = int(parsed.get("limit") or 100)
        member_name = str(parsed.get("member_name") or "").strip()
        days = int(parsed.get("days") or 0)

        if self.history_store is None or self.ai_responder is None:
            return "聊天总结服务尚未完成初始化。"

        chat_id = str(message.get("chat_id") or "")
        since = None
        if kind == self.KIND_TODAY:
            now = datetime.now()
            since = datetime(now.year, now.month, now.day)
        elif kind == self.KIND_DAYS:
            days = max(1, min(days or 3, 30))
            since = datetime.now() - timedelta(days=days)
            limit = max(limit, min(days * 80, 400))

        rows = self._load_rows(
            chat_id=chat_id,
            limit=limit,
            member_name=member_name if kind == self.KIND_MEMBER else "",
            since=since,
        )
        rows = [
            row
            for row in rows
            if not self._is_summary_command(str(row.get("content") or ""), str(message.get("bot_name") or ""))
        ]
        rows = rows[-limit:]

        if not rows:
            if kind == self.KIND_MEMBER and member_name:
                return f"近期没有找到「{member_name}」的可总结发言。可用群昵称再试一次。"
            if kind == self.KIND_TODAY:
                return "今天暂时还没有足够的群聊记录可供总结。"
            return "近期还没有足够的群聊记录可供总结。"

        transcript = self._format_transcript(rows)
        prompt = self._build_prompt(kind=kind, limit=limit, member_name=member_name, transcript=transcript, days=days)

        try:
            reply = str(self.ai_responder(prompt, chat_id) or "").strip()
            reply = self._prettify_summary(reply)
            if not reply:
                return "总结生成失败，请稍后再试。"
            self._save_summary_record(
                chat_id=chat_id,
                kind=kind,
                limit=limit,
                days=days,
                member_name=member_name,
                reply=reply,
            )
            return reply
        except Exception as exc:
            self.logger.error("ChatSummary failed (%s)", type(exc).__name__)
            return "总结生成失败，请稍后再试。"

    def _load_rows(
        self,
        *,
        chat_id: str,
        limit: int,
        member_name: str = "",
        since: datetime | None = None,
    ) -> list[dict]:
        store = self.history_store
        if hasattr(store, "get_messages_for_summary"):
            return store.get_messages_for_summary(
                chat_id,
                min(limit + 20, 120),
                member_name=member_name or "",
                since=since,
                exclude_assistant=False,
            )

        rows = store.get_recent_messages(chat_id, min(max(limit * 3, 80), 120))
        if since is not None:
            filtered = []
            for row in rows:
                created = row.get("created_at")
                if isinstance(created, datetime) and created >= since:
                    filtered.append(row)
            rows = filtered
        if member_name:
            target = self._normalize_name(member_name)
            rows = [
                row
                for row in rows
                if self._name_matches(
                    target,
                    str(row.get("sender_name") or ""),
                    str(row.get("sender_id") or ""),
                )
                and str(row.get("role") or "") != "assistant"
            ]
        return rows

    @staticmethod
    def _format_transcript(rows: list[dict]) -> str:
        lines: list[str] = []
        for row in rows:
            created_at = row.get("created_at")
            time_text = created_at.strftime("%m-%d %H:%M") if isinstance(created_at, datetime) else ""
            role = str(row.get("role") or "user")
            if role == "assistant":
                name = "娜娜"
            else:
                name = str(row.get("sender_name") or row.get("sender_id") or "未知成员")
            content = " ".join(str(row.get("content") or "").split())
            if not content:
                continue
            lines.append(f"[{time_text}] {name}：{content}")
        return "\n".join(lines)

    def _build_prompt(self, *, kind: str, limit: int, member_name: str, transcript: str, days: int = 0) -> str:
        common = (
            "排版硬性要求：\n"
            "1. 必须使用【小标题】分段，每个小标题单独成行。\n"
            "2. 每个小标题下最多 2 句，单句尽量不超过 28 个中文。\n"
            "3. 不要写成一大段，不要用 1.2.3. 堆在同一段。\n"
            "4. 不要客套开场，不要结尾祝福，不要提自己是 AI。\n"
            "5. 只根据记录，客观真实，不讨好，不编造。\n"
        )
        if kind == self.KIND_MEMBER:
            return (
                f"请对群成员「{member_name}」做客观锐评，依据其近 {limit} 条发言。\n"
                f"{common}"
                "请严格按这个模板输出：\n"
                "【一句话印象】\n……\n"
                "【说话风格】\n……\n"
                "【优点】\n……\n"
                "【槽点】\n……\n"
                "【总评】\n……\n\n"
                f"发言记录：\n{transcript}"
            )
        if kind == self.KIND_TODAY:
            return (
                "请总结本群今天的聊天。\n"
                f"{common}"
                "请严格按这个模板输出：\n"
                "【今日概览】\n……\n"
                "【主要话题】\n……\n"
                "【活跃的人】\n……\n"
                "【有意思的点】\n……\n"
                "【争议/待办】\n……（没有就写：无）\n\n"
                f"聊天记录：\n{transcript}"
            )
        if kind == self.KIND_DAYS:
            return (
                f"请总结本群最近 {days or 3} 天的聊天（约 {limit} 条本地记录）。\n"
                f"{common}"
                "请严格按这个模板输出：\n"
                "【时间范围概览】\n……\n"
                "【主要话题】\n……\n"
                "【活跃的人】\n……\n"
                "【关键摘要】\n……\n"
                "【结论】\n……（没有就写：无）\n\n"
                f"聊天记录：\n{transcript}"
            )
        return (
            f"请总结本群最近约 {limit} 条聊天。这些记录来自本地历史，不限当天。\n"
            f"{common}"
            "请严格按这个模板输出：\n"
            "【整体氛围】\n……\n"
            "【主要话题】\n……\n"
            "【关键摘要】\n……\n"
            "【结论】\n……（没有就写：无）\n\n"
            f"聊天记录：\n{transcript}"
        )

    @staticmethod
    def _prettify_summary(text: str) -> str:
        raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not raw:
            return ""
        if "</think>" in raw:
            raw = raw.split("</think>", 1)[1].strip()
        raw = re.sub(r"\s*(【[^】]{1,20}】)\s*", r"\n\1\n", raw)
        raw = re.sub(r"(?m)^\s*[-*•]\s*", "", raw)
        raw = re.sub(r"(?m)^\s*\d+[\.、]\s*", "", raw)
        lines = []
        for line in raw.split("\n"):
            s = " ".join(line.split()).strip()
            if s:
                lines.append(s)
        cleaned = []
        for line in lines:
            if cleaned and cleaned[-1] == line:
                continue
            cleaned.append(line)
        return "\n".join(cleaned).strip()

    @classmethod
    def _parse_command(cls, content: str, bot_name: str = "") -> dict[str, Any] | None:
        text = cls._normalize_command_text(content, bot_name)
        if not text:
            return None

        if re.fullmatch(
            r"(?:请)?(?:帮我|帮忙)?(?:总结|复盘|回顾)(?:一下)?(?:今日|今天)(?:的)?(?:群聊|聊天|记录|内容)?|"
            r"(?:今日|今天)(?:群聊|聊天)?(?:总结|复盘|回顾)",
            text,
        ):
            return {"kind": cls.KIND_TODAY, "limit": 120, "member_name": "", "days": 0}

        days_match = re.fullmatch(
            r"(?:请)?(?:帮我|帮忙)?(?:总结|复盘|回顾)(?:一下)?"
            r"(?:群聊|本群|这个群|聊天|聊天记录|记录)?"
            r"(?:最近|近)?(?P<d>\d{1,2})\s*天(?:的)?(?:群聊|聊天|记录|内容)?",
            text,
        )
        if days_match:
            d = int(days_match.group("d") or 3)
            d = max(1, min(d, 30))
            return {"kind": cls.KIND_DAYS, "limit": min(d * 80, 400), "member_name": "", "days": d}

        group = re.fullmatch(
            r"(?:请)?(?:帮我|帮忙)?(?:总结|复盘|回顾)(?:一下)?"
            r"(?:群聊|本群|这个群|聊天|聊天记录|记录)?"
            r"(?:最近|近)?(?:(?P<n>\d{1,3})\s*条)?",
            text,
        )
        if group:
            remainder = text
            remainder = re.sub(
                r"^(?:请)?(?:帮我|帮忙)?(?:总结|复盘|回顾)(?:一下)?",
                "",
                remainder,
            ).strip()
            remainder = re.sub(r"^(?:群聊|本群|这个群|聊天|聊天记录|记录)", "", remainder).strip()
            remainder = re.sub(r"^(?:最近|近)", "", remainder).strip()
            remainder = re.sub(r"^\d{1,3}\s*条$", "", remainder).strip()
            if remainder == "":
                n = group.group("n")
                limit = int(n) if n else 100
                limit = max(10, min(limit, 300))
                return {"kind": cls.KIND_GROUP, "limit": limit, "member_name": "", "days": 0}

        member = re.fullmatch(
            r"(?:请)?(?:帮我|帮忙)?(?:总结|评价|锐评|点评|客观评价|真实评价)"
            r"(?:一下)?(?:群成员|成员|群友)?"
            r"(?:[@＠](?P<at_name>[^@\s]+)|(?P<name>[^\d@＠].*?))"
            r"(?:的)?(?:发言|聊天|聊天记录|记录)?"
            r"(?:\s*(?:最近|近)?(?P<n>\d{1,3})\s*条)?",
            text,
        )
        if member:
            name = cls._clean_member_name(member.group("at_name") or member.group("name") or "")
            if name and not cls._looks_like_group_scope(name) and not name.isdigit():
                n = member.group("n")
                limit = int(n) if n else 50
                limit = max(10, min(limit, 300))
                return {"kind": cls.KIND_MEMBER, "limit": limit, "member_name": name, "days": 0}

        return None

    @classmethod
    def _normalize_command_text(cls, content: str, bot_name: str = "") -> str:
        text = str(content or "")
        text = text.replace("\u200b", "").replace("\ufeff", "")
        text = " ".join(text.strip().split())
        if not text:
            return ""
        names = [str(bot_name or "").strip(), "娜娜", "nana", "NANA"]
        for name in names:
            if not name:
                continue
            text = re.sub(rf"^[@＠]?{re.escape(name)}[\s,，:：]+", "", text).strip()
            text = re.sub(rf"^[@＠]?{re.escape(name)}(?=(?:总结|评价|锐评|点评|复盘|回顾))", "", text).strip()
            text = re.sub(rf"[@＠]{re.escape(name)}", "", text).strip()
        text = text.replace("＠", "@")
        text = re.sub(r"\s+", " ", text).strip(" 。.!！?？")
        return text

    @classmethod
    def _clean_member_name(cls, value: str) -> str:
        name = str(value or "").strip().lstrip("@＠").strip()
        name = re.sub(r"^(?:一下|下)", "", name).strip()
        name = re.sub(r"(?:最近|近)?\d{1,3}\s*条$", "", name).strip()
        name = re.sub(r"(?:的)?(?:发言|聊天记录|聊天|记录)$", "", name).strip()
        return name.strip(" ，,。.!！?？:：")

    @staticmethod
    def _looks_like_group_scope(name: str) -> bool:
        text = str(name or "").strip()
        if not text or text.isdigit():
            return True
        if re.fullmatch(r"(?:最近|近)?\d{1,3}条", text):
            return True
        if re.fullmatch(r"(?:最近|近)?\d{1,2}天(?:的)?(?:群聊|聊天|记录|内容)?", text):
            return True
        return text in {
            "群聊", "本群", "这个群", "聊天", "聊天记录", "记录",
            "最近", "近", "今日", "今天", "今日群聊", "今天群聊", "一下",
        }

    @classmethod
    def _is_summary_command(cls, content: str, bot_name: str = "") -> bool:
        return cls._parse_command(content, bot_name) is not None

    @staticmethod
    def _normalize_name(value: str) -> str:
        text = str(value or "").strip().lstrip("@＠")
        for ch in (" ", "\t", "\u3000", ":", "：", ",", "，"):
            text = text.replace(ch, "")
        return text.lower()

    @classmethod
    def _name_matches(cls, target: str, sender_name: str, sender_id: str = "") -> bool:
        if not target:
            return True
        for item in (sender_name, sender_id):
            norm = cls._normalize_name(item)
            if not norm:
                continue
            if norm == target or target in norm or norm in target:
                return True
        return False




    def _save_summary_record(
        self,
        *,
        chat_id: str,
        kind: str,
        limit: int,
        days: int,
        member_name: str,
        reply: str,
    ) -> None:
        """Persist summary results under data/summaries for later review."""
        try:
            project_root = self.plugin_dir.parent.parent
            safe_chat = re.sub(r'[\\/:*?"<>|]', '_', str(chat_id or 'unknown'))
            out_dir = project_root / 'data' / 'summaries' / safe_chat
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            meta = f'kind={kind}; limit={limit}; days={days}; member={member_name or "-"}'
            path_out = out_dir / f'{stamp}_{kind}.md'
            path_out.write_text('# Chat Summary\n\n' + meta + '\n\n' + reply + '\n', encoding='utf-8')
            self.logger.info('Saved chat summary to %s', path_out)
        except Exception as exc:
            self.logger.warning('Failed to save summary record: %s', type(exc).__name__)


def create_plugin(plugin_dir: str | Path, logger: logging.Logger | None = None) -> DreamChatSummaryPlugin:
    return DreamChatSummaryPlugin(plugin_dir=plugin_dir, logger=logger)
