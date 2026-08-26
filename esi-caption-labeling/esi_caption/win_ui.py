"""Drive the already-open IX or MoreLogin Chromium via the Windows desktop."""

from __future__ import annotations

import logging
import sys
import time

from .browsers import is_family_chromium, is_family_launcher, score_task_window
from .captions import normalize_caption
from .cards import empty_cards, parse_sidebar_cards, task_blob_hints
from .guidelines import HAND_BUTTONS, is_forbidden_click
from .keys import tap_vk, type_text
from .planner import EpisodePlan, L2Span, L3Span, parse_clock_blob, seconds_to_timestamp
from .scenes import parse_video_id, pick_scene

logger = logging.getLogger("esi.win_ui")
CHROME_CLASS = "Chrome_WidgetWin_1"
HAND_LABELS = (
    "left hand only",
    "right hand only",
    "no hand",
    "both hands same action",
    "both hands diff actions",
    "transfer between hands",
)


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
        found.append(
            {
                "hwnd": int(hwnd),
                "title": title_buf.value or "",
                "class_name": class_buf.value or "",
                "exe_path": _exe_for_hwnd(int(hwnd)),
                "width": int(rect.right - rect.left),
                "height": int(rect.bottom - rect.top),
                "left": int(rect.left),
                "top": int(rect.top),
            }
        )
        return True

    user32.EnumWindows(_enum, 0)
    return found


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return int(rect.left), int(rect.top), int(rect.right - rect.left), int(rect.bottom - rect.top)


def _focus(hwnd: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)


def _click_screen(x: int, y: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def read_uia_infos(hwnd: int) -> list[dict]:
    try:
        from pywinauto import Desktop
    except Exception as exc:
        say(f"[UIA] pywinauto missing: {exc}")
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
                    "control_type": str(getattr(info, "control_type", "") or ""),
                    "ctrl": ctrl,
                }
            )
            if len(infos) >= 1800:
                break
    except Exception as exc:
        say(f"[UIA] tree failed: {exc}")
    return infos


def read_uia_names(hwnd: int) -> list[str]:
    return [str(row.get("name") or "") for row in read_uia_infos(hwnd)]


def snapshot_text(hwnd: int) -> str:
    return " | ".join(read_uia_names(hwnd))


def page_is_task(blob: str) -> bool:
    lowered = (blob or "").casefold()
    return (
        "hierarchical egocentric" in lowered
        or "video caption labeling" in lowered
        or "multimango" in lowered
        or "action (empty)" in lowered
        or "generate with ai" in lowered
    )


def submit_blocked(blob: str) -> bool:
    lowered = (blob or "").casefold()
    return "issue(s) to fix" in lowered or "issues to fix" in lowered or "cannot submit" in lowered


def _sidebar(infos: list[dict], hwnd: int) -> list[dict]:
    left, _top, width, _height = _window_rect(hwnd)
    cut = left + int(width * 0.55)
    return [row for row in infos if int(row.get("left") or 0) >= cut]


def pick_named(
    infos: list[dict],
    *needles: str,
    exact: bool = False,
    contains: bool = True,
) -> dict | None:
    hits: list[dict] = []
    for row in infos:
        name = str(row.get("name") or "").strip()
        lowered = name.casefold()
        if is_forbidden_click(name):
            continue
        ok = False
        for needle in needles:
            key = needle.casefold()
            if exact and lowered == key:
                ok = True
            elif not exact and contains and key in lowered:
                ok = True
        if ok:
            hits.append(row)
    if not hits:
        return None
    hits.sort(key=lambda row: (int(row.get("top") or 0), int(row.get("left") or 0)))
    return hits[0]


def click_row(hwnd: int, row: dict | None) -> bool:
    if row is None:
        return False
    name = str(row.get("name") or "")
    if is_forbidden_click(name):
        say(f"Refusing to click: {name}")
        return False
    x = int(row.get("left") or 0) + max(int(row.get("width") or 0), 8) // 2
    y = int(row.get("top") or 0) + max(int(row.get("height") or 0), 8) // 2
    _focus(hwnd)
    _click_screen(x, y)
    return True


def click_named(hwnd: int, infos: list[dict], *needles: str, exact: bool = False) -> bool:
    return click_row(hwnd, pick_named(infos, *needles, exact=exact))


def select_task_window(family: str) -> dict | None:
    windows = enumerate_windows()
    large_family: list[dict] = []
    for window in windows:
        title = window.get("title") or "(no title)"
        exe = window.get("exe_path") or ""
        if is_family_launcher(family, window.get("title"), exe):
            say(f"Skipping launcher window: {title}")
            continue
        if not is_family_chromium(family, exe):
            if int(window.get("width") or 0) >= 400:
                say(f"Skipping non-task window: {title}")
            continue
        points = score_task_window(
            window.get("title") or "",
            window.get("class_name") or "",
            exe,
            family=family,
            width=int(window.get("width") or 0),
            height=int(window.get("height") or 0),
        )
        say(f"Saw {family} window ({window.get('width')}x{window.get('height')} score={points}): {title}")
        if int(window.get("width") or 0) >= 700 and int(window.get("height") or 0) >= 450 and points > 0:
            large_family.append(window)
        elif points > 0 and int(window.get("width") or 0) < 400:
            say(f"Ignoring tiny titled stub ({window.get('width')}x{window.get('height')}): {title}")

    probed: list[dict] = []
    for window in large_family:
        hwnd = int(window["hwnd"])
        _focus(hwnd)
        blob = snapshot_text(hwnd)
        named = [part for part in blob.split(" | ") if part]
        say(f"[Scan] {window.get('width')}x{window.get('height')} named controls={len(named)} title={window.get('title')!r}")
        if page_is_task(blob) or task_blob_hints(blob):
            probed.append(window)
            say(f"Task page found on {window.get('width')}x{window.get('height')}: {window.get('title')}")
    if probed:
        chosen = max(probed, key=lambda row: int(row.get("width") or 0) * int(row.get("height") or 0))
        say(f"Using {family} window: {chosen.get('title') or '(no title)'} ({chosen.get('width')}x{chosen.get('height')})")
        return chosen
    if large_family:
        chosen = max(large_family, key=lambda row: int(row.get("width") or 0) * int(row.get("height") or 0))
        say(f"Using largest {family} window (no task text yet): {chosen.get('title')}")
        return chosen
    return None


def click_play(hwnd: int, infos: list[dict]) -> bool:
    side = _sidebar(infos, hwnd)
    player = [row for row in infos if row not in side]
    if click_named(hwnd, player or infos, "pause", exact=True) or click_named(hwnd, infos, "Pause", exact=True):
        say("Pause is on screen.")
        return True
    if click_named(hwnd, player or infos, "play", exact=True) or click_named(hwnd, infos, "Play", exact=True):
        say("Clicked Play at 1x.")
        return True
    left, top, width, height = _window_rect(hwnd)
    _click_screen(left + int(width * 0.32), top + int(height * 0.22))
    time.sleep(0.15)
    tap_vk(0x20)
    say("Clicked the video pane / Space.")
    return True


def click_pause(hwnd: int) -> None:
    infos = read_uia_infos(hwnd)
    if not click_named(hwnd, infos, "Pause", exact=True):
        tap_vk(0x20)
    time.sleep(0.2)


def click_speed_1x(hwnd: int, infos: list[dict]) -> None:
    click_named(hwnd, infos, "1x", exact=True)


def click_timeline_fraction(hwnd: int, frac: float) -> None:
    left, top, width, height = _window_rect(hwnd)
    x = left + int(width * (0.06 + 0.46 * min(max(frac, 0.0), 1.0)))
    y = top + int(height * 0.56)
    _focus(hwnd)
    _click_screen(x, y)
    time.sleep(0.15)


def fill_focused(text: str) -> None:
    for _ in range(22):
        tap_vk(0x08)
        time.sleep(0.012)
    type_text(text)


def _click_add(hwnd: int, infos: list[dict], *, level: str) -> bool:
    side = _sidebar(infos, hwnd)
    adds = [
        row
        for row in side
        if str(row.get("name") or "").strip().casefold() in {"+ add", "add", "+add"}
        or str(row.get("name") or "").strip().casefold().endswith("add")
    ]
    adds.sort(key=lambda row: int(row.get("top") or 0))
    if not adds:
        return False
    chosen = adds[0] if level == "L3" else adds[-1]
    say(f"Clicking sidebar {level} + Add")
    return click_row(hwnd, chosen)


def _open_empty_card(hwnd: int, infos: list[dict], *, level: str) -> bool:
    side = _sidebar(infos, hwnd)
    names = [str(row.get("name") or "") for row in side] or [str(row.get("name") or "") for row in infos]
    cards = empty_cards(names, level)
    needle = "action (empty)" if level == "L3" else "result (empty)"
    row = pick_named(side or infos, needle, exact=True) or pick_named(side or infos, needle)
    if row is None and cards:
        row = pick_named(side or infos, cards[0]["id"], exact=True)
    if row is None:
        return False
    say(f"Opening empty {level} card {row.get('name')}")
    return click_row(hwnd, row)


def _hand_buttons_visible(infos: list[dict], hwnd: int) -> bool:
    side = _sidebar(infos, hwnd)
    blob = " ".join(str(row.get("name") or "").casefold() for row in (side or infos))
    return "left hand only" in blob and "right hand only" in blob


def _set_times(hwnd: int, infos: list[dict], start_s: float, end_s: float) -> None:
    start = seconds_to_timestamp(start_s)
    end = seconds_to_timestamp(end_s)
    side = _sidebar(infos, hwnd)
    clocks = [
        row
        for row in (side or infos)
        if str(row.get("name") or "").strip().count(":") == 1
        and any(ch.isdigit() for ch in str(row.get("name") or ""))
        and int(row.get("width") or 0) < 180
        and "frame" not in str(row.get("name") or "").casefold()
        and "/" not in str(row.get("name") or "")
    ]
    clocks.sort(key=lambda row: (int(row.get("top") or 0), int(row.get("left") or 0)))
    if len(clocks) >= 2:
        for row, value in ((clocks[0], start), (clocks[1], end)):
            click_row(hwnd, row)
            time.sleep(0.12)
            fill_focused(value)
            tap_vk(0x09)
            time.sleep(0.1)


def _fill_edits(hwnd: int, infos: list[dict], values: list[str]) -> None:
    side = _sidebar(infos, hwnd)
    edits = [
        row
        for row in side
        if "edit" in str(row.get("control_type") or "").casefold()
        or str(row.get("name") or "").casefold() in {"object", "target location", "caption"}
    ]
    edits.sort(key=lambda row: int(row.get("top") or 0))
    for row, value in zip(edits, values):
        if not value:
            continue
        click_row(hwnd, row)
        time.sleep(0.1)
        fill_focused(value)
        tap_vk(0x09)
        time.sleep(0.1)


def fill_l3(hwnd: int, span: L3Span, duration: float) -> None:
    click_pause(hwnd)
    infos = read_uia_infos(hwnd)
    opened = _open_empty_card(hwnd, infos, level="L3")
    if not opened:
        click_timeline_fraction(hwnd, span.start_s / max(duration, 0.1))
        time.sleep(0.15)
        infos = read_uia_infos(hwnd)
        if not _click_add(hwnd, infos, level="L3"):
            say("[L3] No empty card and + Add was not found. Not pressing 3 on a playing video.")
            return
        time.sleep(0.35)
    time.sleep(0.35)
    infos = read_uia_infos(hwnd)
    if not _hand_buttons_visible(infos, hwnd) and not span.idle:
        say("[L3] Hand buttons did not open. Click the empty A-card yourself if this keeps happening.")
        return
    _set_times(hwnd, infos, span.start_s, span.end_s)
    side = _sidebar(infos, hwnd)
    if span.idle:
        click_named(hwnd, side, "Idle — nothing is happening", "idle — nothing")
        say(f"[L3] Idle {seconds_to_timestamp(span.start_s)}–{seconds_to_timestamp(span.end_s)}")
        return
    button = HAND_BUTTONS.get(span.hand, "Right hand only")
    if not click_named(hwnd, side, button, exact=True):
        click_named(hwnd, side, "Right hand only", exact=True)
    time.sleep(0.25)
    infos = read_uia_infos(hwnd)
    side = _sidebar(infos, hwnd)
    combos = [row for row in side if "combo" in str(row.get("control_type") or "").casefold()]
    if combos:
        click_row(hwnd, combos[0])
        time.sleep(0.15)
        type_text(span.action)
        time.sleep(0.1)
        infos = read_uia_infos(hwnd)
        click_named(hwnd, _sidebar(infos, hwnd), span.action, exact=True)
    obj = span.obj if not span.tool else f"{span.obj} with {span.tool}"
    _fill_edits(hwnd, infos, [obj, span.target or ""])
    if not span.target:
        click_named(hwnd, side, "no placement destination", "object not moving")
    infos = read_uia_infos(hwnd)
    side = _sidebar(infos, hwnd)
    if click_named(hwnd, side, "Generate with AI", exact=True):
        say("[L3] Clicked Generate with AI on the open card")
        time.sleep(1.3)
    if span.caption:
        infos = read_uia_infos(hwnd)
        _fill_edits(hwnd, infos, ["", "", normalize_caption(span.caption)])
        cap = pick_named(_sidebar(infos, hwnd), "caption")
        if cap:
            click_row(hwnd, cap)
            fill_focused(normalize_caption(span.caption))
    say(f"[L3] {span.caption or 'idle'}")


def fill_l2(hwnd: int, span: L2Span, duration: float) -> None:
    click_pause(hwnd)
    infos = read_uia_infos(hwnd)
    opened = _open_empty_card(hwnd, infos, level="L2")
    if not opened:
        click_timeline_fraction(hwnd, span.start_s / max(duration, 0.1))
        infos = read_uia_infos(hwnd)
        if not _click_add(hwnd, infos, level="L2"):
            say("[L2] No empty card and + Add was not found.")
            return
        time.sleep(0.35)
    time.sleep(0.3)
    infos = read_uia_infos(hwnd)
    _set_times(hwnd, infos, span.start_s, span.end_s)
    if span.idle:
        say(f"[L2] Idle inherited {seconds_to_timestamp(span.start_s)}–{seconds_to_timestamp(span.end_s)}")
        return
    side = _sidebar(infos, hwnd)
    click_named(hwnd, side, "Success", exact=True)
    click_named(hwnd, side, str(span.retries) if span.retries else "0", exact=True)
    if click_named(hwnd, side, "Generate with AI", exact=True):
        say("[L2] Clicked Generate with AI on the open card")
        time.sleep(1.2)
    if span.caption:
        infos = read_uia_infos(hwnd)
        cap = pick_named(_sidebar(infos, hwnd), "caption")
        if cap:
            click_row(hwnd, cap)
            fill_focused(normalize_caption(span.caption))
    say(f"[L2] {span.caption}")


def fill_l1(hwnd: int, plan: EpisodePlan) -> None:
    infos = read_uia_infos(hwnd)
    side = _sidebar(infos, hwnd)
    if click_named(hwnd, side, "Select where it takes place", "Choose environment"):
        time.sleep(0.25)
        infos = read_uia_infos(hwnd)
        if not click_named(hwnd, infos, plan.environment, exact=True):
            click_named(hwnd, infos, "Home", exact=True)
        say(f"[L1] Environment: {plan.environment}")
    infos = read_uia_infos(hwnd)
    side = _sidebar(infos, hwnd)
    gens = [row for row in side if str(row.get("name") or "").strip() == "Generate with AI"]
    if gens:
        click_row(hwnd, gens[-1])
        say("[L1] Clicked Generate with AI")
        time.sleep(1.4)
    infos = read_uia_infos(hwnd)
    box = pick_named(_sidebar(infos, hwnd), "Describe the whole episode", "L1 episode caption", "episode caption")
    if box:
        click_row(hwnd, box)
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
    if click_named(hwnd, infos, "Submit Captions"):
        say("Clicked Submit Captions. Skip/Flag were not clicked.")
        return True
    say("Submit Captions button was not found.")
    return False


def watch_video(hwnd: int, duration_s: float) -> None:
    infos = read_uia_infos(hwnd)
    click_speed_1x(hwnd, infos)
    click_play(hwnd, infos)
    deadline = time.monotonic() + min(max(duration_s + 4.0, 6.0), 130.0)
    last = 0.0
    say("Watching the clip at 1x. Status lines should keep printing.")
    while time.monotonic() < deadline:
        blob = snapshot_text(hwnd)
        clock = parse_clock_blob(blob)
        now = time.monotonic()
        if clock:
            cur, total, frame, frames = clock
            if now - last >= 8:
                say(f"[Watch] {seconds_to_timestamp(cur)} / {seconds_to_timestamp(total)} frame {frame}/{frames}")
                last = now
            if total > 1 and cur >= total - 0.7:
                say("[Watch] Reached the end of the clip.")
                break
        elif now - last >= 8:
            say("[Watch] Still watching (clock not in UIA yet)...")
            last = now
        time.sleep(2.0)
    click_pause(hwnd)
    say("[Watch] Paused before labeling so new cards are not dropped on a moving playhead.")


def drive_plan(hwnd: int, plan: EpisodePlan, *, submit: bool) -> dict:
    names = read_uia_names(hwnd)
    existing = parse_sidebar_cards(names)
    say(
        f"On screen: {sum(1 for c in existing if c['level']=='L3')} L3 cards, "
        f"{sum(1 for c in existing if c['level']=='L2')} L2 cards "
        f"({sum(1 for c in existing if c['empty'])} empty)."
    )
    say(f"Plan: {len(plan.actions)} L3 actions, {len(plan.segments)} L2 segments, env={plan.environment}")
    for idx, action in enumerate(plan.actions, 1):
        say(f"[L3 {idx}/{len(plan.actions)}] opening an empty card and filling fields...")
        fill_l3(hwnd, action, plan.duration_s)
    for idx, segment in enumerate(plan.segments, 1):
        say(f"[L2 {idx}/{len(plan.segments)}] opening an empty card and filling fields...")
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
        say("Window attached; waiting for Video Caption Labeling to be on screen...")
        time.sleep(2)
        blob = snapshot_text(hwnd)
    video_id = parse_video_id(blob)
    clock = parse_clock_blob(blob)
    duration = clock[1] if clock else 73.5
    frames = clock[3] if clock else 0
    scene = pick_scene(blob, duration_s=duration, frame_count=frames)
    say(
        f"Video id: {video_id or 'unknown'}; duration {duration:.1f}s; "
        f"frames {frames or 'unknown'}; scene={scene.key}"
    )
    watch_video(hwnd, min(duration, 90))
    blob = snapshot_text(hwnd)
    clock = parse_clock_blob(blob) or clock
    if clock:
        duration = clock[1]
        frames = clock[3]
    from .planner import plan_episode

    plan = plan_episode(duration_s=duration, frame_count=frames, video_blob=blob)
    plan.video_id = video_id
    plan.environment = scene.environment
    return drive_plan(hwnd, plan, submit=submit)
