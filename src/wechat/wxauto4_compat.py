"""Compatibility helpers for free wxauto4 on newer WeChat 4.x builds.

wxauto4 41.1.2 looks for the profile card below the main window.  WeChat
4.1.11 moved that card to a top-level ``mmui::ProfileUniquePop`` window.
Only client construction is patched here; all public wxauto4 foreground APIs
remain in use afterwards.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PATCH_LOCK = threading.Lock()
_PROFILE_WINDOW_CLASS = "mmui::ProfileUniquePop"
_MAIN_WINDOW_CLASS = "mmui::MainWindow"
_WECHAT_TAB_NAME = "\u5fae\u4fe1"


def _file_version(path: str | Path) -> tuple[int, int, int, int] | None:
    try:
        import win32api

        info = win32api.GetFileVersionInfo(str(path), "\\")
        ms = info["FileVersionMS"]
        ls = info["FileVersionLS"]
        return (
            win32api.HIWORD(ms),
            win32api.LOWORD(ms),
            win32api.HIWORD(ls),
            win32api.LOWORD(ls),
        )
    except Exception:
        return None


def detect_wechat_version() -> tuple[int, int, int, int] | None:
    """Return the installed/running WeChat version when it can be detected."""

    try:
        import psutil

        for process in psutil.process_iter(["name", "exe"]):
            try:
                if str(process.info.get("name") or "").lower() != "weixin.exe":
                    continue
                executable = process.info.get("exe")
                if executable and (version := _file_version(executable)):
                    return version
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
    except Exception:
        logger.debug("Unable to inspect running WeChat processes", exc_info=True)

    candidates = (
        Path("C:/Program Files/Tencent/Weixin/Weixin.exe"),
        Path("C:/Program Files (x86)/Tencent/Weixin/Weixin.exe"),
    )
    for executable in candidates:
        if executable.exists() and (version := _file_version(executable)):
            return version
    return None


def needs_profile_popover_compat(
    version: tuple[int, int, int, int] | None,
) -> bool:
    """Whether the WeChat 4.1.11-style top-level profile card is expected."""

    return bool(version and version >= (4, 1, 9, 0))


def _find_profile_window(process_id: int) -> Any | None:
    from wxauto4.uia import uiautomation as auto

    for control in auto.GetRootControl().GetChildren():
        try:
            if (
                control.ProcessId == process_id
                and control.ClassName == _PROFILE_WINDOW_CLASS
            ):
                return control
        except Exception:
            continue
    return None


def _click_avatar(main_control: Any) -> None:
    """Click the avatar area that WeChat 4.1.11 no longer exposes as a control."""

    import win32api
    import win32con

    nav = main_control.ToolBarControl(
        AutomationId="MainView.main_tabbar",
        searchDepth=12,
    )
    if not nav.Exists(1):
        raise LookupError("WeChat navigation bar was not found")

    first_tab = nav.ButtonControl(Name=_WECHAT_TAB_NAME, searchDepth=4)
    nav_rect = nav.BoundingRectangle
    if first_tab.Exists(0.5):
        # Current layout: the avatar is 68 px tall and ends about 32 px above
        # the first navigation item.
        y = first_tab.BoundingRectangle.top - 66
    else:
        y = nav_rect.top + 122
    x = (nav_rect.left + nav_rect.right) // 2

    win32api.SetCursorPos((int(x), int(y)))
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.04)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def _read_profile_info(profile: Any) -> dict[str, str]:
    nickname = ""
    account = ""

    nickname_control = profile.TextControl(
        AutomationId="right_v_view.nickname_button_view.display_name_text",
        searchDepth=12,
    )
    if nickname_control.Exists(0.8):
        nickname = str(nickname_control.Name or "").strip()

    if not nickname:
        avatar = profile.ButtonControl(
            ClassName="mmui::ContactHeadView",
            searchDepth=12,
        )
        if avatar.Exists(0.5):
            nickname = str(avatar.Name or "").strip()

    account_control = profile.TextControl(
        AutomationId=(
            "right_v_view.user_info_center_view.basic_line_view.ProfileTextView"
        ),
        searchDepth=12,
    )
    if account_control.Exists(0.5):
        account = str(account_control.Name or "").strip()

    return {
        "nickname": nickname,
        "name": nickname,
        "Name": nickname,
        "NickName": nickname,
        "account": account,
        "wxid": account,
    }


def _compat_get_my_info(window: Any) -> dict[str, str]:
    """Replacement for ``WeChatMainWnd.get_my_info`` on WeChat 4.1.11."""

    info: dict[str, str] = {}
    profile = None
    try:
        main_control = window.control
        main_control.SwitchToThisWindow()
        process_id = main_control.ProcessId
        profile = _find_profile_window(process_id)

        for _ in range(2):
            if profile is not None:
                break
            _click_avatar(main_control)
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                profile = _find_profile_window(process_id)
                if profile is not None:
                    break
                time.sleep(0.08)

        if profile is not None:
            info = _read_profile_info(profile)
    except Exception:
        # Missing profile information must not prevent message automation.
        logger.warning("Unable to read WeChat profile; continuing without nickname", exc_info=True)
    finally:
        if profile is not None:
            try:
                profile.SendKeys("{Esc}")
            except Exception:
                logger.debug("Unable to close WeChat profile card", exc_info=True)

    window.myinfo = info
    window.nickname = info.get("nickname", "")
    return info


def create_wechat_client(*, ads: bool = False) -> Any:
    """Create a free wxauto4 client with WeChat 4.1.11 compatibility."""

    from wxauto4 import WeChat

    version = detect_wechat_version()
    if not needs_profile_popover_compat(version):
        return WeChat(ads=ads)

    from wxauto4.ui.main import WeChatMainWnd

    logger.info(
        "Detected WeChat %s; enabling wxauto4 profile-popover compatibility",
        ".".join(map(str, version or ())),
    )
    with _PATCH_LOCK:
        original = WeChatMainWnd.get_my_info
        WeChatMainWnd.get_my_info = _compat_get_my_info
        try:
            client = WeChat(ads=ads, resize=False)
        finally:
            WeChatMainWnd.get_my_info = original

    info = getattr(client, "myinfo", None)
    if isinstance(info, dict):
        nickname = str(
            info.get("nickname")
            or info.get("name")
            or info.get("NickName")
            or info.get("Name")
            or ""
        ).strip()
        client.nickname = nickname
        client.name = nickname
    return client
