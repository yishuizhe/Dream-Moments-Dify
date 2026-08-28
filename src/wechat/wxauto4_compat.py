"""Compatibility helpers for free wxauto4 on newer WeChat 4.x builds.

wxauto4 41.1.2 looks for the profile card below the main window.  WeChat
4.1.11 moved that card to a top-level ``mmui::ProfileUniquePop`` window.
Only client construction is patched here; all public wxauto4 foreground APIs
remain in use afterwards.
"""

from __future__ import annotations

import logging
import subprocess
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


def _wechat_process_info() -> tuple[set[int], str | None]:
    """Return running Weixin process ids and one executable path."""

    process_ids: set[int] = set()
    executable: str | None = None
    try:
        import psutil

        for process in psutil.process_iter(["pid", "name", "exe"]):
            try:
                if str(process.info.get("name") or "").lower() != "weixin.exe":
                    continue
                process_ids.add(int(process.info["pid"]))
                executable = executable or process.info.get("exe")
            except (psutil.AccessDenied, psutil.NoSuchProcess, TypeError, ValueError):
                continue
    except Exception:
        logger.debug("Unable to inspect running WeChat processes", exc_info=True)

    if not executable:
        for candidate in (
            Path("C:/Program Files/Tencent/Weixin/Weixin.exe"),
            Path("C:/Program Files (x86)/Tencent/Weixin/Weixin.exe"),
        ):
            if candidate.exists():
                executable = str(candidate)
                break
    return process_ids, executable


def _is_qt_top_level_class(class_name: str) -> bool:
    """WeChat 4.1.11+ exposes Qt Win32 class names such as Qt51514QWindowIcon."""

    return class_name.startswith("Qt") and class_name.endswith("QWindowIcon")


def _window_score(hwnd: int, class_name: str, title: str) -> tuple[int, int, int]:
    """Prefer the real Chinese main window over tray/tool/login shells."""

    import win32gui

    visible = 1 if win32gui.IsWindowVisible(hwnd) else 0
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        area = max(0, right - left) * max(0, bottom - top)
    except Exception:
        area = 0

    title_rank = {
        "\u5fae\u4fe1": 300,  # 微信
        "WeChat": 200,
        "Weixin": 50,
    }.get(title, 0)

    class_rank = 100 if class_name == _MAIN_WINDOW_CLASS else 80 if _is_qt_top_level_class(class_name) else 0
    return (visible, title_rank + class_rank, area)


def _is_candidate_main_window(class_name: str, title: str) -> bool:
    if class_name == _MAIN_WINDOW_CLASS:
        return True
    if not _is_qt_top_level_class(class_name):
        return False
    # Current WeChat main UI is a Qt top-level window titled 微信/WeChat.
    return title in {"\u5fae\u4fe1", "WeChat", "Weixin"}


def _find_native_main_window(process_ids: set[int]) -> int | None:
    """Find WeChat's top-level main window, including hidden/minimized ones.

    Newer WeChat 4.x builds keep UIA class ``mmui::MainWindow`` but report a
    Qt Win32 class such as ``Qt51514QWindowIcon``. Match both so restore/show
    still works before wxauto4 attaches via UI Automation.
    """

    if not process_ids:
        return None
    import win32gui
    import win32process

    candidates: list[tuple[tuple[int, int, int], int]] = []

    def visit(hwnd: int, _extra: object) -> bool:
        try:
            _, process_id = win32process.GetWindowThreadProcessId(hwnd)
            if process_id not in process_ids:
                return True
            class_name = win32gui.GetClassName(hwnd)
            title = win32gui.GetWindowText(hwnd) or ""
            if not _is_candidate_main_window(class_name, title):
                return True
            # Ignore tiny helper shells; the main chat UI is substantially larger.
            try:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                if (right - left) < 200 or (bottom - top) < 200:
                    return True
            except Exception:
                return True
            candidates.append((_window_score(hwnd, class_name, title), hwnd))
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(visit, None)
    except Exception:
        # pywin32 may raise when a callback returns False; keep best match.
        pass

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _restore_native_window(hwnd: int) -> None:
    import win32con
    import win32gui

    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        logger.debug("Unable to foreground WeChat main window", exc_info=True)


def ensure_wechat_main_window(timeout: float = 10.0) -> bool:
    """Restore a tray-hidden WeChat window, or ask the running client to open it."""

    process_ids, executable = _wechat_process_info()
    hwnd = _find_native_main_window(process_ids)
    if hwnd is not None:
        _restore_native_window(hwnd)
        return True

    if not executable:
        logger.warning("WeChat executable was not found")
        return False

    try:
        # Starting Weixin.exe while it is already running asks the existing
        # instance to recreate/show its main chat window.
        subprocess.Popen([executable])
    except Exception:
        logger.warning("Unable to open WeChat main window", exc_info=True)
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.2)
        process_ids, _ = _wechat_process_info()
        hwnd = _find_native_main_window(process_ids)
        if hwnd is not None:
            _restore_native_window(hwnd)
            return True

    logger.warning("WeChat process is running but its main window is still unavailable")
    return False


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

    from wxauto4.uia import uiautomation as auto

    nav = main_control.ToolBarControl(
        AutomationId="MainView.main_tabbar",
        searchDepth=12,
    )
    if not nav.Exists(1):
        raise LookupError("WeChat navigation bar was not found")

    first_tab = nav.ButtonControl(Name=_WECHAT_TAB_NAME, searchDepth=4)
    nav_rect = nav.BoundingRectangle
    if first_tab.Exists(0.5):
        # Avatar sits in the blank strip above the first navigation item.
        # 50 px above the first tab is reliable on current 4.1.11 layouts.
        y = first_tab.BoundingRectangle.top - 50
    else:
        y = nav_rect.top + 46
    x = (nav_rect.left + nav_rect.right) // 2

    # Synthetic win32 mouse events are ignored by this Qt build; UIA Click works.
    auto.Click(int(x), int(y))


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
    """Create the matching free client for the installed WeChat version."""

    ensure_wechat_main_window()
    version = detect_wechat_version()
    if version and version >= (4, 1, 12, 0):
        from .replica_compat import create_replica_client

        logger.info(
            "Detected WeChat %s; using the 4.1.12+ database/UIA hybrid backend",
            ".".join(map(str, version)),
        )
        return create_replica_client()

    from wxauto4 import WeChat

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
