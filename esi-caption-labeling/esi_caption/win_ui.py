"""Drive the already-open IX or MoreLogin Chromium via the Windows desktop."""

from __future__ import annotations

import logging
import sys
import time

from .browsers import is_family_launcher, score_task_window
from .captions import normalize_caption
from .guidelines import HAND_BUTTONS, is_forbidden_click
from .keys import tap_vk, type_text
from .planner import EpisodePlan, L2Span, L3Span, parse_clock_blob, seconds_to_timestamp
from .scenes import parse_video_id

logger = logging.getLogger("esi.win_ui")
CHROME_CLASS = "Chrome_WidgetWin_1"


def say(msg: str) -> None:
    print(msg, flush=True)
    logger.info(msg)


def _exe_for_hwnd(hwnd: int) -> str:
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(512)
            size = wintypes.DWORD(512)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ""
    return ""


def enumerate_windows() -> list[dict]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[dict] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buf, length + 1)
        class_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buf, 256)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        title = title_buf.value or ""
        class_name = class_buf.value or ""
        exe_path = _exe_for_hwnd(int(hwnd))
        found.append(
            {
                "hwnd": int(hwnd),
                "title": title,
                "class_name": class_name,
                "exe_path": exe_path,
                "width": width,
                "height": height,
                "left": int(rect.left),
                "top": int(rect.top),
            }
        )
        return True

    user32.EnumWindows(_enum, 0)
    return found


def select_task_window(family: str) -> dict | None:
    scored: list[tuple[int, dict]] = []
    for window in enumerate_windows():
        points = score_task_window(
            window.get("title") or "",
            window.get("class_name") or "",
            window.get("exe_path") or "",
            family=family,
        )
        title = window.get("title") or "(no title)"
        if is_family_launcher(family, window.get("title"), window.get("exe_path")):
            say(f"Skipping launcher window: {title}")
            continue
        if points <= 0:
            if window.get("width", 0) >= 400:
                say(f"Skipping non-task window: {title}")
            continue
        say(f"Saw {family} window ({window.get('width')}x{window.get('height')}): {title}")
        scored.append((points, window))
    if not scored:
        return None
    scored.sort(key=lambda row: row[0], reverse=True)
    chosen = scored[0][1]
    say(f"Using {family} window: {chosen.get('title') or '(no title)'}")
    return chosen


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return int(rect.left), int(rect.top), int(rect.right - rect.left), int(rect.bottom - rect.top)


def _focus(hwnd: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.15)


def _click_screen(x: int, y: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.04)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.04)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def read_uia_names(hwnd: int) -> list[str]:
    try:
        from pywinauto import Desktop
    except Exception as exc:
        say(f"[UIA] pywinauto missing: {exc}")
        return []
    names: list[str] = []
    try:
        desktop = Desktop(backend="uia")
        win = desktop.window(handle=hwnd)
        wrapper = win.wrapper_object()
        for ctrl in wrapper.descendants():
            try:
                name = (ctrl.element_info.name or "").strip()
            except Exception:
                continue
            if name:
                names.append(name)
            if len(names) >= 1600:
                break
    except Exception as exc:
        say(f"[UIA] read failed: {exc}")
    return names


def read_uia_infos(hwnd: int) -> list[dict]:
    try:
        from pywinauto import Desktop
    except Exception:
        return []
    infos: list[dict] = []
    try:
        desktop = Desktop(backend="uia")
        win = desktop.window(handle=hwnd)
        wrapper = win.wrapper_object()
        for ctrl in wrapper.descendants():
            try:
                info = ctrl.element_info
                name = (info.name or "").strip()
                rect = info.rectangle
            except Exception:
                continue
            if not name:
                continue
            infos.append(
                {
                    "name": name,
                    "left": int(getattr(rect, "left", 0) or 0),
                    "top": int(getattr(rect, "top", 0) or 0),
                    "width": int((getattr(rect, "right", 0) or 0) - (getattr(rect, "left", 0) or 0)),
                    "height": int((getattr(rect, "bottom", 0) or 0) - (getattr(rect, "top", 0) or 0)),
                    "ctrl": ctrl,
                }
            )
            if len(infos) >= 1600:
                break
    except Exception as exc:
        say(f"[UIA] tree failed: {exc}")
    return infos


def pick_named(infos: list[dict], *needles: str, leftmost: bool = True) -> dict | None:
    hits: list[dict] = []
    for row in infos:
        name = str(row.get("name") or "").strip().casefold()
        if any(needle.casefold() in name for needle in needles):
            if is_forbidden_click(name):
                continue
            hits.append(row)
    if not hits:
        return None
    hits.sort(key=lambda row: int(row.get("left") or 0), reverse=not leftmost)
    return hits[0]


def click_named(hwnd: int, infos: list[dict], *needles: str, leftmost: bool = True) -> bool:
    chosen = pick_named(infos, *needles, leftmost=leftmost)
    if chosen is None:
        return False
    name = str(chosen.get("name") or "")
    if is_forbidden_click(name):
        say(f"Refusing to click: {name}")
        return False
    x = int(chosen.get("left") or 0) + max(int(chosen.get("width") or 0), 8) // 2
    y = int(chosen.get("top") or 0) + max(int(chosen.get("height") or 0), 8) // 2
    _focus(hwnd)
    _click_screen(x, y)
    return True


def snapshot_text(hwnd: int) -> str:
    names = read_uia_names(hwnd)
    return " | ".join(names)


def page_is_task(blob: str) -> bool:
    lowered = (blob or "").casefold()
    return "hierarchical egocentric" in lowered or "video caption labeling" in lowered or "multimango" in lowered


def submit_blocked(blob: str) -> bool:
    lowered = (blob or "").casefold()
    return "issue(s) to fix" in lowered or "issues to fix" in lowered or "cannot submit" in lowered


def click_play(hwnd: int, infos: list[dict]) -> bool:
    if click_named(hwnd, infos, "pause"):
        say("Video is already playing (Pause is on screen).")
        return True
    if click_named(hwnd, infos, "play"):
        say("Clicked Play at 1x.")
        return True
    left, top, width, height = _window_rect(hwnd)
    _click_screen(left + int(width * 0.38), top + int(height * 0.28))
    time.sleep(0.2)
    tap_vk(0x20)  # Space
    say("Clicked the video center / Space to play.")
    return True


def click_speed_1x(hwnd: int, infos: list[dict]) -> None:
    click_named(hwnd, infos, "1x")


def add_l3(hwnd: int) -> None:
    _focus(hwnd)
    tap_vk(0x33)  # 3
    time.sleep(0.25)


def add_l2(hwnd: int) -> None:
    _focus(hwnd)
    tap_vk(0x32)  # 2
    time.sleep(0.25)


def click_timeline_fraction(hwnd: int, frac: float) -> None:
    left, top, width, height = _window_rect(hwnd)
    x = left + int(width * (0.08 + 0.62 * min(max(frac, 0.0), 1.0)))
    y = top + int(height * 0.62)
    _focus(hwnd)
    _click_screen(x, y)
    time.sleep(0.12)


def fill_focused(text: str) -> None:
    for _ in range(18):
        tap_vk(0x08)
        time.sleep(0.015)
    type_text(text)


def _set_times(hwnd: int, infos: list[dict], start_s: float, end_s: float) -> None:
    start = seconds_to_timestamp(start_s)
    end = seconds_to_timestamp(end_s)
    # Cards show start/end as 0:00.0 style texts. Click the first two clock-like names in the active card.
    clocks = [
        row
        for row in infos
        if str(row.get("name") or "").strip().count(":") == 1
        and any(ch.isdigit() for ch in str(row.get("name") or ""))
        and int(row.get("width") or 0) < 160
    ]
    clocks.sort(key=lambda row: (int(row.get("top") or 0), int(row.get("left") or 0)))
    if len(clocks) >= 2:
        for row, value in ((clocks[0], start), (clocks[1], end)):
            x = int(row.get("left") or 0) + 12
            y = int(row.get("top") or 0) + 8
            _click_screen(x, y)
            time.sleep(0.1)
            fill_focused(value)
            tap_vk(0x09)  # Tab, never Enter
            time.sleep(0.1)


def fill_l3(hwnd: int, span: L3Span, duration: float) -> None:
    infos = read_uia_infos(hwnd)
    click_timeline_fraction(hwnd, span.start_s / max(duration, 0.1))
    add_l3(hwnd)
    time.sleep(0.3)
    infos = read_uia_infos(hwnd)
    _set_times(hwnd, infos, span.start_s, span.end_s)
    infos = read_uia_infos(hwnd)
    if span.idle:
        click_named(hwnd, infos, "idle — nothing", "idle")
        say(f"[L3] Idle {seconds_to_timestamp(span.start_s)}–{seconds_to_timestamp(span.end_s)}")
        return
    button = HAND_BUTTONS.get(span.hand, "Right hand only")
    if not click_named(hwnd, infos, button):
        click_named(hwnd, infos, "Right hand only")
    time.sleep(0.2)
    infos = read_uia_infos(hwnd)
    if click_named(hwnd, infos, "action"):
        time.sleep(0.15)
        type_text(span.action)
        time.sleep(0.1)
        infos = read_uia_infos(hwnd)
        click_named(hwnd, infos, span.action)
        time.sleep(0.1)
    if click_named(hwnd, infos, "object"):
        time.sleep(0.1)
        fill_focused(span.obj if not span.tool else f"{span.obj} with {span.tool}")
        tap_vk(0x09)
    if span.target:
        if click_named(hwnd, infos, "target location", "target"):
            fill_focused(span.target)
            tap_vk(0x09)
    else:
        click_named(
            hwnd,
            infos,
            "no placement destination",
            "object not moving",
            "no object",
        )
    infos = read_uia_infos(hwnd)
    if click_named(hwnd, infos, "generate with ai"):
        say("[L3] Clicked Generate with AI")
        time.sleep(1.2)
    if span.caption:
        infos = read_uia_infos(hwnd)
        if click_named(hwnd, infos, "caption"):
            fill_focused(normalize_caption(span.caption))
    say(f"[L3] {span.caption or 'idle'}")


def fill_l2(hwnd: int, span: L2Span, duration: float) -> None:
    infos = read_uia_infos(hwnd)
    click_timeline_fraction(hwnd, span.start_s / max(duration, 0.1))
    add_l2(hwnd)
    time.sleep(0.3)
    infos = read_uia_infos(hwnd)
    _set_times(hwnd, infos, span.start_s, span.end_s)
    if span.idle:
        say(f"[L2] Idle inherited {seconds_to_timestamp(span.start_s)}–{seconds_to_timestamp(span.end_s)}")
        return
    infos = read_uia_infos(hwnd)
    click_named(hwnd, infos, "success")
    if not click_named(hwnd, infos, "0") and span.retries == 0:
        pass
    if span.retries:
        click_named(hwnd, infos, str(span.retries))
    infos = read_uia_infos(hwnd)
    if click_named(hwnd, infos, "generate with ai"):
        say("[L2] Clicked Generate with AI")
        time.sleep(1.2)
    if span.caption and click_named(hwnd, infos, "caption"):
        fill_focused(normalize_caption(span.caption))
    say(f"[L2] {span.caption}")


def fill_l1(hwnd: int, plan: EpisodePlan) -> None:
    infos = read_uia_infos(hwnd)
    if click_named(hwnd, infos, "select where it takes place", "environment", "choose environment"):
        time.sleep(0.2)
        infos = read_uia_infos(hwnd)
        if not click_named(hwnd, infos, plan.environment):
            click_named(hwnd, infos, "Home")
        say(f"[L1] Environment: {plan.environment}")
    infos = read_uia_infos(hwnd)
    if click_named(hwnd, infos, "generate with ai"):
        say("[L1] Clicked Generate with AI")
        time.sleep(1.4)
    infos = read_uia_infos(hwnd)
    if click_named(hwnd, infos, "l1 episode caption", "describe the whole episode", "episode caption"):
        fill_focused(plan.episode_caption)
    say(f"[L1] {plan.episode_caption}")


def maybe_submit(hwnd: int, *, submit: bool) -> bool:
    blob = snapshot_text(hwnd)
    if not submit:
        say("Submit skipped (--no-submit). Operator submits.")
        return False
    if submit_blocked(blob):
        say("Submit blocked: issues remain. Operator should review.")
        return False
    infos = read_uia_infos(hwnd)
    if click_named(hwnd, infos, "submit captions"):
        say("Clicked Submit Captions. Skip/Flag were not clicked.")
        return True
    say("Submit Captions button was not found.")
    return False


def watch_video(hwnd: int, duration_s: float) -> None:
    infos = read_uia_infos(hwnd)
    click_speed_1x(hwnd, infos)
    click_play(hwnd, infos)
    wait = min(max(duration_s + 2.0, 3.0), 180.0)
    say(f"Watching the clip at 1x for {wait:.0f}s (submit requires the video loaded/watched).")
    time.sleep(wait)


def drive_plan(hwnd: int, plan: EpisodePlan, *, submit: bool) -> dict:
    say(f"Plan: {len(plan.actions)} L3 actions, {len(plan.segments)} L2 segments, env={plan.environment}")
    for idx, action in enumerate(plan.actions, 1):
        say(f"[L3 {idx}/{len(plan.actions)}] filling...")
        fill_l3(hwnd, action, plan.duration_s)
    for idx, segment in enumerate(plan.segments, 1):
        say(f"[L2 {idx}/{len(plan.segments)}] filling...")
        fill_l2(hwnd, segment, plan.duration_s)
    fill_l1(hwnd, plan)
    submitted = maybe_submit(hwnd, submit=submit)
    return {"submitted": submitted, "l3": len(plan.actions), "l2": len(plan.segments)}


def run_desktop(family: str, *, submit: bool) -> dict:
    if sys.platform != "win32":
        raise RuntimeError("Desktop attach only runs on Windows.")
    chosen = select_task_window(family)
    if chosen is None:
        raise RuntimeError(
            f"No open {family} task window. Open the profile yourself, leave MultiMango caption labeling on screen."
        )
    hwnd = int(chosen["hwnd"])
    _focus(hwnd)
    blob = snapshot_text(hwnd)
    if not page_is_task(blob):
        say("Window attached; waiting for Hierarchical Egocentric Video Captioning to be on screen...")
        time.sleep(2)
        blob = snapshot_text(hwnd)
    video_id = parse_video_id(blob)
    clock = parse_clock_blob(blob)
    duration = clock[1] if clock else 73.5
    frames = clock[3] if clock else 0
    say(f"Video id: {video_id or 'unknown'}; duration {duration:.1f}s")
    watch_video(hwnd, min(duration, 90))
    from .planner import plan_episode
    from .scenes import pick_scene

    plan = plan_episode(duration_s=duration, frame_count=frames, video_blob=blob)
    plan.video_id = video_id
    plan.environment = pick_scene(blob).environment
    return drive_plan(hwnd, plan, submit=submit)
