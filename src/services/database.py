"""Local SQLite persistence for chat history and per-member memory."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from services import memory_curve
from wechat.message_types import conversation_text

Base = declarative_base()
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db_path = os.path.join(project_root, "data", "database", "chat_history.db")
os.makedirs(os.path.dirname(db_path), exist_ok=True)
engine = create_engine(
    f"sqlite:///{db_path}",
    connect_args={"check_same_thread": False},
)
Session = sessionmaker(bind=engine)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    sender_id = Column(String(100))
    sender_name = Column(String(100))
    message = Column(Text)
    reply = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True)
    chat_id = Column(String(255), nullable=False, index=True)
    sender_id = Column(String(255), nullable=False, default="")
    sender_name = Column(String(255), nullable=False, default="")
    role = Column(String(20), nullable=False, default="user")
    content = Column(Text, nullable=False, default="")
    is_group = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now, index=True)


class UserMemory(Base):
    __tablename__ = "user_memories"

    id = Column(Integer, primary_key=True)
    identity_key = Column(String(600), nullable=False, unique=True, index=True)
    chat_id = Column(String(255), nullable=False, default="")
    sender_id = Column(String(255), nullable=False, default="")
    sender_name = Column(String(255), nullable=False, default="")
    memory_text = Column(Text, nullable=False, default="[]")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class ChatIdentity(Base):
    """Stable WeChat conversation id with all observed display-name aliases."""

    __tablename__ = "chat_identities"

    id = Column(Integer, primary_key=True)
    stable_id = Column(String(255), nullable=False, unique=True, index=True)
    display_name = Column(String(255), nullable=False, default="")
    aliases_json = Column(Text, nullable=False, default="[]")
    is_group = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class PersonIdentity(Base):
    """One real person across private chats, groups and Moments.

    The WeChat ``wxid`` is the canonical id when it is available. Display
    names, group nicknames and the chats where this person was seen are kept
    as aliases so the model can recognise the same person everywhere.
    """

    __tablename__ = "people"

    person_id = Column(String(255), primary_key=True)
    display_name = Column(String(255), nullable=False, default="")
    aliases_json = Column(Text, nullable=False, default="[]")
    chats_json = Column(Text, nullable=False, default="[]")
    first_seen = Column(DateTime, nullable=False, default=datetime.now)
    last_seen = Column(DateTime, nullable=False, default=datetime.now)


Base.metadata.create_all(engine)


def make_identity_key(chat_id: str, sender_id: str, is_group: bool) -> str:
    stable_sender = str(sender_id or "unknown").strip() or "unknown"
    if is_group:
        return f"group:{chat_id}:member:{stable_sender}"
    return f"private:{stable_sender}"


def resolve_identity(
    chat_id: str,
    sender_id: str,
    sender_name: str,
    is_group: bool,
    identity_aliases: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Return a stable person key when the sender matches a configured alias.

    Alias rules use ``本人=私聊名|群昵称1|群昵称2``; repeated ``=`` is also
    accepted as an alias separator. The explicit mapping is
    intentionally required: matching arbitrary equal display names across groups
    would merge unrelated people.
    """

    observed = {
        _normalize_identity_token(sender_id),
        _normalize_identity_token(sender_name),
    }
    observed.discard("")
    for rule in identity_aliases or []:
        if "=" not in str(rule):
            continue
        canonical, raw_aliases = str(rule).split("=", 1)
        canonical = canonical.strip()
        if not canonical:
            continue
        aliases = [canonical] + re.split(r"[|;=]", raw_aliases)
        normalized_aliases = {
            _normalize_identity_token(value) for value in aliases if value.strip()
        }
        if observed & normalized_aliases:
            display_aliases = [value.strip() for value in aliases if value.strip()]
            return f"person:{canonical}", display_aliases
    return make_identity_key(chat_id, sender_id, is_group), []


def _normalize_identity_token(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def person_key_for(
    sender_id: str,
    sender_name: str = "",
    identity_aliases: list[str] | None = None,
) -> str:
    """Return one stable memory key for a human across all conversations.

    The WeChat ``wxid`` wins whenever it is known; display names are only a
    fallback for the older UI-automation backend. Explicit ``本人=...`` alias
    rules still collapse several display names onto one canonical person.
    """

    stable_id = str(sender_id or "").strip()
    name = str(sender_name or "").strip()
    observed = {_normalize_identity_token(value) for value in (stable_id, name)}
    observed.discard("")
    for rule in identity_aliases or []:
        if "=" not in str(rule):
            continue
        canonical, raw_aliases = str(rule).split("=", 1)
        canonical = canonical.strip()
        if not canonical:
            continue
        aliases = {_normalize_identity_token(value) for value in [canonical, *re.split(r"[|;=]", raw_aliases)] if value.strip()}
        if observed & aliases:
            return f"person:{canonical}"
    if stable_id.startswith("wxid_"):
        return f"person:{stable_id}"
    # Non-wxid ids such as a manually bound contact id still beat a nickname.
    if stable_id and not stable_id.isdigit() and stable_id != name:
        return f"person:{stable_id}"
    return f"person:{stable_id or name or 'unknown'}"


class HistoryStore:
    """Thread-safe-by-session access to history and compact local memories."""

    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or Session

    def register_chat_identity(
        self,
        stable_id: str,
        display_name: str,
        *,
        aliases: list[str] | None = None,
        is_group: bool = False,
    ) -> str:
        """Register a stable chat id and migrate rows stored under old names.

        WeChat group display names are mutable.  The ``@chatroom`` username is
        stable, so all history and per-member memory is consolidated under it.
        """

        stable = str(stable_id or display_name or "").strip()
        current = str(display_name or stable).strip()
        if not stable:
            return current
        observed = {current, *(str(item or "").strip() for item in aliases or [])}
        observed.discard("")
        observed.discard(stable)

        session = self.session_factory()
        try:
            row = session.query(ChatIdentity).filter(ChatIdentity.stable_id == stable).first()
            known: set[str] = set()
            if row is not None:
                try:
                    known = {str(item).strip() for item in json.loads(row.aliases_json or "[]")}
                except (TypeError, ValueError):
                    known = set()
            else:
                row = ChatIdentity(stable_id=stable)
                session.add(row)

            all_aliases = {item for item in known | observed if item and item != stable}
            row.display_name = current
            row.aliases_json = json.dumps(sorted(all_aliases), ensure_ascii=False)
            row.is_group = bool(is_group)

            if all_aliases:
                session.query(ConversationMessage).filter(
                    ConversationMessage.chat_id.in_(all_aliases)
                ).update({ConversationMessage.chat_id: stable}, synchronize_session=False)

                memories = session.query(UserMemory).filter(
                    UserMemory.chat_id.in_(all_aliases)
                ).all()
                for memory in memories:
                    old_chat_id = str(memory.chat_id or "")
                    old_key = str(memory.identity_key or "")
                    new_key = old_key
                    prefix = f"group:{old_chat_id}:member:"
                    if old_key.startswith(prefix):
                        new_key = f"group:{stable}:member:{old_key[len(prefix):]}"
                    duplicate = session.query(UserMemory).filter(
                        UserMemory.identity_key == new_key,
                        UserMemory.id != memory.id,
                    ).first()
                    if duplicate is not None:
                        merged = self._merge_memory_texts(duplicate.memory_text, memory.memory_text)
                        duplicate.memory_text = merged
                        duplicate.chat_id = stable
                        duplicate.updated_at = datetime.now()
                        session.delete(memory)
                    else:
                        memory.chat_id = stable
                        memory.identity_key = new_key
            session.commit()
            return stable
        finally:
            session.close()

    @staticmethod
    def _merge_memory_texts(first: str, second: str) -> str:
        result: list[str] = []
        for raw in (first, second):
            try:
                items = json.loads(raw or "[]")
            except (TypeError, ValueError):
                items = []
            for item in items if isinstance(items, list) else []:
                text = str(item or "").strip()
                if text and text not in result:
                    result.append(text)
        return json.dumps(result[-12:], ensure_ascii=False)

    def get_chat_display_name(self, stable_id: str) -> str:
        session = self.session_factory()
        try:
            row = session.query(ChatIdentity).filter(
                ChatIdentity.stable_id == str(stable_id or "")
            ).first()
            return str(row.display_name or "") if row is not None else ""
        finally:
            session.close()

    def record_message(
        self,
        *,
        chat_id: str,
        sender_id: str,
        sender_name: str,
        role: str,
        content: str,
        is_group: bool,
        created_at: datetime | None = None,
    ) -> None:
        text = str(content or "").strip()
        if not text:
            return
        session = self.session_factory()
        try:
            session.add(
                ConversationMessage(
                    chat_id=str(chat_id or ""),
                    sender_id=str(sender_id or ""),
                    sender_name=str(sender_name or sender_id or ""),
                    role=str(role or "user"),
                    content=text,
                    is_group=bool(is_group),
                    created_at=created_at if isinstance(created_at, datetime) else datetime.now(),
                )
            )
            session.commit()
        finally:
            session.close()

    def get_recent_messages(
        self,
        chat_id: str,
        limit: int,
        *,
        sender_id: str | None = None,
        sender_name: str | None = None,
    ) -> list[dict]:
        safe_limit = max(1, min(int(limit), 120))
        session = self.session_factory()
        try:
            query = session.query(ConversationMessage).filter(
                ConversationMessage.chat_id == str(chat_id or "")
            )
            if sender_id:
                query = query.filter(ConversationMessage.sender_id == str(sender_id))
            elif sender_name:
                query = query.filter(ConversationMessage.sender_name == str(sender_name))
            rows = query.order_by(ConversationMessage.id.desc()).limit(safe_limit).all()
            rows.reverse()
            return [
                {
                    "id": row.id,
                    "chat_id": row.chat_id,
                    "sender_id": row.sender_id,
                    "sender_name": row.sender_name,
                    "role": row.role,
                    "content": row.content,
                    "is_group": bool(row.is_group),
                    "created_at": row.created_at,
                }
                for row in rows
            ]
        finally:
            session.close()



    def get_messages_for_summary(
        self,
        chat_id: str,
        limit: int = 100,
        *,
        member_name: str = "",
        member_id: str = "",
        member_ids: list[str] | None = None,
        since: datetime | None = None,
        exclude_assistant: bool = False,
    ) -> list[dict]:
        """Fetch recent chat rows for summary/eval, with optional member/day filters."""
        safe_limit = max(1, min(int(limit), 500))
        # Over-fetch then filter so nickname matching stays flexible.
        fetch_n = min(1200, max(safe_limit * 4, safe_limit + 40))
        session = self.session_factory()
        try:
            query = session.query(ConversationMessage).filter(
                ConversationMessage.chat_id == str(chat_id or "")
            )
            if since is not None:
                query = query.filter(ConversationMessage.created_at >= since)
            identities = list(member_ids or ([member_id] if member_id else []))
            if identities:
                query = query.filter(
                    ConversationMessage.sender_id.in_(identities),
                    ConversationMessage.role != "assistant",
                )
            rows = query.order_by(ConversationMessage.id.desc()).limit(fetch_n).all()
            rows.reverse()
            target = self._normalize_person_name(member_name)
            result: list[dict] = []
            for row in rows:
                role = str(row.role or "user")
                if exclude_assistant and role == "assistant":
                    continue
                sender_name = str(row.sender_name or "")
                sender_id = str(row.sender_id or "")
                if target and not identities:
                    if not self._person_name_matches(target, sender_name, sender_id):
                        continue
                    if role == "assistant":
                        continue
                result.append(
                    {
                        "id": row.id,
                        "chat_id": row.chat_id,
                        "sender_id": sender_id,
                        "sender_name": sender_name,
                        "role": role,
                        "content": row.content,
                        "is_group": bool(row.is_group),
                        "created_at": row.created_at,
                    }
                )
            return result[-safe_limit:]
        finally:
            session.close()

    @staticmethod
    def _normalize_person_name(value: str) -> str:
        text = str(value or "").strip()
        text = text.lstrip("@＠").strip()
        for ch in (" ", "\t", "\u3000", ":", "：", ",", "，", "。", "!", "！", "?", "？"):
            text = text.replace(ch, "")
        return text.lower()

    def get_summary_members(self, chat_id: str) -> list[dict]:
        """All observed aliases in this chat, without reading message bodies."""
        session = self.session_factory()
        try:
            rows = session.query(
                ConversationMessage.sender_id, ConversationMessage.sender_name,
            ).filter(
                ConversationMessage.chat_id == str(chat_id),
                ConversationMessage.role != "assistant",
            ).distinct().all()
            return [{"username": sender_id, "sender_name": name}
                    for sender_id, name in rows if sender_id]
        finally:
            session.close()

    @classmethod
    def _person_name_matches(cls, target: str, sender_name: str, sender_id: str = "") -> bool:
        if not target:
            return True
        candidates = [
            cls._normalize_person_name(sender_name),
            cls._normalize_person_name(sender_id),
        ]
        for item in candidates:
            if not item:
                continue
            if item == target or target in item or item in target:
                return True
        return False

    def get_recent_group_members(self, chat_id: str, limit: int = 40) -> list[dict]:
        """Return recent human members in a group chat, newest interaction first."""
        rows = self.get_recent_messages(chat_id, max(1, int(limit)))
        members: list[dict] = []
        seen: set[str] = set()
        for row in reversed(rows):
            if str(row.get("role") or "") == "assistant":
                continue
            sender_id = str(row.get("sender_id") or "").strip()
            sender_name = str(row.get("sender_name") or sender_id or "").strip()
            if not sender_name or sender_name.lower() in {"system", "bot", "ai"}:
                continue
            key = sender_id or sender_name
            if key in seen:
                continue
            seen.add(key)
            members.append(
                {
                    "sender_id": sender_id or sender_name,
                    "sender_name": sender_name,
                }
            )
        return members

    def format_recent_transcript(
        self,
        chat_id: str,
        limit: int = 12,
        *,
        within_hours: float | None = 6.0,
    ) -> str:
        """Format recent labeled chat lines for group-aware prompting.

        ``within_hours`` keeps only relatively fresh messages so the model
        does not treat yesterday's jokes as "just now".
        """
        rows = self.get_recent_messages(chat_id, max(1, int(limit) * 3))
        if within_hours is not None:
            cutoff = datetime.now() - timedelta(hours=float(within_hours))
            fresh = []
            for row in rows:
                ts = row.get("created_at")
                if isinstance(ts, datetime) and ts >= cutoff:
                    fresh.append(row)
            # If nothing is fresh, fall back to the newest few with age labels.
            rows = fresh if fresh else rows[-max(1, int(limit)) :]
        lines: list[str] = []
        now = datetime.now()
        for row in rows:
            role = str(row.get("role") or "user")
            name = str(row.get("sender_name") or row.get("sender_id") or "未知")
            content = conversation_text(str(row.get("content") or ""))
            if not content:
                continue
            ts = row.get("created_at")
            if isinstance(ts, datetime):
                stamp = ts.strftime("%m-%d %H:%M")
                age_min = max(0, int((now - ts).total_seconds() // 60))
                if age_min < 60:
                    age = f"{age_min}分钟前"
                elif age_min < 1440:
                    age = f"{age_min // 60}小时前"
                else:
                    age = f"{age_min // 1440}天前"
                prefix = f"[{stamp}|{age}] "
            else:
                prefix = ""
            lines.append(f"{prefix}{name}：{content}")
        return "\n".join(lines[-max(1, int(limit)) :])


    def remember_user_message(
        self,
        *,
        identity_key: str,
        chat_id: str,
        sender_id: str,
        sender_name: str,
        content: str,
        max_items: int = 40,
        half_life_days: float = 14.0,
        min_strength: float = 0.12,
    ) -> None:
        text = " ".join(str(content or "").split()).strip()
        if not self._is_memory_candidate(text):
            return
        text = text[:300]
        now = datetime.now()
        session = self.session_factory()
        try:
            row = session.query(UserMemory).filter(UserMemory.identity_key == identity_key).one_or_none()
            entries = self._decode_entries(row.memory_text if row else "[]")
            merged = False
            for entry in entries:
                if entry["text"] == text:
                    memory_curve.reinforce(entry, now)
                    merged = True
                    break
            if not merged:
                entries.append(memory_curve.new_entry(text, now))
            entries = memory_curve.prune(
                entries,
                now,
                half_life_days=half_life_days,
                min_strength=min_strength,
                max_items=max_items,
            )
            if row is None:
                row = UserMemory(
                    identity_key=identity_key,
                    chat_id=str(chat_id or ""),
                    sender_id=str(sender_id or ""),
                    sender_name=str(sender_name or sender_id or ""),
                )
                session.add(row)
            row.chat_id = str(chat_id or "")
            row.sender_id = str(sender_id or "")
            row.sender_name = str(sender_name or sender_id or "")
            row.memory_text = json.dumps(entries, ensure_ascii=False)
            row.updated_at = now
            session.commit()
        finally:
            session.close()

    # ------------------------------------------------------------------
    # People: one identity across private chats, groups and Moments
    # ------------------------------------------------------------------
    def register_person(
        self,
        person_id: str,
        display_name: str = "",
        *,
        chat_id: str = "",
        chat_name: str = "",
        is_group: bool = False,
        aliases: list[str] | None = None,
    ) -> str:
        person_id = str(person_id or "").strip()
        if not person_id:
            return ""
        now = datetime.now()
        session = self.session_factory()
        try:
            row = session.query(PersonIdentity).filter(PersonIdentity.person_id == person_id).one_or_none()
            if row is None:
                row = PersonIdentity(
                    person_id=person_id,
                    display_name=str(display_name or "").strip(),
                    first_seen=now,
                )
                session.add(row)
            if str(display_name or "").strip():
                row.display_name = str(display_name).strip()
            known_aliases = self._load_json_list(row.aliases_json)
            for value in [display_name, *(aliases or [])]:
                value = str(value or "").strip()
                if value and value not in known_aliases:
                    known_aliases.append(value)
            row.aliases_json = json.dumps(known_aliases[-20:], ensure_ascii=False)
            if chat_id:
                chats = self._load_json_list(row.chats_json, expect_dicts=True)
                label = str(chat_name or chat_id)
                for item in chats:
                    if str(item.get("chat_id") or "") == str(chat_id):
                        item["last_seen"] = now.isoformat(timespec="seconds")
                        item["chat_name"] = label
                        item["is_group"] = bool(is_group)
                        break
                else:
                    chats.append({
                        "chat_id": str(chat_id),
                        "chat_name": label,
                        "is_group": bool(is_group),
                        "last_seen": now.isoformat(timespec="seconds"),
                    })
                row.chats_json = json.dumps(chats[-20:], ensure_ascii=False)
            row.last_seen = now
            session.commit()
            return person_id
        finally:
            session.close()

    def get_person_profile(self, person_id: str) -> dict | None:
        person_id = str(person_id or "").strip()
        if not person_id:
            return None
        session = self.session_factory()
        try:
            row = session.query(PersonIdentity).filter(PersonIdentity.person_id == person_id).one_or_none()
            if row is None:
                return None
            return {
                "person_id": row.person_id,
                "display_name": row.display_name,
                "aliases": self._load_json_list(row.aliases_json),
                "chats": self._load_json_list(row.chats_json, expect_dicts=True),
                "first_seen": row.first_seen,
                "last_seen": row.last_seen,
            }
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Memory reads (Ebbinghaus decay + spacing reinforcement)
    # ------------------------------------------------------------------
    def get_memory_items(
        self,
        identity_key: str,
        limit: int = 8,
        *,
        half_life_days: float = 14.0,
        min_strength: float = 0.12,
        touch: bool = True,
    ) -> list[str]:
        session = self.session_factory()
        try:
            row = session.query(UserMemory).filter(UserMemory.identity_key == identity_key).one_or_none()
            if row is None:
                return []
            all_entries = self._decode_entries(row.memory_text)
            entries = memory_curve.rank(
                all_entries,
                half_life_days=half_life_days,
                min_strength=min_strength,
                limit=limit,
            )
            if touch and entries:
                selected = {entry["text"] for entry in entries}
                for entry in all_entries:
                    if entry["text"] in selected:
                        memory_curve.reinforce(entry)
                row.memory_text = json.dumps(all_entries, ensure_ascii=False)
                row.updated_at = datetime.now()
                session.commit()
            return [entry["text"] for entry in entries]
        finally:
            session.close()

    def get_memory_items_for_aliases(
        self,
        identity_key: str,
        identity_aliases: list[str] | None = None,
        limit: int = 8,
        *,
        half_life_days: float = 14.0,
        min_strength: float = 0.12,
        touch: bool = True,
    ) -> list[str]:
        """Read merged memories for an identity and its configured aliases."""

        aliases = {
            _normalize_identity_token(value) for value in (identity_aliases or [])
        }
        aliases.discard("")
        if not aliases:
            return self.get_memory_items(
                identity_key,
                limit,
                half_life_days=half_life_days,
                min_strength=min_strength,
                touch=touch,
            )
        session = self.session_factory()
        try:
            rows = session.query(UserMemory).all()
            matched = []
            for row in rows:
                row_tokens = {
                    _normalize_identity_token(row.sender_id),
                    _normalize_identity_token(row.sender_name),
                }
                if row.identity_key == identity_key or aliases & row_tokens:
                    matched.append(row)
            return self._rank_rows(matched, limit, half_life_days, min_strength, touch, session)
        finally:
            session.close()

    def get_memory_items_for_person(
        self,
        person_key: str,
        *,
        sender_id: str = "",
        sender_name: str = "",
        identity_aliases: list[str] | None = None,
        limit: int = 8,
        half_life_days: float = 14.0,
        min_strength: float = 0.12,
        touch: bool = True,
    ) -> list[str]:
        """Merge the person's memory even if legacy rows used old chat keys."""

        aliases = {_normalize_identity_token(value) for value in (identity_aliases or [])}
        aliases.discard("")
        wanted_sender = str(sender_id or "").strip()
        wanted_name = _normalize_identity_token(sender_name)
        session = self.session_factory()
        try:
            rows = session.query(UserMemory).all()
            matched = []
            for row in rows:
                row_tokens = {
                    _normalize_identity_token(row.sender_id),
                    _normalize_identity_token(row.sender_name),
                }
                if row.identity_key == person_key:
                    matched.append(row)
                elif wanted_sender and str(row.sender_id or "") == wanted_sender:
                    matched.append(row)
                elif aliases & row_tokens:
                    matched.append(row)
                elif not wanted_sender and wanted_name and wanted_name in row_tokens:
                    matched.append(row)
            return self._rank_rows(matched, limit, half_life_days, min_strength, touch, session)
        finally:
            session.close()

    def _rank_rows(
        self,
        rows: list[UserMemory],
        limit: int,
        half_life_days: float,
        min_strength: float,
        touch: bool,
        session,
    ) -> list[str]:
        merged: dict[str, dict] = {}
        for row in rows:
            for entry in self._decode_entries(row.memory_text):
                previous = merged.get(entry["text"])
                if previous is None or float(entry.get("importance") or 0) > float(previous.get("importance") or 0):
                    merged[entry["text"]] = entry
        ranked = memory_curve.rank(
            list(merged.values()),
            half_life_days=half_life_days,
            min_strength=min_strength,
            limit=limit,
        )
        if touch and ranked and rows:
            now = datetime.now()
            selected = {entry["text"] for entry in ranked}
            for row in rows:
                entries = self._decode_entries(row.memory_text)
                changed = False
                for entry in entries:
                    if entry["text"] in selected:
                        memory_curve.reinforce(entry, now)
                        changed = True
                if changed:
                    row.memory_text = json.dumps(entries, ensure_ascii=False)
                    row.updated_at = now
            session.commit()
        return [entry["text"] for entry in ranked]

    def clear_memory(self, identity_key: str) -> bool:
        session = self.session_factory()
        try:
            count = session.query(UserMemory).filter(UserMemory.identity_key == identity_key).delete()
            session.commit()
            return bool(count)
        finally:
            session.close()

    def clear_person_memory(self, person_key: str, sender_id: str = "") -> bool:
        session = self.session_factory()
        try:
            query = session.query(UserMemory)
            rows = [
                row for row in query.all()
                if row.identity_key == person_key
                or (sender_id and str(row.sender_id or "") == str(sender_id))
            ]
            for row in rows:
                session.delete(row)
            session.commit()
            return bool(rows)
        finally:
            session.close()

    @staticmethod
    def _decode_entries(value: str) -> list[dict]:
        try:
            data = json.loads(value or "[]")
        except (TypeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        entries = []
        for item in data:
            entry = memory_curve.normalize_entry(item)
            if entry is not None:
                entries.append(entry)
        return entries

    @staticmethod
    def _decode_memory(value: str) -> list[str]:
        return [
            entry["text"]
            for entry in HistoryStore._decode_entries(value)
        ]

    @staticmethod
    def _load_json_list(value: str, *, expect_dicts: bool = False) -> list:
        try:
            data = json.loads(value or "[]")
        except (TypeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        if expect_dicts:
            return [item for item in data if isinstance(item, dict)]
        return [str(item) for item in data if str(item).strip()]

    @staticmethod
    def _is_memory_candidate(text: str) -> bool:
        if len(text) < 2:
            return False
        lowered = text.lower()
        # A bare wake word or greeting is conversational glue, not a fact
        # about the person. Keeping it in long-term memory both wastes the
        # small memory window and can make a stale sender mapping look like an
        # established identity.
        normalized = re.sub(r"[\s@，。！？、,.!?~～]+", "", lowered)
        if normalized in {
            "娜娜",
            "呐呐",
            "在吗",
            "在么",
            "你好",
            "嗨",
            "hi",
            "hello",
        }:
            return False
        blocked = (
            "sk-",
            "api_key",
            "apikey",
            "password",
            "\u5bc6\u7801",
            "\u67e5\u770b\u6211\u7684\u8bb0\u5fc6",
            "\u6e05\u9664\u6211\u7684\u8bb0\u5fc6",
        )
        if any(token in lowered for token in blocked):
            return False
        if "\u603b\u7ed3" in text and re.search(r"(?:50|100)\s*\u6761", text):
            return False
        return True
