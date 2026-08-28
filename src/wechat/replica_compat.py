"""Compatibility client for WeChat 4.1.12 and newer.

WeChat 4.1.12 no longer exposes the message list through the UI Automation
tree used by wxauto4.  ``wechatauto-replica`` reads incoming messages from the
logged-in client's local database and uses its UIA/OCR hybrid driver only when
sending.  This facade keeps the small wxauto-shaped API consumed by the
project's polling adapter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_GROUP_SENDER_RE = re.compile(r"^(wxid_[0-9A-Za-z_]+):\s*\n")


@dataclass(slots=True)
class ReplicaMessage:
    content: str
    sender: str
    type: str
    attr: str
    local_id: int | str | None = None
    sort_seq: int | None = None
    _db: Any = None
    _username: str = ""

    def download(self) -> str | None:
        """Download image/media data through the replica media reader."""

        if self._db is None or self.local_id is None or not self._username:
            return None
        from wechatauto import MediaDownloader

        downloader = MediaDownloader(self._db)
        if self.type in {"图片", "image"}:
            return downloader.download_image(self._username, int(self.local_id))
        return downloader.download_media(self._username, int(self.local_id))


class ReplicaWeChatClient:
    """Expose the subset of wxauto APIs used by Dream Moments."""

    backend_name = "wechatauto-replica"

    def __init__(self) -> None:
        try:
            from wechatauto import WeChatDB
        except ImportError as exc:
            raise RuntimeError(
                "微信 4.1.12+ 需要兼容组件，请执行: "
                "python -m pip install wechatauto-replica==1.1.9"
            ) from exc

        self._db = WeChatDB()
        self._gui: Any = None
        self._current_name = ""
        self._current_username = ""
        self._name_to_username: dict[str, str] = {}
        self._username_to_name: dict[str, str] = {}
        info = self._db.get_self_info() or {}
        self.myinfo = {
            "username": str(info.get("username") or ""),
            "nickname": str(info.get("nick_name") or info.get("username") or ""),
        }
        self.nickname = self.myinfo["nickname"]
        self.name = self.nickname

    @property
    def _sender(self) -> Any:
        if self._gui is None:
            from wechatauto import WeChatGUI

            self._gui = WeChatGUI()
        return self._gui

    def IsOnline(self) -> bool:  # noqa: N802
        return bool(self.myinfo.get("username"))

    def GetMyInfo(self) -> dict[str, str]:  # noqa: N802
        return dict(self.myinfo)

    def _display_name(self, username: str) -> str:
        if username in self._username_to_name:
            return self._username_to_name[username]
        if username == "filehelper":
            name = "文件传输助手"
        else:
            name = str(self._db.get_nickname(username) or username)
        self._username_to_name[username] = name
        self._name_to_username.setdefault(name, username)
        return name

    def _resolve_username(self, name: str) -> str:
        name = str(name or "").strip()
        if not name:
            return ""
        if name in {"filehelper", "文件传输助手"}:
            return "filehelper"
        if name in self._name_to_username:
            return self._name_to_username[name]

        hits = list(self._db.search_contact(name) or [])
        exact = [
            hit
            for hit in hits
            if name
            in {
                str(hit.get("username") or ""),
                str(hit.get("nick_name") or ""),
                str(hit.get("remark") or ""),
            }
        ]
        if len(exact) == 1:
            username = str(exact[0].get("username") or "")
            self._name_to_username[name] = username
            self._username_to_name.setdefault(username, name)
            return username

        # Group names and some remarks are resolved more reliably through the
        # active session list than through fuzzy contact search.
        for row in self._db.get_sessions(limit=500):
            username = str(row.get("username") or "")
            if username and self._display_name(username) == name:
                self._name_to_username[name] = username
                return username
        return ""

    def ChatWith(self, who: str, exact: bool = True, **_: Any) -> str | None:  # noqa: N802
        username = self._resolve_username(who)
        if not username:
            return None
        self._current_name = str(who)
        self._current_username = username
        return self._current_name

    def ChatInfo(self) -> dict[str, str]:  # noqa: N802
        return {
            "chat_name": self._current_name,
            "chat_type": "group" if self._current_username.endswith("@chatroom") else "friend",
        }

    def GetSession(self) -> list[dict[str, Any]]:  # noqa: N802
        result = []
        for row in self._db.get_sessions(limit=500):
            username = str(row.get("username") or "")
            result.append(
                {
                    "name": self._display_name(username),
                    "username": username,
                    "content": row.get("summary") or "",
                    "time": row.get("last_time") or 0,
                    "unread_count": row.get("unread") or 0,
                }
            )
        return result

    def GetAllMessage(self) -> list[ReplicaMessage]:  # noqa: N802
        if not self._current_username:
            return []
        rows = list(self._db.get_messages(self._current_username, limit=100) or [])
        # The database API returns newest-first; the polling adapter expects
        # chronological order just like wxauto4's visible message list.
        return [self._convert_message(row) for row in reversed(rows)]

    def _convert_message(self, row: dict[str, Any]) -> ReplicaMessage:
        content = str(row.get("content") or "")
        sender_id = row.get("sender_id")
        is_self = sender_id == 2 or str(sender_id) == self.myinfo.get("username")
        is_group = self._current_username.endswith("@chatroom")

        if is_self:
            sender = self.nickname or "我"
        elif is_group:
            sender_username = str(row.get("sender_username") or "")
            prefix = _GROUP_SENDER_RE.match(content)
            if prefix:
                sender_username = sender_username or prefix.group(1)
                content = content[prefix.end() :]
            sender = self._display_name(sender_username) if sender_username else self._current_name
        else:
            sender = self._current_name

        raw_type = str(row.get("type") or "friend")
        is_system = raw_type in {"系统消息", "时间", "notice", "system"}
        attr = "self" if is_self else ("system" if is_system else "friend")
        return ReplicaMessage(
            content=content,
            sender=sender,
            type=raw_type,
            attr=attr,
            local_id=row.get("local_id"),
            sort_seq=row.get("sort_seq"),
            _db=self._db,
            _username=self._current_username,
        )

    def SendMsg(  # noqa: N802
        self,
        msg: str,
        who: str,
        at: str | list[str] | None = None,
        **_: Any,
    ) -> Any:
        if at:
            return self._sender.at_member(at, msg, who)
        return self._sender.send_msg(msg, who)

    def SendFiles(self, filepath: str, who: str, **_: Any) -> Any:  # noqa: N802
        path = str(Path(filepath).expanduser().resolve())
        return self._sender.send_file(path, who)


def create_replica_client() -> ReplicaWeChatClient:
    return ReplicaWeChatClient()
