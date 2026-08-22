"""Drive the already-open IX window via the Windows desktop (no DevTools, no Local API)."""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from typing import Any

from caption_engine import clip_export_from_subgoals, lint_clips, subgoal_captions_from_names
from ego_task import parse_clips_from_text
from process_cdp import is_ix_chromium_exe, is_ix_launcher, is_stock_chrome_path
from review_ui import (
    EMPTY_CLIP_PHRASES,
    find_phrase_click,
    find_review_use_clicks,
    find_word_click,
    interesting_uia_names,
    is_clip_export_missing_error,
    is_clip_export_tab,
    is_empty_clip_label,
    is_grammar_row_label,
    is_idle_too_long_error,
    is_ignore_all_label,
    is_pause_control_label,
    is_pending_clip_label,
    is_play_control_label,
    is_quality_assistant_text,
    is_quality_empty_error,
    is_review_use_label,
    is_split_control_label,
    ocr_text,
    parse_grammar_clip_count,
    parse_watched_percent,
    review_work_remaining,
    should_skip_watch,
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
_OCR_BROKEN = False


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
    _ensure_dpi_aware()
    prev_a11y = _enable_chromium_a11y()
    try:
        hwnd, title = _pick_ix_window()
        say(f"Using IX window: {title or '(no title)'}")
        _focus(hwnd)
        time.sleep(1.0)

        uia_text, uia_nodes = _read_uia(hwnd)
        ocr_words, img_w, img_h = _ocr_window(hwnd, "start")
        page_text = "\n".join(part for part in (uia_text, ocr_text(ocr_words)) if part)
        watched_pct = parse_watched_percent(page_text)
        use_ready = bool(find_review_use_clicks(ocr_words, img_w, img_h)) or any(
            is_review_use_label(_uia_name(ctrl)) for ctrl in uia_nodes
        )
        empty_ready = any(p in page_text.lower() for p in EMPTY_CLIP_PHRASES) or any(
            is_empty_clip_label(_uia_name(ctrl)) for ctrl in uia_nodes
        )
        quality_ready = is_quality_assistant_text(page_text) or any(
            is_quality_empty_error(_uia_name(ctrl)) for ctrl in uia_nodes
        )
        if watched_pct is not None:
            say(f"Player shows Watched {watched_pct}%")
        if empty_ready:
            say("Empty timeline clip is on screen (click to add text).")
        if use_ready:
            say("Review Use is on screen.")
        if quality_ready:
            say("Quality Assistant reds are on screen.")

        already_playing = any(is_pause_control_label(_uia_name(ctrl)) for ctrl in uia_nodes)
        played = False
        remaining = 0.0
        if already_playing:
            say("Video is already playing (Pause is on screen).")
            played = True
        else:
            played = _play_via_uia(uia_nodes)
            if not played:
                played = _play_video(hwnd)
            say(
                "Watch the IX window: Play was clicked and the video should be playing now."
                if played
                else "Sent play input; check the IX window."
            )

        skip_full_watch = should_skip_watch(
            watched_pct, use_ready=use_ready, quality_ready=quality_ready
        )
        if skip_full_watch:
            say("Watched / Review already on screen, so not waiting another 90s after Play.")
            time.sleep(4.0)
        else:
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

        review = {"applied": 0, "text": page_text}
        filled = {"wrote": 0, "text": page_text}
        idle_rounds = 0
        for pass_i in range(8):
            say(f"Review pass {pass_i + 1}/8")
            used = _apply_review_uses(hwnd, write=write)
            missing = _fill_missing_and_reds(hwnd, write=write)
            exported = _fill_clip_export(hwnd, write=write)
            split = _split_long_idle(hwnd, write=write)
            review["applied"] += int(used["applied"])
            if used.get("text"):
                review["text"] = used["text"]
            filled["wrote"] += int(missing["wrote"]) + int(exported["wrote"]) + int(split["wrote"])
            if missing.get("text"):
                filled["text"] = missing["text"]
            say(
                f"Pass {pass_i + 1}: Use {used['applied']}, filled {missing['wrote']}, "
                f"clip-export {exported['wrote']}, idle-split {split['wrote']}"
            )
            body_now = "\n".join(
                part
                for part in (missing.get("text"), used.get("text"), exported.get("text"), page_text)
                if part
            )
            if used["applied"] + missing["wrote"] + exported["wrote"] + split["wrote"] == 0:
                idle_rounds += 1
                if not review_work_remaining(body_now):
                    say("No more Review / Quality Assistant work on screen.")
                    break
                if idle_rounds >= 2:
                    say("Stopped after two passes with no new Use/fill. Remaining reds may need a Split control.")
                    break
                if not _advance_review_target(hwnd):
                    say("Grammar/Quality work remains but no next clip control was found.")
                    break
                time.sleep(0.6)
            else:
                idle_rounds = 0

        say(f"Clicked Review Use {review['applied']} time(s)")
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
            "quality_assistant": bool(
                review["applied"] > 0 or filled["wrote"] > 0 or quality_ready
            ),
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


def _double_click_screen(x: int, y: int) -> None:
    _click_screen(x, y)
    time.sleep(0.08)
    _click_screen(x, y)


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


def _ensure_dpi_aware() -> None:
    """Match GetWindowRect to on-screen pixels so OCR clicks land on Use / clips."""
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            logger.debug("DPI awareness not set", exc_info=True)


def _restore_chromium_a11y(previous: int) -> None:
    import ctypes

    try:
        ctypes.windll.user32.SystemParametersInfoW(0x0047, int(previous), None, 0)
    except Exception:
        logger.debug("Could not restore screen-reader flag", exc_info=True)


def _uia_name(ctrl: Any) -> str:
    for getter in (
        lambda: ctrl.window_text(),
        lambda: ctrl.element_info.name,
        lambda: getattr(ctrl.element_info, "rich_text", None),
        lambda: getattr(ctrl.element_info, "automation_id", None),
        lambda: getattr(ctrl.element_info, "legacy_name", None),
    ):
        try:
            value = (getter() or "").strip()
        except Exception:
            continue
        if value:
            return str(value)
    return ""


def _ctrl_center(ctrl: Any) -> tuple[int, int] | None:
    try:
        rect = ctrl.rectangle()
        return (int(rect.left + rect.right) // 2, int(rect.top + rect.bottom) // 2)
    except Exception:
        return None


def _uia_click(ctrl: Any) -> bool:
    for action in (
        lambda: ctrl.click_input(),
        lambda: ctrl.invoke(),
        lambda: ctrl.click(),
    ):
        try:
            action()
            return True
        except Exception:
            continue
    center = _ctrl_center(ctrl)
    if center:
        _click_screen(center[0], center[1])
        return True
    return False


def _iter_uia_controls(target: Any, limit: int = 6000):
    try:
        for i, ctrl in enumerate(target.descendants()):
            if i >= limit:
                break
            yield ctrl
    except Exception:
        return


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
            say("UIA: SensorFusionLab window handle not found")
            return "", []
        for ctrl in _iter_uia_controls(target):
            nodes.append(ctrl)
            name = _uia_name(ctrl)
            if name:
                texts.append(name)
    except Exception as exc:
        say(f"UIA read failed: {exc}")
        logger.debug("UIA read skipped", exc_info=True)
    named = [t for t in texts if t]
    say(f"UIA named controls: {len(named)}")
    preview = interesting_uia_names(named)
    if preview:
        say("UIA names: " + " | ".join(preview))
    try:
        dest = config.DEBUG_CAPTURES / "uia_names.txt"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(named), encoding="utf-8")
    except Exception:
        logger.debug("Could not write uia_names.txt", exc_info=True)
    return "\n".join(texts), nodes


def _play_via_uia(nodes: list[Any]) -> bool:
    if any(is_pause_control_label(_uia_name(ctrl)) for ctrl in nodes):
        say("Pause control is visible; leaving the video playing.")
        return True
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if not is_play_control_label(name):
            continue
        try:
            if _uia_click(ctrl):
                say(f"Clicked UIA play control: {name}")
                return True
        except Exception:
            logger.debug("UIA play click failed", exc_info=True)
    return False


def _click_uia_use(hwnd: int, nodes: list[Any]) -> bool:
    """Click Grammar Use in the right Review pane. Never Submit."""
    _left, _top, width, _height = _window_rect(hwnd)
    for ctrl in nodes:
        if not is_review_use_label(_uia_name(ctrl)):
            continue
        center = _ctrl_center(ctrl)
        if center and center[0] < _left + int(width * 0.48):
            continue
        if _uia_click(ctrl):
            say(f"Clicked UIA Review Use at {center}")
            return True
    return False


def _click_uia_empty_clip(nodes: list[Any]) -> bool:
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if not is_empty_clip_label(name):
            continue
        if _uia_click(ctrl):
            say(f"Clicked UIA empty clip: {name}")
            time.sleep(0.08)
            _uia_click(ctrl)
            return True
    return False


def _click_uia_quality_empty(nodes: list[Any]) -> bool:
    """Click the Quality Assistant row that points at a clip with no text."""
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if not is_quality_empty_error(name):
            continue
        if _uia_click(ctrl):
            say(f"Clicked Quality Assistant empty-clip error: {name[:80]}")
            return True
    return False


def _click_control_left(ctrl: Any, frac: float = 0.18) -> bool:
    """Click the left side of a control so Grammar is hit, not Ignore all."""
    try:
        rect = ctrl.rectangle()
        x = int(rect.left + max(rect.right - rect.left, 1) * frac)
        y = int((rect.top + rect.bottom) / 2)
    except Exception:
        return False
    _click_screen(x, y)
    return True


def _advance_review_target(hwnd: int, nodes: list[Any] | None = None) -> bool:
    """Select the next Grammar/pending clip so Use reappears. Never Ignore all / Submit."""
    if nodes is None:
        _text, nodes = _read_uia(hwnd)
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if is_ignore_all_label(name):
            continue
        if not is_grammar_row_label(name):
            continue
        if _click_control_left(ctrl):
            say(f"Clicked Grammar row (left side, not Ignore all): {name[:80]}")
            return True
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if not is_pending_clip_label(name):
            continue
        if _uia_click(ctrl):
            say(f"Opened pending timeline clip: {name}")
            return True
    for ctrl in nodes:
        name = _uia_name(ctrl)
        if is_ignore_all_label(name) or is_review_use_label(name):
            continue
        if is_idle_too_long_error(name) or is_clip_export_missing_error(name):
            continue
        if is_quality_empty_error(name):
            continue
        lowered = name.casefold()
        if not lowered.startswith("error"):
            continue
        if _uia_click(ctrl):
            say(f"Opened Quality Assistant clip: {name[:80]}")
            return True
    return False


def _fill_clip_export(hwnd: int, write: bool = True) -> dict:
    """Fill the Clip Export card. Never Submit. Never type Idle here."""
    uia_text, nodes = _read_uia(hwnd)
    names = [line for line in (uia_text or "").splitlines() if line.strip()]
    if not any(is_clip_export_missing_error(n) for n in names) and not is_clip_export_missing_error(uia_text):
        return {"wrote": 0, "text": uia_text}
    for ctrl in nodes:
        if is_clip_export_tab(_uia_name(ctrl)):
            _uia_click(ctrl)
            say(f"Clicked Clip Export tab: {_uia_name(ctrl)}")
            time.sleep(0.4)
            uia_text, nodes = _read_uia(hwnd)
            break
    for ctrl in nodes:
        if is_clip_export_missing_error(_uia_name(ctrl)):
            _uia_click(ctrl)
            say("Clicked Quality Assistant Clip Export error")
            time.sleep(0.45)
            uia_text, nodes = _read_uia(hwnd)
            break
    clicked = _click_uia_empty_clip(nodes)
    if not clicked and not _OCR_BROKEN:
        words, img_w, img_h = _ocr_window(hwnd, "clip_export")
        left, top, _w, _h = _window_rect(hwnd)
        target = find_phrase_click(words, "click to add text", img_w, img_h)
        if target and write:
            _focus(hwnd)
            _double_click_screen(left + target[0], top + target[1])
            clicked = True
    if not clicked:
        say("Clip Export still empty but no editable field was found.")
        return {"wrote": 0, "text": uia_text}
    if not write:
        return {"wrote": 0, "text": uia_text}
    names = [line for line in (uia_text or "").splitlines() if line.strip()]
    text = clip_export_from_subgoals(subgoal_captions_from_names(names))
    time.sleep(0.2)
    _type_into_focused(text)
    say(f"Typed Clip Export: {text}")
    time.sleep(0.4)
    return {"wrote": 1, "text": text}


def _split_long_idle(hwnd: int, write: bool = True) -> dict:
    """Select a >5s Idle clip and click Split if the control exists."""
    uia_text, nodes = _read_uia(hwnd)
    target = None
    for ctrl in nodes:
        if is_idle_too_long_error(_uia_name(ctrl)):
            target = ctrl
            break
    if target is None:
        return {"wrote": 0, "text": uia_text}
    if write:
        _uia_click(target)
        say("Clicked Quality Assistant idle-too-long error")
        time.sleep(0.45)
        uia_text, nodes = _read_uia(hwnd)
    for ctrl in nodes:
        if is_split_control_label(_uia_name(ctrl)):
            if write and _uia_click(ctrl):
                say(f"Clicked split control: {_uia_name(ctrl)}")
                time.sleep(0.4)
                return {"wrote": 1, "text": uia_text}
    say("Idle clip is over 5s; no Split control in the accessibility tree.")
    return {"wrote": 0, "text": uia_text}


def _type_caption(hwnd: int, nodes: list[Any], original: str, rewritten: str) -> bool:
    snippet = (original or "").strip()[:40]
    _focus(hwnd)
    time.sleep(0.2)
    clicked = False
    if snippet:
        for ctrl in nodes:
            name = _uia_name(ctrl)
            if snippet.lower() in name.lower():
                if _uia_click(ctrl):
                    clicked = True
                    break
    if not clicked:
        return False
    _type_into_focused(rewritten)
    return True


def _send_ctrl_a() -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(0x11, 0, 0, 0)  # VK_CONTROL
    user32.keybd_event(0x41, 0, 0, 0)  # A
    user32.keybd_event(0x41, 0, 2, 0)
    user32.keybd_event(0x11, 0, 2, 0)


def _send_unicode(text: str) -> None:
    """Type with Unicode SendInput so Idle is not dropped on non-US layouts."""
    import ctypes

    if not text:
        return
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_KEYUP = 0x0002
    INPUT_KEYBOARD = 1

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_uint),
            ("time", ctypes.c_uint),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_uint),
            ("ki", KEYBDINPUT),
            ("padding", ctypes.c_ubyte * 8),
        ]

    extra = ctypes.sizeof(INPUT)
    for ch in text:
        if ch == "\n":
            ctypes.windll.user32.keybd_event(0x0D, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x0D, 0, 2, 0)
            continue
        code = ord(ch)
        down = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, None))
        up = INPUT(
            type=INPUT_KEYBOARD,
            ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None),
        )
        ctypes.windll.user32.SendInput(1, ctypes.byref(down), extra)
        ctypes.windll.user32.SendInput(1, ctypes.byref(up), extra)


def _type_into_focused(text: str) -> None:
    time.sleep(0.15)
    _send_ctrl_a()
    time.sleep(0.05)
    _send_unicode(text)


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
    """Grab pixels on screen. Chromium PrintWindow is often a blank bitmap."""
    from pathlib import Path

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    left, top, width, height = _window_rect(hwnd)
    if width < 2 or height < 2:
        return 0, 0
    bmp = dest.with_suffix(".bmp")
    png = dest.with_suffix(".png")
    _capture_screen_bitblt(left, top, width, height, bmp)
    _capture_screen_pillow(left, top, width, height, png)
    size = 0
    for path in (bmp, png):
        try:
            if path.is_file():
                size = max(size, path.stat().st_size)
        except OSError:
            continue
    say(f"Capture file ~{size} bytes ({bmp.name}/{png.name})")
    return width, height


def _capture_screen_pillow(left: int, top: int, width: int, height: int, dest) -> bool:
    try:
        from PIL import ImageGrab

        image = ImageGrab.grab(bbox=(left, top, left + width, top + height), all_screens=True)
        image.save(dest)
        return True
    except Exception as exc:
        say(f"Screen grab (Pillow) failed: {exc}")
        return False


def _capture_screen_bitblt(left: int, top: int, width: int, height: int, dest) -> bool:
    """BitBlt the desktop DC. This sees Chromium; PrintWindow often does not."""
    import ctypes
    from ctypes import wintypes
    from pathlib import Path

    dest = Path(dest)
    try:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        hdc_screen = user32.GetDC(0)
        if not hdc_screen:
            return False
        mem_dc = gdi32.CreateCompatibleDC(hdc_screen)
        bmp = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
        gdi32.SelectObject(mem_dc, bmp)
        SRCCOPY = 0x00CC0020
        ok = gdi32.BitBlt(mem_dc, 0, 0, width, height, hdc_screen, left, top, SRCCOPY)
        if not ok:
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(0, hdc_screen)
            return False

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
        header = (
            b"BM"
            + file_size.to_bytes(4, "little")
            + (0).to_bytes(4, "little")
            + (54).to_bytes(4, "little")
        )
        dib = (
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
        user32.ReleaseDC(0, hdc_screen)
        return dest.is_file() and dest.stat().st_size > 54
    except Exception as exc:
        say(f"Screen grab (BitBlt) failed: {exc}")
        return False


def _ocr_image(path) -> list[dict]:
    import json
    import subprocess
    from pathlib import Path

    global _OCR_BROKEN
    if _OCR_BROKEN:
        return []
    script = Path(__file__).with_name("ocr_image.ps1")
    path = Path(path)
    if not script.is_file() or not path.is_file():
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
    err = (proc.stderr or "").strip()
    json_path = Path(raw.splitlines()[-1].strip()) if raw else None
    if json_path and json_path.suffix.lower() == ".json" and json_path.is_file():
        raw = json_path.read_text(encoding="utf-8-sig")
    elif proc.returncode not in (0, None) or not raw:
        say(f"OCR empty (exit {proc.returncode}). {err[:400]}")
        if "MakeGenericMethod" in err or "generic parameter" in err.lower():
            _OCR_BROKEN = True
            say("OCR script failed; continuing with UIA only.")
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]")
        if start >= 0 and end > start:
            try:
                payload = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                say(f"OCR JSON parse failed: {raw[:240]}")
                return []
        else:
            say(f"OCR JSON parse failed: {raw[:240]}")
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
    if not words:
        png = dest.with_suffix(".png")
        if png.is_file():
            words = _ocr_image(png)
    say(f"OCR words: {len(words)}")
    if words:
        preview = " ".join(str(w.get("text") or "") for w in words[:24])
        say(f"OCR preview: {preview[:220]}")
    return words, width, height


def _apply_review_uses(hwnd: int, write: bool = True, max_clicks: int = 12) -> dict:
    """Click Grammar Use on the Review sidebar for red clips. Never Submit."""
    applied = 0
    stalled = 0
    last_words: list[dict] = []
    last_text = ""
    left, top, width, height = _window_rect(hwnd)
    for step in range(max_clicks):
        uia_text, nodes = _read_uia(hwnd)
        last_text = uia_text
        grammar_n = parse_grammar_clip_count(uia_text)
        if grammar_n:
            say(f"Grammar still has {grammar_n} clip(s)")
        if write and _click_uia_use(hwnd, nodes):
            applied += 1
            stalled = 0
            time.sleep(0.85)
            continue
        if grammar_n and stalled < 5 and _advance_review_target(hwnd, nodes):
            stalled += 1
            time.sleep(0.55)
            continue
        if _OCR_BROKEN:
            say("No Review Use control found (OCR/UIA). Not guessing a click.")
            break
        words, img_w, img_h = _ocr_window(hwnd, f"review_{step}")
        last_words = words
        last_text = "\n".join(part for part in (uia_text, ocr_text(words)) if part)
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
            say("No Review Use control found (OCR/UIA). Not guessing a click.")
            break
        cx, cy = targets[0]
        say(f"Review Use at {left + cx},{top + cy}")
        if not write:
            break
        _focus(hwnd)
        _click_screen(left + cx, top + cy)
        applied += 1
        stalled = 0
        time.sleep(0.85)
    return {"applied": applied, "text": last_text or ocr_text(last_words), "words": last_words}


def _fill_missing_and_reds(hwnd: int, write: bool = True) -> dict:
    """Click 'click to add text' and type fixes for red Quality Assistant clips."""
    left, top, _width, _height = _window_rect(hwnd)
    wrote = 0
    words: list[dict] = []
    img_w = img_h = 1
    uia_text = ""
    nodes: list[Any] = []

    for attempt in range(8):
        uia_text, nodes = _read_uia(hwnd)
        clicked_empty = _click_uia_empty_clip(nodes)
        if not clicked_empty:
            clicked_empty = _click_uia_quality_empty(nodes)
            if clicked_empty:
                time.sleep(0.35)
                uia_text, nodes = _read_uia(hwnd)
                clicked_empty = _click_uia_empty_clip(nodes) or clicked_empty
        if not clicked_empty:
            if _OCR_BROKEN:
                break
            words, img_w, img_h = _ocr_window(hwnd, f"missing_{attempt}")
            target = None
            for phrase in EMPTY_CLIP_PHRASES:
                target = find_phrase_click(words, phrase, img_w, img_h)
                if target:
                    break
            if not target:
                target = find_phrase_click(
                    words, "empty clip", img_w, img_h, y_min_frac=0.12, y_max_frac=0.70
                )
            if target:
                say("Clicked missing clip (click to add text)")
                if write:
                    _focus(hwnd)
                    _double_click_screen(left + target[0], top + target[1])
                clicked_empty = True
        if not clicked_empty:
            break
        if write:
            time.sleep(0.25)
            _type_into_focused("Idle")
            wrote += 1
            say("Typed missing caption: Idle")
            time.sleep(0.45)

    if not words:
        if not _OCR_BROKEN:
            words, img_w, img_h = _ocr_window(hwnd, "after_empty")
        uia_text, nodes = _read_uia(hwnd)

    body = "\n".join(part for part in (uia_text, ocr_text(words)) if part)
    for item in lint_clips([clip.to_dict() for clip in parse_clips_from_text(body)]):
        lint = item["lint"]
        if item.get("skip_edit") or not lint.changed:
            continue
        snippet = " ".join((lint.original or "").split()[:5])
        if not snippet or snippet.lower() in {"idle", "click to add text"}:
            continue
        hit = None
        for ctrl in nodes:
            name = _uia_name(ctrl)
            if snippet.lower() in name.lower():
                center = _ctrl_center(ctrl)
                if center:
                    hit = (center[0] - left, center[1] - top)
                    try:
                        if write and _uia_click(ctrl):
                            hit = "uia"
                    except Exception:
                        hit = (center[0] - left, center[1] - top)
                break
        if hit is None:
            hit = find_phrase_click(
                words, snippet, img_w, img_h, y_min_frac=0.48, y_max_frac=0.96
            )
        if not hit:
            continue
        say(f"Clicked red clip to edit: {snippet}")
        if not write:
            continue
        if hit != "uia":
            _focus(hwnd)
            _click_screen(left + hit[0], top + hit[1])
        time.sleep(0.2)
        _type_into_focused(lint.rewritten)
        wrote += 1
        say(f"Typed caption fix: {lint.rewritten}")
        time.sleep(0.35)
        uia_text, nodes = _read_uia(hwnd)
        words, img_w, img_h = _ocr_window(hwnd, f"edit_{wrote}")
        body = "\n".join(part for part in (uia_text, ocr_text(words)) if part)
    return {"wrote": wrote, "text": body}
