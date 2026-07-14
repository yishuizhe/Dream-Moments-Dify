"""Local SQLite persistence for chat history and per-member memory."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

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


Base.metadata.create_all(engine)


def make_identity_key(chat_id: str, sender_id: str, is_group: bool) -> str:
    stable_sender = str(sender_id or "unknown").strip() or "unknown"
    if is_group:
        return f"group:{chat_id}:member:{stable_sender}"
    return f"private:{stable_sender}"


class HistoryStore:
    """Thread-safe-by-session access to history and compact local memories."""

    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or Session

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

    def remember_user_message(
        self,
        *,
        identity_key: str,
        chat_id: str,
        sender_id: str,
        sender_name: str,
        content: str,
        max_items: int = 12,
    ) -> None:
        text = " ".join(str(content or "").split()).strip()
        if not self._is_memory_candidate(text):
            return
        text = text[:300]
        session = self.session_factory()
        try:
            row = session.query(UserMemory).filter(UserMemory.identity_key == identity_key).one_or_none()
            items = self._decode_memory(row.memory_text if row else "[]")
            items = [item for item in items if item != text]
            items.append(text)
            items = items[-max(1, int(max_items)):]
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
            row.memory_text = json.dumps(items, ensure_ascii=False)
            row.updated_at = datetime.now()
            session.commit()
        finally:
            session.close()

    def get_memory_items(self, identity_key: str) -> list[str]:
        session = self.session_factory()
        try:
            row = session.query(UserMemory).filter(UserMemory.identity_key == identity_key).one_or_none()
            return self._decode_memory(row.memory_text if row else "[]")
        finally:
            session.close()

    def clear_memory(self, identity_key: str) -> bool:
        session = self.session_factory()
        try:
            count = session.query(UserMemory).filter(UserMemory.identity_key == identity_key).delete()
            session.commit()
            return bool(count)
        finally:
            session.close()

    @staticmethod
    def _decode_memory(value: str) -> list[str]:
        try:
            data = json.loads(value or "[]")
        except (TypeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [str(item).strip() for item in data if str(item).strip()]

    @staticmethod
    def _is_memory_candidate(text: str) -> bool:
        if len(text) < 2:
            return False
        lowered = text.lower()
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
