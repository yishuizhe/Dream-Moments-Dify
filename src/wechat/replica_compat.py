"""Compatibility client for WeChat 4.1.12 and newer.

WeChat 4.1.12 no longer exposes the message list through the UI Automation
tree used by wxauto4.  ``wechatauto-replica`` reads incoming messages from the
logged-in client's local database and uses its UIA/OCR hybrid driver only when
sending.  This facade keeps the small wxauto-shaped API consumed by the
project's polling adapter.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


_GROUP_SENDER_RE = re.compile(r"^(wxid_[0-9A-Za-z_]+):\s*\n")
logger = logging.getLogger(__name__)


def _safe_ocr_name_matches(ocr_name: str, target: str) -> bool:
    """Tolerate one clipped/extra edge character without broad fuzzy matches."""

    observed = re.sub(r"\s+", "", str(ocr_name or ""))
    expected = re.sub(r"\s+", "", str(target or ""))
    if not observed or not expected:
        return False
    if observed == expected or observed in expected or expected in observed:
        return True
    if len(expected) < 5:
        return False
    # WeChat often clips the first or final glyph and sometimes joins one
    # neighbouring glyph from the avatar/time column.  Require almost the
    # complete target so similar short contact names cannot collide.
    return expected[:-1] in observed or expected[1:] in observed


def _search_ocr_name_matches(ocr_name: str, target: str) -> bool:
    """Allow one OCR substitution while selecting an already-filtered result."""

    if _safe_ocr_name_matches(ocr_name, target):
        return True
    observed = re.sub(r"^[^\u4e00-\u9fffA-Za-z]+", "", str(ocr_name or ""))
    expected = re.sub(r"\s+", "", str(target or ""))
    if len(expected) < 4 or len(observed) != len(expected):
        return False
    return sum(left != right for left, right in zip(observed, expected)) <= 1


def _ocr_name_similarity(ocr_name: str, target: str) -> float:
    observed = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", str(ocr_name or ""))
    expected = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", str(target or ""))
    if not observed or not expected:
        return 0.0
    if expected in observed or observed in expected:
        return 1.0
    return SequenceMatcher(None, observed, expected).ratio()


def _title_ocr_name_matches(ocr_name: str, target: str) -> bool:
    """Match only title-line OCR, tolerating a single difficult CJK glyph."""

    if _safe_ocr_name_matches(ocr_name, target):
        return True
    expected = re.sub(r"\s+", "", str(target or ""))
    return len(expected) >= 4 and _ocr_name_similarity(ocr_name, target) >= 0.72


def _merge_search_ocr_rows(
    batches: list[list[tuple[Any, ...]]], target: str
) -> list[tuple[Any, ...]]:
    """Merge two OCR scales, keeping the clearest text at each position."""

    merged: list[tuple[Any, ...]] = []
    for batch in batches:
        for row in batch:
            if len(row) < 5:
                continue
            same_index = next(
                (
                    index
                    for index, current in enumerate(merged)
                    if abs(current[1] - row[1]) <= 5
                    and abs(current[2] - row[2]) <= 3
                ),
                None,
            )
            if same_index is None:
                merged.append(row)
                continue
            current = merged[same_index]
            current_rank = (
                _ocr_name_similarity(str(current[0] or ""), target),
                len(str(current[0] or "")),
            )
            row_rank = (
                _ocr_name_similarity(str(row[0] or ""), target),
                len(str(row[0] or "")),
            )
            if row_rank > current_rank:
                merged[same_index] = row
    return merged


def _collapse_search_rows_by_line(
    rows: list[tuple[Any, ...]], target: str
) -> list[tuple[Any, ...]]:
    """Collapse OCR fragments/scales that describe the same visual row."""

    lines: list[list[tuple[Any, ...]]] = []
    for row in sorted(rows, key=lambda item: item[2]):
        if lines and abs(lines[-1][0][2] - row[2]) <= 3:
            lines[-1].append(row)
        else:
            lines.append([row])
    return [
        max(
            line,
            key=lambda row: (
                _ocr_name_similarity(str(row[0] or ""), target),
                len(str(row[0] or "")),
            ),
        )
        for line in lines
    ]


def _search_result_click_point(
    row: tuple[Any, ...], sidebar_right: int
) -> tuple[int, int]:
    """Click the result text area instead of an avatar-shaped OCR box."""

    _text, x, y, width, height = row[:5]
    return max(
        int(x) + int(width) // 2,
        int(sidebar_right * 0.55),
    ), int(y) + int(height) // 2


def _select_search_result(
    rows: list[tuple[Any, ...]],
    target: str,
    *,
    sidebar_right: int,
    render_h: int,
    expected_group: bool | None,
) -> tuple[Any, ...] | None:
    """Select a search result only when its chat type is unambiguous.

    WeChat may return an enterprise contact and a group with the same display
    name. Group rows have a nearby ``包含：<member>`` preview, while enterprise
    contacts have an ``企业：`` subtitle. A stable ``@chatroom`` id tells the
    caller which kind is intended. If OCR cannot distinguish the candidates,
    refusing to send is safer than picking the first result.
    """

    group_headers = _collapse_search_rows_by_line([
        row for row in rows if len(row) >= 3 and "群聊" in str(row[0] or "")
    ], target)
    if expected_group is True:
        most_used_headers = _collapse_search_rows_by_line([
            row
            for row in rows
            if len(row) >= 3
            and "常" in str(row[0] or "")
            and "用" in str(row[0] or "")
        ], target)
        if len(most_used_headers) == 1:
            most_top = most_used_headers[0][2]
            related_markers = [
                row[2]
                for row in rows
                if len(row) >= 3
                and row[2] > most_top
                and "包含" in str(row[0] or "")
            ]
            # OCR may miss the light-grey next section heading. Do not let a
            # distant `包含` marker absorb 联系人/群聊 into 最常使用.
            most_bottom = min(related_markers + [most_top + 115])
            most_used_matches = _collapse_search_rows_by_line([
                row
                for row in rows
                if len(row) >= 5
                # On WeChat 4.1.12 the first OCR box may include the group
                # avatar and begin around x=87 in a 300px sidebar. The old
                # 30% cutoff (x=90) discarded that exact result by 3px.
                and row[1] >= sidebar_right * 0.20
                and most_top + 15 < row[2] < most_bottom
                and _ocr_name_similarity(str(row[0] or ""), target) >= 0.55
            ], target)
            if len(most_used_matches) == 1:
                return most_used_matches[0]

        enterprise_rows = [
            row
            for row in rows
            if len(row) >= 3 and str(row[0] or "").strip().startswith("企业")
        ]
        if len(group_headers) == 1:
            group_top = group_headers[0][2]
        else:
            return None
        boundary_rows = [
            row
            for row in rows
            if len(row) >= 3
            and row[2] > group_top
            and ("搜索" in str(row[0] or "") or "结果" in str(row[0] or ""))
        ]
        group_bottom = min(
            [row[2] for row in boundary_rows] or [render_h * 0.48]
        )
        group_rows = _collapse_search_rows_by_line([
            row
            for row in rows
            if len(row) >= 5
            and row[1] >= sidebar_right * 0.20
            and group_top + 15 < row[2] < group_bottom
            and "包含" not in str(row[0] or "")
            and _ocr_name_similarity(str(row[0] or ""), target) >= 0.25
        ], target)
        if len(group_rows) == 1:
            return group_rows[0]
        strong_rows = [
            row
            for row in group_rows
            if _ocr_name_similarity(str(row[0] or ""), target) >= 0.55
        ]
        return strong_rows[0] if len(strong_rows) == 1 else None

    enterprise_markers = [
        row
        for row in rows
        if len(row) >= 5
        and str(row[0] or "").strip().startswith("企业")
        and row[1] >= sidebar_right * 0.30
        and row[2] < render_h * 0.42
    ]
    if expected_group is False and len(enterprise_markers) == 1:
        return enterprise_markers[0]

    candidates: list[dict[str, Any]] = []
    for row in rows:
        if len(row) < 5:
            continue
        text, x, y, _width, _height = row[:5]
        if (
            y >= render_h * 0.47
            or x < sidebar_right * 0.20
            or "包含" in str(text or "")
            or "企业" in str(text or "")
        ):
            continue
        score = _ocr_name_similarity(str(text or ""), target)
        if score >= 0.55:
            candidates.append({"score": score, "row": row, "group": False, "enterprise": False})

    candidates.sort(key=lambda item: item["row"][2])
    for index, candidate in enumerate(candidates):
        y = candidate["row"][2]
        next_y = (
            candidates[index + 1]["row"][2]
            if index + 1 < len(candidates)
            else y + 100
        )
        context_bottom = min(y + 100, next_y - 1)
        context = [
            str(row[0] or "")
            for row in rows
            if len(row) >= 3 and y < row[2] <= context_bottom
        ]
        candidate["group"] = any("包含" in text for text in context)
        candidate["enterprise"] = any("企业" in text for text in context)

    if expected_group is True:
        typed = [candidate for candidate in candidates if candidate["group"]]
        if len(typed) == 1:
            return typed[0]["row"]
        if typed:
            return None
        if len(candidates) == 1 and not candidates[0]["enterprise"]:
            return candidates[0]["row"]
        return None

    if expected_group is False:
        typed = [candidate for candidate in candidates if not candidate["group"]]
        return typed[0]["row"] if len(typed) == 1 else None

    return candidates[0]["row"] if len(candidates) == 1 else None


@dataclass(slots=True)
class ReplicaMessage:
    content: str
    sender: str
    sender_id: str
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
        self._uia_sender: Any = None
        self._send_lock = threading.RLock()
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
        if self._uia_sender is None:
            from wechatauto.guia import (
                SIDEBAR_LEFT,
                VK_A,
                VK_DELETE,
                VK_V,
                WeChatGUI,
            )

            class SafeWeChatGUI(WeChatGUI):
                """Use OCR only for target confirmation, never window cleanup."""

                def calibrate_layout(self, save: bool = True) -> bool:
                    # WeChat 4.1.12 uses a wider session pane than the upstream
                    # 0.22 fallback. Detect its vertical divider from a screen
                    # sample; the divider is the only strong edge that persists
                    # through most rows, unlike avatars and message bubbles.
                    try:
                        from statistics import median

                        self._update_render_rect()
                        top = min(90, max(0, self.render_h // 8))
                        bottom = max(top + 20, self.render_h - 120)
                        image = self._grab_screen(
                            self._rel_to_screen((0, top, self.render_w, bottom))
                        ).convert("RGB")
                        best_score = -1.0
                        best_x = 0
                        for x in range(int(self.render_w * 0.20), int(self.render_w * 0.38)):
                            diffs = []
                            for y in range(0, image.height, 5):
                                left = image.getpixel((x, y))
                                right = image.getpixel((x + 1, y))
                                diffs.append(sum(abs(left[i] - right[i]) for i in range(3)))
                            score = float(median(diffs)) if diffs else 0.0
                            if score > best_score:
                                best_score, best_x = score, x
                        if best_score >= 10.0:
                            self._sidebar_ratio = (best_x + 1) / self.render_w
                            self._update_layout()
                            return True
                    except Exception:
                        pass
                    return False

                def _get_uia(self):
                    # 4.1.12.55 exposes only an empty render shell through UIA.
                    return None

                def ensure_visible(self) -> bool:
                    if not self.bring_to_front(keep_topmost=True):
                        self._minimize_blockers()
                        time.sleep(0.4)
                        if not self.bring_to_front(keep_topmost=True):
                            return False
                    self._update_render_rect()
                    return (
                        self._input._user32.GetForegroundWindow() == self.main_hwnd
                        and self.desktop_available()
                    )

                @staticmethod
                def _name_matches(ocr_name: str, target: str) -> bool:
                    return _safe_ocr_name_matches(ocr_name, target)

                def _chat_is_open(self, name: str) -> bool:
                    """Confirm only against the right-pane title.

                    The upstream OCR box starts 60 pixels inside the session
                    sidebar.  A visible group name there can therefore make an
                    unrelated private chat look like the requested group.  A
                    false positive is unsafe for a sender, so keep the box
                    strictly to the right pane even if that means retrying an
                    occasional hard-to-read title.
                    """

                    normalized_name = re.sub(r"\s+", "", str(name or ""))
                    if not normalized_name:
                        return False
                    for attempt, scale in enumerate((2, 3, 2)):
                        try:
                            self._update_render_rect()
                            results = self.ocr_zoomed(
                                # Read the title line only. Group announcements
                                # begin below this crop and may contain a contact
                                # name, which must never confirm a send target.
                                (self.right_pane_left, 20, self.render_w, 75),
                                scale=scale,
                            )
                            title = "".join(text.strip() for text, *_ in results)
                            if _title_ocr_name_matches(title, normalized_name):
                                return True
                        except Exception:
                            pass
                        if attempt < 2:
                            time.sleep(0.15)
                    return False

                def _search_chat(self, name: str, expected_group: bool | None = None) -> bool:
                    """Search and click the exact group/contact result safely."""

                    crop_top = int(self.render_h * 0.08)
                    ambiguous = False
                    for _ in range(3):
                        # Mouse hit-testing on WeChat's transparent render
                        # child is intermittent. Ctrl+F deterministically
                        # focuses the global search field.
                        self._input.key(0x46, ctrl=True)  # VK_F
                        time.sleep(0.3)
                        self._input.key(VK_A, ctrl=True)
                        self._input.key(VK_DELETE)
                        self.set_clipboard(name)
                        self._input.key(VK_V, ctrl=True)
                        time.sleep(0.8)
                        search_region = (
                            SIDEBAR_LEFT,
                            crop_top,
                            self.sidebar_right,
                            self.render_h,
                        )
                        results = _merge_search_ocr_rows(
                            [
                                self.ocr_zoomed(search_region, scale=3),
                                self.ocr_zoomed(search_region, scale=4),
                            ],
                            name,
                        )
                        selected = _select_search_result(
                            results,
                            name,
                            sidebar_right=self.sidebar_right,
                            render_h=self.render_h,
                            expected_group=expected_group,
                        )
                        if selected:
                            _text, x, y, width, height = selected
                            click_x, click_y = _search_result_click_point(
                                selected, self.sidebar_right
                            )
                            self.wx_click(
                                self.origin_x + click_x,
                                self.origin_y + click_y,
                            )
                            time.sleep(0.8)
                            if self._chat_is_open(name):
                                return True
                            time.sleep(0.6)
                            if self._chat_is_open(name):
                                return True
                        else:
                            ambiguous = True
                            time.sleep(0.35)
                    if ambiguous:
                        logger.error(
                            "微信搜索结果存在同名或类型不明的目标，已拒绝发送: %s (%s)",
                            name,
                            "群聊" if expected_group else "联系人",
                        )
                    return False

                def open_chat(
                    self,
                    name: str,
                    exact: bool = False,
                    expected_group: bool | None = None,
                ) -> bool:
                    if not self.ensure_visible():
                        return False
                    self._update_render_rect()
                    if expected_group is None and self._chat_is_open(name):
                        return True
                    if self._search_chat(name, expected_group=expected_group):
                        return self._chat_is_open(name)
                    return False

            self._uia_sender = SafeWeChatGUI()
            self._uia_sender.calibrate_layout(save=False)
        return self._uia_sender

    def _open_send_target(self, who: str, username: str) -> Any:
        sender = self._sender
        expected_group = username.endswith("@chatroom")
        if not sender.open_chat(who, exact=True, expected_group=expected_group):
            sender.restore_zorder()
            raise RuntimeError(f"无法打开微信发送目标: {who}")
        if not sender._chat_is_open(who):
            sender.restore_zorder()
            raise RuntimeError(f"微信发送目标校验失败: {who}")
        return sender

    @staticmethod
    def _assert_send_target(sender: Any, who: str) -> None:
        """Abort before Enter if focus is no longer on the requested chat."""

        if not sender._chat_is_open(who):
            raise RuntimeError(f"微信发送目标在输入过程中发生变化: {who}")

    @staticmethod
    def _safe_input_box(sender: Any) -> tuple[int, int, int, int]:
        return (
            sender.right_pane_left,
            sender.render_h - int(sender.render_h * 0.214),
            sender.render_w,
            sender.render_h - int(sender.render_h * 0.082),
        )

    def IsOnline(self) -> bool:  # noqa: N802
        return bool(self.myinfo.get("username"))

    def GetMyInfo(self) -> dict[str, str]:  # noqa: N802
        return dict(self.myinfo)

    def _display_name(self, username: str, *, refresh: bool = False) -> str:
        if username in self._username_to_name and not refresh:
            return self._username_to_name[username]
        if username == "filehelper":
            name = "文件传输助手"
        else:
            name = str(self._db.get_nickname(username) or username)
        previous = self._username_to_name.get(username, "")
        self._username_to_name[username] = name
        if previous and previous != name:
            # Keep the old display name as an alias for configurations that
            # have not yet been edited after a group rename.
            self._name_to_username.setdefault(previous, username)
        self._name_to_username.setdefault(name, username)
        return name

    def BindContactId(self, name: str, username: str) -> None:  # noqa: N802
        """Restore a persisted display-name → stable-id binding."""

        name = str(name or "").strip()
        username = str(username or "").strip()
        if name and username:
            self._name_to_username[name] = username

    def ResolveContactId(self, name: str) -> str:  # noqa: N802
        return self._resolve_username(name)

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
        self._current_name = self._display_name(username, refresh=True) or self._current_name
        return self._current_name

    def ChatInfo(self) -> dict[str, str]:  # noqa: N802
        return {
            "chat_name": self._current_name,
            "chat_id": self._current_username,
            "chat_type": "group" if self._current_username.endswith("@chatroom") else "friend",
        }

    def GetSession(self) -> list[dict[str, Any]]:  # noqa: N802
        result = []
        for row in self._db.get_sessions(limit=500):
            username = str(row.get("username") or "")
            result.append(
                {
                    "name": self._display_name(username, refresh=True),
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
        is_group = self._current_username.endswith("@chatroom")
        group_sender_prefix = _GROUP_SENDER_RE.match(content) if is_group else None
        # In current WeChat 4.1.12 tables, sender_id=1 is the local account.
        # Group members use other ids and plain-text rows normally include the
        # real member wxid prefix.
        if is_group:
            is_self = not group_sender_prefix and (
                sender_id in {1, "1"}
                or str(sender_id) == self.myinfo.get("username")
            )
        else:
            is_self = sender_id in {1, "1"} or str(sender_id) == self.myinfo.get("username")

        if is_self:
            sender = self.nickname or "我"
            stable_sender = self.myinfo.get("username") or "self"
        elif is_group:
            sender_username = str(row.get("sender_username") or "")
            if group_sender_prefix:
                # The numeric real_sender_id index can lag behind/reuse rows
                # after WeChat 4.1.12 database updates. The per-message wxid
                # prefix is embedded in the group message itself and is the
                # authoritative sender identity.
                sender_username = group_sender_prefix.group(1)
                content = content[group_sender_prefix.end() :]
            sender = self._display_name(sender_username) if sender_username else self._current_name
            stable_sender = sender_username or str(sender_id or sender)
        else:
            sender = self._current_name
            stable_sender = self._current_username

        raw_type = str(row.get("type") or "friend")
        is_system = raw_type in {"系统消息", "时间", "notice", "system"}
        attr = "self" if is_self else ("system" if is_system else "friend")
        return ReplicaMessage(
            content=content,
            sender=sender,
            sender_id=stable_sender,
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
        with self._send_lock:
            username = self._resolve_username(who)
            if not username:
                raise RuntimeError(f"无法解析微信发送目标: {who}")
            sender = self._open_send_target(who, username)
            try:
                box = self._safe_input_box(sender)
                if not sender.focus_input(box):
                    raise RuntimeError(f"微信输入框不可用: {who}")
                self._assert_send_target(sender, who)
                from wechatauto.guia import VK_A, VK_DELETE, VK_RETURN, VK_V

                sender.set_clipboard(msg)
                sender._input.key(VK_A, ctrl=True)
                sender._input.key(VK_DELETE)
                sender._input.key(VK_V, ctrl=True)
                time.sleep(0.35)
                try:
                    self._assert_send_target(sender, who)
                except Exception:
                    sender._input.key(VK_A, ctrl=True)
                    sender._input.key(VK_DELETE)
                    raise
                sender._input.key(VK_RETURN)
                return True
            finally:
                sender.restore_zorder()

    def SendFiles(self, filepath: str, who: str, **_: Any) -> Any:  # noqa: N802
        path = str(Path(filepath).expanduser().resolve())
        with self._send_lock:
            username = self._resolve_username(who)
            if not username:
                raise RuntimeError(f"无法解析微信发送目标: {who}")
            sender = self._open_send_target(who, username)
            try:
                box = self._safe_input_box(sender)
                if not sender.focus_input(box):
                    raise RuntimeError(f"微信输入框不可用: {who}")
                self._assert_send_target(sender, who)
                from wechatauto.guia import WeChatGUI

                if not WeChatGUI.copy_files_to_clipboard([path]):
                    raise RuntimeError(f"无法复制待发送文件: {path}")
                from wechatauto.guia import VK_RETURN, VK_V

                sender._input.key(VK_V, ctrl=True)
                time.sleep(0.8)
                try:
                    self._assert_send_target(sender, who)
                except Exception:
                    from wechatauto.guia import VK_A, VK_DELETE

                    sender._input.key(VK_A, ctrl=True)
                    sender._input.key(VK_DELETE)
                    raise
                sender._input.key(VK_RETURN)
                return True
            finally:
                sender.restore_zorder()


def create_replica_client() -> ReplicaWeChatClient:
    return ReplicaWeChatClient()
