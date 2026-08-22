"""Drive the already-open IX window via the Windows desktop (no DevTools, no Local API)."""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from caption_engine import lint_clips
from ego_task import parse_clips_from_text
import config

logger = logging.getLogger("ego.win_ui")

TASK_HINTS = (
    "focused timeline",
    "sub-goal",
    "subgoal",
    "ego_rectified",
    "review",
    "atlas",
    "clip export",
)

CHROME_CLASS = "Chrome_WidgetWin_1"


def say(msg: str) -> None:
    print(msg, flush=True)
    logger.info(msg)


def score_window(title: str, class_name: str = "") -> int:
    lowered = (title or "").lower()
    class_l = (class_name or "").lower()
    chrome_like = class_name == CHROME_CLASS or class_l.startswith("chrome_widgetwin")
    score = 0
    if chrome_like:
        score += 2
    if "ixbrowser" in lowered or "ix browser" in lowered:
        score += 8
    elif " ix " in f" {lowered} " or lowered.startswith("ix ") or lowered.endswith(" ix"):
        score += 4
    for hint in TASK_HINTS:
        if hint in lowered:
            score += 10
    if score == 0:
        return 0
    if not chrome_like and "ix" not in lowered:
        return 0
    return score


def drive_open_task(write: bool = True, watch_seconds: float = 12.0) -> dict[str, Any]:
    """Focus the open IX window, play the video, lint timeline text if readable."""
    if sys.platform != "win32":
        raise RuntimeError("Desktop IX control is Windows-only")

    say("DevTools is not exposed on this IX profile. Controlling the window you already opened...")
    say("Look at IX now: that window will come forward and the video should play.")
    hwnd, title = _pick_ix_window()
    say(f"Using IX window: {title or '(no title)'}")
    _focus(hwnd)
    time.sleep(0.4)
    played = _play_video(hwnd)
    say("Watch the IX window: the video should be playing now." if played else "Sent play input; check the IX window.")
    remaining = max(watch_seconds, 2.0)
    elapsed = 0.0
    while elapsed < remaining:
        step = min(2.0, remaining - elapsed)
        time.sleep(step)
        elapsed += step
        say(f"Watching video... {int(elapsed)}/{int(remaining)}s")

    body = _read_window_text(hwnd)
    clips = parse_clips_from_text(body) if body else []
    say(f"Read {len(clips)} timeline clip(s) from the window")
    reports = []
    for item in lint_clips([clip.to_dict() for clip in clips]):
        lint = item["lint"]
        reports.append(
            {
                "index": item.get("index"),
                "original": lint.original,
                "rewritten": lint.rewritten,
                "issues": [issue.__dict__ for issue in lint.issues],
                "wrote": False,
                "skipped": bool(item.get("skip_edit")),
            }
        )
        if write and lint.changed and not item.get("skip_edit"):
            say(f"Suggested caption fix: {lint.rewritten}")

    payload = {
        "mode": "ego-window",
        "window_title": title,
        "watched_video": True,
        "played": played,
        "clip_count": len(clips),
        "wrote_captions": 0,
        "quality_assistant": False,
        "submitted": False,
        "hte_edited": False,
        "clips": reports,
    }
    dest = config.ANALYSIS_RESULT
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2), flush=True)
    say(f"Done. IX window left open. Report: {dest}")
    return payload


def _pick_ix_window() -> tuple[int, str]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[tuple[int, str, str, int]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buf, length + 1)
        class_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buf, 256)
        title = title_buf.value
        class_name = class_buf.value
        points = score_window(title, class_name)
        if points > 0:
            found.append((hwnd, title, class_name, points))
        return True

    user32.EnumWindows(callback, 0)
    if not found:
        raise RuntimeError("Could not find an open IX/Chrome window. Leave the profile visible and retry.")
    found.sort(key=lambda row: row[3], reverse=True)
    hwnd, title, _cls, _score = found[0]
    return int(hwnd), title


def _focus(hwnd: int) -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    fg = user32.GetForegroundWindow()
    current_thread = kernel32.GetCurrentThreadId()
    fg_pid = wintypes.DWORD()
    fg_thread = user32.GetWindowThreadProcessId(fg, ctypes.byref(fg_pid))
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    user32.AttachThreadInput(fg_thread, current_thread, True)
    user32.AttachThreadInput(target_thread, current_thread, True)
    # Alt tap lets Windows allow a foreground switch from this process.
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(fg_thread, current_thread, False)
    user32.AttachThreadInput(target_thread, current_thread, False)


def _play_video(hwnd: int) -> bool:
    """Click the top-center play control, then Space (EGO player shortcut)."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width = max(rect.right - rect.left, 1)
    height = max(rect.bottom - rect.top, 1)
    # Screenshot layout: play triangle is top-center next to Sub-goal; video is mid-window.
    spots = ((0.50, 0.07), (0.47, 0.08), (0.53, 0.09), (0.50, 0.11), (0.50, 0.38))
    for rel_x, rel_y in spots:
        x = int(rect.left + width * rel_x)
        y = int(rect.top + height * rel_y)
        user32.SetCursorPos(x, y)
        time.sleep(0.05)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        say(f"Clicked play region at {x},{y}")
        time.sleep(0.15)
    _send_space(hwnd)
    say("Sent Space (play/pause) to the IX window")
    return True


def _send_space(hwnd: int | None = None) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    vk_space = 0x20
    if hwnd:
        user32.PostMessageW(hwnd, 0x0100, vk_space, 0)  # WM_KEYDOWN
        user32.PostMessageW(hwnd, 0x0101, vk_space, 0)  # WM_KEYUP
    user32.keybd_event(vk_space, 0, 0, 0)
    user32.keybd_event(vk_space, 0, 2, 0)


def _read_window_text(hwnd: int) -> str:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    chunks = [buf.value]
    found: list[str] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def callback(child, _lparam):
        n = user32.GetWindowTextLengthW(child)
        if n:
            child_buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(child, child_buf, n + 1)
            if child_buf.value:
                found.append(child_buf.value)
        return True

    user32.EnumChildWindows(hwnd, callback, 0)
    chunks.extend(found)
    try:
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        for win in desktop.windows():
            try:
                if int(win.handle) != int(hwnd):
                    continue
                texts = [win.window_text()]
                for ctrl in win.descendants():
                    t = ctrl.window_text()
                    if t:
                        texts.append(t)
                chunks.extend(texts)
                break
            except Exception:
                continue
    except Exception:
        logger.debug("pywinauto UIA dump skipped", exc_info=True)
    return "\n".join(chunk for chunk in chunks if chunk)
