"""Drive the already-open IX window via the Windows desktop (no DevTools, no Local API)."""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from typing import Any

from caption_engine import lint_clips
from ego_task import parse_clips_from_text
from process_cdp import is_ix_chromium_exe, is_ix_launcher, is_stock_chrome_path
from review_ui import (
    estimated_use_point,
    find_phrase_click,
    find_review_use_clicks,
    find_word_click,
    ocr_text,
    parse_watched_percent,
)
import config

logger = logging.getLogger("ego.win_ui")

TASK_HINTS = (
    "focused timeline",
    "sub-goal",
    "subgoal",
    "ego_rectified",
    "clip export",
    "ego_rectified_canonical",
    "sensorfusionlab",
    "sensorfusion",
)

REJECT_TITLE_TOKENS = (
    "google chrome",
    "google gemini",
    "microsoft edge",
)

HINDI_CHROMIUM = "क्रोमियम"

CHROME_CLASS = "Chrome_WidgetWin_1"
TAB_STRIP_MIN = 110
TAB_STRIP_MAX = 160
DEFAULT_WATCH_S = 90.0
MAX_WATCH_S = 300.0
CLOCK_RE = re.compile(r"(\d{1,2}):(\d{2})\s*/\s*(\d{1,2}):(\d{2})")


def say(msg: str) -> None:
    print(msg, flush=True)
    logger.info(msg)


def score_window(title: str, class_name: str = "", exe_path: str = "") -> int:
    """Score a desktop window. Prefer IX Chromium (SensorFusionLab), never the profile manager."""
    lowered = (title or "").lower()
    if any(token in lowered for token in REJECT_TITLE_TOKENS):
        return 0
    if is_ix_launcher(title, exe_path):
        return 0
    if is_stock_chrome_path(exe_path) and not is_ix_chromium_exe(exe_path):
        return 0

    score = 0
    if is_ix_chromium_exe(exe_path):
        score += 80
    if "sensorfusionlab" in lowered or "sensorfusion" in lowered:
        score += 40
    if HINDI_CHROMIUM in (title or "") or "chromium" in lowered:
        score += 20
    class_l = (class_name or "").lower()
    chrome_like = class_name == CHROME_CLASS or class_l.startswith("chrome_widgetwin")
    if chrome_like and is_ix_chromium_exe(exe_path):
        score += 5
    for hint in TASK_HINTS:
        if hint in lowered:
            score += 10
    if score == 0:
        return 0
    if not is_ix_chromium_exe(exe_path) and "sensorfusionlab" not in lowered:
        return 0
    return score


def select_ix_window(windows: list[dict]) -> dict | None:
    """Pick the IX Browser window from enumerated desktop windows."""
    scored: list[tuple[int, dict]] = []
    for window in windows:
        points = score_window(
            window.get("title") or "",
            window.get("class_name") or "",
            window.get("exe_path") or "",
        )
        if points > 0:
            scored.append((points, window))
    if not scored:
        return None
    scored.sort(key=lambda row: row[0], reverse=True)
    return scored[0][1]


def page_click_points(left: int, top: int, width: int, height: int) -> list[tuple[int, int, str]]:
    """Click targets in the web page, never in the Chromium tab strip.

    The previous run clicked y=49 (tabs). SensorFusionLab chrome UI sits in the
    top ~110-160px; the video is in the remaining client area.
    """
    tab = min(max(int(height * 0.18), TAB_STRIP_MIN), TAB_STRIP_MAX)
    page_top = top + tab
    page_h = max(height - tab - 24, 1)
    page_left = left + 12
    page_w = max(width - 24, 1)
    return [
        (int(page_left + page_w * 0.46), int(page_top + page_h * 0.40), "video-center"),
        (int(page_left + page_w * 0.42), int(page_top + page_h * 0.14), "player-toolbar"),
    ]


def parse_media_clock(text: str) -> float | None:
    """Return duration seconds from a player clock like 0:12 / 1:45."""
    match = CLOCK_RE.search(text or "")
    if not match:
        return None
    return float(int(match.group(3)) * 60 + int(match.group(4)))


def drive_open_task(write: bool = True, watch_seconds: float | None = None) -> dict[str, Any]:
    """Focus the open IX window, play the video, lint/type timeline captions."""
    if sys.platform != "win32":
        raise RuntimeError("Desktop IX control is Windows-only")

    say("DevTools is not exposed on this IX profile. Controlling the window you already opened...")
    say("Look at IX now: that window will come forward and the video should play.")
    prev_a11y = _enable_chromium_a11y()
    try:
        hwnd, title = _pick_ix_window()
        say(f"Using IX window: {title or '(no title)'}")
        _focus(hwnd)
        time.sleep(0.8)

        ocr_words, img_w, img_h = _ocr_window(hwnd, "start")
        page_text = ocr_text(ocr_words)
        watched_pct = parse_watched_percent(page_text)
        use_ready = bool(find_review_use_clicks(ocr_words, img_w, img_h))
        if watched_pct is not None:
            say(f"Player shows Watched {watched_pct}%")

        played = False
        remaining = 0.0
        skip_watch = (
            (watched_pct is not None and watched_pct >= 80)
            or use_ready
            or "click to add text" in page_text.lower()
            or "quality assistant" in page_text.lower()
        )
        if skip_watch:
            say("Review / watched state already on screen. Skipping another full watch; fixing red Grammar clips.")
            played = True
        else:
            uia_text, uia_nodes = _read_uia(hwnd)
            played = _play_via_uia(uia_nodes)
            if not played:
                played = _play_video(hwnd)
            say("Watch the IX window: the video should be playing now." if played else "Sent play input; check the IX window.")
            duration = parse_media_clock(page_text)
            remaining = watch_seconds
            if remaining is None:
                remaining = duration if duration and duration > 2 else DEFAULT_WATCH_S
            remaining = min(max(float(remaining), 8.0), MAX_WATCH_S)
            elapsed = 0.0
            while elapsed < remaining:
                step = min(5.0, remaining - elapsed)
                time.sleep(step)
                elapsed += step
                say(f"Watching video... {int(elapsed)}/{int(remaining)}s")

        review = _apply_review_uses(hwnd, write=write)
        say(f"Clicked Review Use {review['applied']} time(s)")
        filled = _fill_missing_and_reds(hwnd, write=write)
        say(f"Filled {filled['wrote']} missing/red caption(s)")

        body = "\n".join(part for part in (filled.get("text"), review.get("text"), page_text) if part)
        clips = parse_clips_from_text(body) if body else []
        say(f"Read {len(clips)} timeline clip(s) from the window")
        preview = re.sub(r"\s+", " ", body).strip()[:220]
        if preview:
            say(f"Page text preview: {preview}")

        reports = []
        wrote = int(review["applied"]) + int(filled["wrote"])
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
            if write and lint.changed and not item.get("skip_edit") and review["applied"] == 0:
                say(f"Suggested caption fix: {lint.rewritten}")

        payload = {
            "mode": "ego-window",
            "window_title": title,
            "watched_video": True,
            "played": played,
            "watch_seconds": remaining,
            "clip_count": len(clips),
            "wrote_captions": wrote,
            "review_use_clicks": review["applied"],
            "missing_filled": filled["wrote"],
            "quality_assistant": review["applied"] > 0 or filled["wrote"] > 0,
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
    finally:
        _restore_chromium_a11y(prev_a11y)


def _pick_ix_window() -> tuple[int, str]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[dict] = []
    skipped: list[str] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        ex_style = user32.GetWindowLongW(hwnd, -20)
        if ex_style & 0x00000080:  # WS_EX_TOOLWINDOW
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width < 400 or height < 300:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buf, length + 1)
        class_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buf, 256)
        title = title_buf.value
        class_name = class_buf.value
        exe_path = _hwnd_exe(hwnd)
        row = {
            "hwnd": int(hwnd),
            "title": title,
            "class_name": class_name,
            "exe_path": exe_path,
        }
        points = score_window(title, class_name, exe_path)
        if points <= 0:
            if title and (
                any(token in title.lower() for token in REJECT_TITLE_TOKENS)
                or is_stock_chrome_path(exe_path)
                or is_ix_launcher(title, exe_path)
            ):
                skipped.append(title)
            return True
        found.append(row)
        return True

    user32.EnumWindows(callback, 0)
    for title in skipped[:8]:
        say(f"Skipping non-task window: {title}")
    chosen = select_ix_window(found)
    if chosen is None:
        seen = skipped[:8] or [row.get("title") or "(no title)" for row in found[:8]]
        raise RuntimeError(
            "Could not find the IX Chromium task window (SensorFusionLab). "
            "The profile manager / Edit Notes dashboard is not the task. "
            "Click Open on the profile, leave SensorFusionLab visible, then retry. "
            f"Saw: {seen}"
        )
    exe = chosen.get("exe_path") or ""
    say(f"IX process: {exe or '(path unknown)'}")
    return int(chosen["hwnd"]), chosen.get("title") or ""


def _hwnd_exe(hwnd: int) -> str:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if handle:
        try:
            size = wintypes.DWORD(32768)
            buf = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value
        finally:
            kernel32.CloseHandle(handle)
    try:
        import psutil

        return psutil.Process(int(pid.value)).exe()
    except Exception:
        return ""


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
    """Click once in the page (video), then Space. Never click the Chromium tab strip."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width = max(rect.right - rect.left, 1)
    height = max(rect.bottom - rect.top, 1)
    points = page_click_points(rect.left, rect.top, width, height)
    # One click on the video so we do not toggle play/pause. Then Space once.
    x, y, label = points[0]
    _click_screen(x, y)
    say(f"Clicked {label} at {x},{y} (below tab strip)")
    time.sleep(0.35)
    _send_space(hwnd)
    say("Sent Space (play) to the IX page")
    return True


def _click_screen(x: int, y: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.SetCursorPos(x, y)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def _send_space(hwnd: int | None = None) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    vk_space = 0x20
    user32.keybd_event(vk_space, 0, 0, 0)
    user32.keybd_event(vk_space, 0, 2, 0)


def _enable_chromium_a11y() -> int:
    """Ask Chromium to expose its accessibility tree (needed to read clips / Play)."""
    import ctypes

    user32 = ctypes.windll.user32
    prev = ctypes.c_int(0)
    user32.SystemParametersInfoW(0x0046, 0, ctypes.byref(prev), 0)  # SPI_GETSCREENREADER
    user32.SystemParametersInfoW(0x0047, 1, None, 0)  # SPI_SETSCREENREADER
    return int(prev.value)


def _restore_chromium_a11y(previous: int) -> None:
    import ctypes

    try:
        ctypes.windll.user32.SystemParametersInfoW(0x0047, int(previous), None, 0)
    except Exception:
        logger.debug("Could not restore screen-reader flag", exc_info=True)


def _read_uia(hwnd: int) -> tuple[str, list[Any]]:
    nodes: list[Any] = []
    texts: list[str] = []
    try:
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        target = None
        for win in desktop.windows():
            try:
                if int(win.handle) == int(hwnd):
                    target = win
                    break
            except Exception:
                continue
        if target is None:
            return "", []
        for i, ctrl in enumerate(target.descendants()):
            if i > 500:
                break
            nodes.append(ctrl)
            try:
                name = (ctrl.window_text() or "").strip()
            except Exception:
                name = ""
            if name:
                texts.append(name)
    except Exception:
        logger.debug("UIA read skipped", exc_info=True)
    return "\n".join(texts), nodes


def _play_via_uia(nodes: list[Any]) -> bool:
    for ctrl in nodes:
        try:
            name = (ctrl.window_text() or "").strip().lower()
        except Exception:
            continue
        if name in {"play", "play video", "play clip"} or name.startswith("play "):
            try:
                ctrl.click_input()
                say(f"Clicked UIA play control: {name}")
                return True
            except Exception:
                logger.debug("UIA play click failed", exc_info=True)
    return False


def _type_caption(hwnd: int, nodes: list[Any], original: str, rewritten: str) -> bool:
    snippet = (original or "").strip()[:40]
    _focus(hwnd)
    time.sleep(0.2)
    clicked = False
    if snippet:
        for ctrl in nodes:
            try:
                name = ctrl.window_text() or ""
            except Exception:
                continue
            if snippet.lower() in name.lower():
                try:
                    ctrl.click_input()
                    clicked = True
                    break
                except Exception:
                    continue
    if not clicked:
        return False
    time.sleep(0.15)
    _send_ctrl_a()
    time.sleep(0.05)
    _send_unicode(rewritten)
    time.sleep(0.1)
    return True


def _send_ctrl_a() -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(0x11, 0, 0, 0)  # VK_CONTROL
    user32.keybd_event(0x41, 0, 0, 0)  # A
    user32.keybd_event(0x41, 0, 2, 0)
    user32.keybd_event(0x11, 0, 2, 0)


def _send_unicode(text: str) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    for ch in text:
        if ch == "\n":
            user32.keybd_event(0x0D, 0, 0, 0)
            user32.keybd_event(0x0D, 0, 2, 0)
            continue
        scanned = user32.VkKeyScanW(ord(ch))
        if scanned == -1:
            continue
        vk_code = scanned & 0xFF
        shift = scanned & 0x100
        if shift:
            user32.keybd_event(0x10, 0, 0, 0)
        user32.keybd_event(vk_code, 0, 0, 0)
        user32.keybd_event(vk_code, 0, 2, 0)
        if shift:
            user32.keybd_event(0x10, 0, 2, 0)


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
    return "\n".join(chunk for chunk in chunks if chunk)


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def _capture_window_bmp(hwnd: int, dest) -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes
    from pathlib import Path

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    left, top, width, height = _window_rect(hwnd)
    if width < 2 or height < 2:
        return 0, 0
    hwnd_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    gdi32.SelectObject(mem_dc, bmp)
    if not user32.PrintWindow(hwnd, mem_dc, 2):
        user32.PrintWindow(hwnd, mem_dc, 0)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.biWidth = width
    info.biHeight = -height
    info.biPlanes = 1
    info.biBitCount = 32
    info.biCompression = 0
    row = ((width * 32 + 31) // 32) * 4
    buf = (ctypes.c_char * (row * height))()
    gdi32.GetDIBits(mem_dc, bmp, 0, height, buf, ctypes.byref(info), 0)
    pixel_bytes = buf.raw[: row * height]
    file_size = 14 + 40 + len(pixel_bytes)
    header = b"BM" + file_size.to_bytes(4, "little") + (0).to_bytes(4, "little") + (54).to_bytes(4, "little")
    dib = bytes(info) if ctypes.sizeof(info) == 40 else (
        (40).to_bytes(4, "little")
        + width.to_bytes(4, "little", signed=True)
        + (-height).to_bytes(4, "little", signed=True)
        + (1).to_bytes(2, "little")
        + (32).to_bytes(2, "little")
        + (0).to_bytes(4, "little")
        + (0).to_bytes(4, "little") * 5
    )
    dest.write_bytes(header + dib + pixel_bytes)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)
    return width, height


def _ocr_image(path) -> list[dict]:
    import json
    import subprocess
    from pathlib import Path

    script = Path(__file__).with_name("ocr_image.ps1")
    if not script.is_file():
        return []
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=40,
        )
    except Exception:
        logger.debug("OCR subprocess failed", exc_info=True)
        return []
    raw = (proc.stdout or "").strip()
    if not raw:
        logger.debug("OCR empty stderr=%s", proc.stderr)
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("OCR JSON parse failed: %s", raw[:200])
        return []
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _ocr_window(hwnd: int, tag: str) -> tuple[list[dict], int, int]:
    dest = config.DEBUG_CAPTURES / f"ix_{tag}.bmp"
    width, height = _capture_window_bmp(hwnd, dest)
    say(f"Captured IX window {width}x{height} -> {dest.name}")
    words = _ocr_image(dest)
    say(f"OCR words: {len(words)}")
    return words, width, height


def _apply_review_uses(hwnd: int, write: bool = True, max_clicks: int = 12) -> dict:
    """Click Grammar Use on the Review sidebar for red clips. Never Submit."""
    applied = 0
    last_words: list[dict] = []
    left, top, width, height = _window_rect(hwnd)
    guessed = False
    for step in range(max_clicks):
        words, img_w, img_h = _ocr_window(hwnd, f"review_{step}")
        last_words = words
        targets = find_review_use_clicks(words, img_w, img_h)
        if not targets:
            review = find_word_click(
                words, "review", img_w, img_h, x_min_frac=0.45, y_max_frac=0.30
            )
            if review and applied == 0 and step < 2:
                rx, ry = review
                say(f"Clicked Review tab at {left + rx},{top + ry}")
                if write:
                    _focus(hwnd)
                    _click_screen(left + rx, top + ry)
                    time.sleep(0.5)
                continue
            if applied == 0 and not guessed:
                ex, ey = estimated_use_point(width, height)
                say(f"No OCR Use; clicking estimated Review Use at {left + ex},{top + ey}")
                guessed = True
                if write:
                    _focus(hwnd)
                    _click_screen(left + ex, top + ey)
                    applied += 1
                    time.sleep(0.85)
                continue
            break
        cx, cy = targets[0]
        say(f"Review Use at {left + cx},{top + cy}")
        if not write:
            break
        _focus(hwnd)
        _click_screen(left + cx, top + cy)
        applied += 1
        time.sleep(0.85)
    return {"applied": applied, "text": ocr_text(last_words), "words": last_words}


def _fill_missing_and_reds(hwnd: int, write: bool = True) -> dict:
    """Click 'click to add text' and type fixes for red Quality Assistant clips."""
    left, top, _width, _height = _window_rect(hwnd)
    words, img_w, img_h = _ocr_window(hwnd, "missing")
    wrote = 0
    target = find_phrase_click(words, "click to add text", img_w, img_h)
    if not target:
        target = find_phrase_click(
            words, "empty clip", img_w, img_h, y_min_frac=0.12, y_max_frac=0.70
        )
    if target:
        say("Clicked missing clip (click to add text)")
        if write:
            _focus(hwnd)
            _click_screen(left + target[0], top + target[1])
            time.sleep(0.25)
            _send_ctrl_a()
            _send_unicode("Idle")
            wrote += 1
            say("Typed missing caption: Idle")
        time.sleep(0.4)
        words, img_w, img_h = _ocr_window(hwnd, "after_empty")

    for item in lint_clips([clip.to_dict() for clip in parse_clips_from_text(ocr_text(words))]):
        lint = item["lint"]
        if item.get("skip_edit") or not lint.changed:
            continue
        snippet = " ".join((lint.original or "").split()[:5])
        if not snippet or snippet.lower() in {"idle", "click to add text"}:
            continue
        hit = find_phrase_click(
            words, snippet, img_w, img_h, y_min_frac=0.48, y_max_frac=0.96
        )
        if not hit:
            continue
        say(f"Clicked red clip to edit: {snippet}")
        if not write:
            continue
        _focus(hwnd)
        _click_screen(left + hit[0], top + hit[1])
        time.sleep(0.2)
        _send_ctrl_a()
        _send_unicode(lint.rewritten)
        wrote += 1
        say(f"Typed caption fix: {lint.rewritten}")
        time.sleep(0.35)
        words, img_w, img_h = _ocr_window(hwnd, f"edit_{wrote}")
    return {"wrote": wrote, "text": ocr_text(words)}
