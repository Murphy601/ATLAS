"""Drive the already-open IX window via the Windows desktop (no DevTools, no Local API).

Same attach model as the lidar bot: SensorFusionLab Chromium is the task window.
ixBrowser | v2.9.20 is the profile manager and is ignored. Never clicks Send.
"""

from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

from .chathomebase import (
    CLAIMED_URL,
    PageSnapshot,
    is_forbidden_click,
    logbook_comment,
)
from .engine import handle_claimed_chat
from .ix_cdp import is_ix_chromium_exe, is_ix_launcher, is_stock_chrome_path
from .logbook import Logbook

logger = logging.getLogger("copilot.win_ui")

TASK_HINTS = (
    "chathomebase",
    "chat home base",
    "sensorfusionlab",
    "sensorfusion",
    "claimed",
)
REJECT_TITLE_TOKENS = (
    "google chrome",
    "google gemini",
    "microsoft edge",
)
HINDI_CHROMIUM = "क्रोमियम"
CHROME_CLASS = "Chrome_WidgetWin_1"
PICK_WAIT_S = 45.0
PICK_INTERVAL_S = 2.5
# Chat Home Base ids look like USETN4695969 — letters then a run of digits.
CHAT_ID_RE = re.compile(r"\b([A-Z]{4,8}\d{5,12})\b")
WAITING_HINTS = (
    "waiting for a claim",
    "waiting for next",
    "waiting for claim",
    "searching for a chat",
    "looking for a chat",
    "claiming chat",
    "claimloadercontainer",
)
LIVE_TESTIDS = (
    "messagetextarea",
    "messageslist",
    "messageitem",
    "claimednotification",
)
DRAFT_TESTIDS = ("messagetextarea", "typeyourreplyhere")
LOADER_TESTIDS = ("claimloadercontainer", "claimloader")
CHROME_UI_TOKENS = (
    "address and search bar",
    "address bar",
    "search or enter address",
    "bookmarks",
    "new tab",
    "reload",
    "refresh",
    "google chrome",
    "sensorfusionlab",
    "ixbrowser",
    "chrome legacy window",
    "omnibox",
    "app banner",
)
CHROME_UI_EXACT = {
    "chrome",
    "chromium",
    "menu",
    "toolbar",
    "document",
    "pane",
    "group",
    "back",
    "forward",
    "close",
    "minimize",
    "maximize",
    "restore",
    HINDI_CHROMIUM.casefold(),
}
CHAT_CHROME_EXACT = {
    "send",
    "save",
    "other",
    "cancel",
    "add",
    "logbook",
    "claimed",
    "unclaimed",
    "waiting",
    "chat",
    "messages",
    "send message",
    "send & end shift",
    "add log",
    "add new log",
    "create the log",
    "customer",
    "profile",
    "category",
    "comment",
    "chat home base",
    "claimed chat",
    "search",
    "end shift",
    "profile details",
    "add new log",
    "no logs yet",
    "you are",
    "type your reply here",
    "your message is too short",
}
CHAT_CHROME_TOKENS = (
    "chathomebase.com",
    "chat home base",
    "add new log",
    "create the log",
    "send & end",
    "type a message",
    "type your reply here",
    "claimloader",
    "messagetextarea",
    "messageslist",
    "logbook",
    "profile details",
    "no logs yet",
)


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


def keep_enumerated_window(
    width: int,
    height: int,
    *,
    visible: bool = True,
    minimized: bool = False,
    title: str = "",
    class_name: str = "",
    exe_path: str = "",
) -> bool:
    """Keep SensorFusionLab even when Win32 reports a tiny minimized rect."""
    if score_window(title, class_name, exe_path) > 0:
        return True
    if not visible and not minimized:
        return False
    if width < 400 or height < 300:
        return False
    return True


def _norm_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def _has_token(names: list[str], *needles: str) -> bool:
    blob = " ".join(_norm_token(name) for name in names)
    return any(needle in blob for needle in needles)


def is_chrome_ui_name(name: str) -> bool:
    text = (name or "").strip()
    lowered = text.casefold()
    if not lowered:
        return False
    if lowered in CHROME_UI_EXACT:
        return True
    return any(token in lowered for token in CHROME_UI_TOKENS)


def is_send_control_name(name: str) -> bool:
    return is_forbidden_click(label=name)


def _candidate_blob(candidate: dict) -> str:
    return " ".join(
        str(candidate.get(key) or "")
        for key in ("name", "automation_id")
    )


def is_chat_draft_marker(candidate: dict | str) -> bool:
    blob = _candidate_blob(candidate) if isinstance(candidate, dict) else str(candidate)
    lowered = blob.casefold()
    if "type your reply here" in lowered:
        return True
    return _has_token([blob], *DRAFT_TESTIDS)


def is_draft_edit(candidate: dict) -> bool:
    control_type = str(candidate.get("control_type") or "").casefold()
    name = str(candidate.get("name") or "")
    if is_chat_draft_marker(candidate):
        return True
    if "edit" not in control_type:
        return False
    if is_chrome_ui_name(name):
        return False
    if name.strip().casefold() in {"search", "find"}:
        return False
    if is_send_control_name(name):
        return False
    return True


def pick_named_control(
    candidates: list[dict],
    *needles: str,
    leftmost: bool = False,
) -> dict | None:
    hits: list[dict] = []
    for row in candidates:
        blob = _candidate_blob(row).casefold()
        name = str(row.get("name") or "")
        if is_send_control_name(name):
            continue
        if any(needle.casefold() in blob for needle in needles):
            hits.append(row)
    if not hits:
        return None
    if leftmost:
        hits.sort(key=lambda row: int(row.get("left") or 10**9))
        return hits[0]
    return hits[0]


def pick_draft_edit(candidates: list[dict], *, allow_fallback: bool = True) -> dict | None:
    """Prefer the Chat Home Base draft box. Never the address bar, never Send."""
    marked = [row for row in candidates if is_chat_draft_marker(row)]
    if marked:
        return marked[0]
    if not allow_fallback:
        return None
    edits = [row for row in candidates if is_draft_edit(row)]
    if not edits:
        return None
    edits.sort(key=lambda row: (int(row.get("top") or 0), int(row.get("width") or 0)), reverse=True)
    return edits[0]


def looks_like_chat_line(name: str) -> bool:
    text = " ".join((name or "").split())
    if len(text) < 8:
        return False
    lowered = text.casefold()
    if is_chrome_ui_name(text):
        return False
    if lowered in CHAT_CHROME_EXACT:
        return False
    if any(token in lowered for token in CHAT_CHROME_TOKENS):
        return False
    if is_send_control_name(text):
        return False
    if "://" in text or ".com" in lowered:
        return False
    compact = text.replace(" ", "")
    if CHAT_ID_RE.fullmatch(compact):
        return False
    if _has_token([text], *LIVE_TESTIDS, *LOADER_TESTIDS, "chatid", "sendchatmessagebutton"):
        return False
    if not any(ch.isalpha() for ch in text):
        return False
    if " " not in text and "?" not in text:
        return False
    return True


def parse_messages_from_names(names: list[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in names:
        if not looks_like_chat_line(name):
            continue
        text = " ".join(name.split())
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append({"sender": "client", "text": text})
    return out


def extract_chat_id(names: list[str]) -> str:
    for idx, name in enumerate(names):
        compact = (name or "").replace(" ", "").strip()
        if CHAT_ID_RE.fullmatch(compact):
            return compact
        if "chat-id" in (name or "").casefold() or _norm_token(name) == "chatid":
            if idx + 1 < len(names):
                nxt = names[idx + 1].replace(" ", "").strip()
                if CHAT_ID_RE.fullmatch(nxt):
                    return nxt
    return ""


def snapshot_from_uia_names(
    names: list[str],
    *,
    has_edit: bool = False,
    has_send: bool = False,
    title: str = "",
) -> PageSnapshot:
    """Waiting room vs live claim. Any Chromium Edit is not enough; /chat/claimed is not enough."""
    del has_edit, has_send  # Generic address-bar / search edits are not a claimed chat.
    lowered = " ".join(names).casefold()
    title_l = (title or "").casefold()
    has_loader = _has_token(names, *LOADER_TESTIDS) or any(hint in lowered for hint in WAITING_HINTS)
    has_draft = _has_token(names, *DRAFT_TESTIDS)
    has_messages = _has_token(names, "messageslist", "messageitem")
    has_claimed_notice = (
        _has_token(names, "claimednotification")
        or "chat is claimed" in lowered
        or "chat is claimed" in title_l
    )
    chat_id = extract_chat_id(names)
    live = bool(has_draft or has_messages or has_claimed_notice or chat_id)
    if has_loader and not has_draft and not has_messages:
        live = False
    waiting = not live
    customer_name = ""
    for idx, name in enumerate(names):
        if "customer" in name.casefold() and idx + 1 < len(names):
            nxt = names[idx + 1].strip()
            if nxt and len(nxt.split()) <= 3 and nxt[0].isalpha() and nxt.casefold() not in CHAT_CHROME_EXACT:
                customer_name = nxt
                break
    return PageSnapshot(
        url=CLAIMED_URL,
        waiting=waiting,
        live=live,
        chat_id=chat_id,
        customer_name=customer_name,
        title=title,
    )


def run_uia_attach(
    *,
    target_url: str = CLAIMED_URL,
    logbook_path: str | Path = "logbook.json",
    once: bool = False,
    poll_s: float = 1.5,
) -> int:
    if sys.platform != "win32":
        raise RuntimeError("Desktop IX control is Windows-only")

    say("DevTools is not exposed on this IX profile. Controlling the window you already opened...")
    say("Debug port 9222 is optional. Leave SensorFusionLab on Chat Home Base.")
    say(f"Target: {target_url}")
    _ensure_dpi_aware()
    prev_a11y = _enable_chromium_a11y()
    logbook = Logbook(logbook_path)
    previous = PageSnapshot(waiting=True)
    drafted_key: str | None = None
    say("Waiting for a live claimed conversation (loader is not a claim)...")
    try:
        hwnd, title = _pick_ix_window()
        say(f"Using IX window: {title or '(no title)'}")
        _focus(hwnd)
        time.sleep(0.8)
        while True:
            try:
                _text, nodes = _read_uia(hwnd, verbose=False)
            except Exception as exc:
                say(f"[Copilot] Window read failed, retrying: {exc}")
                time.sleep(poll_s)
                continue
            infos = [_node_info(ctrl) for ctrl in nodes]
            tokens = _uia_tokens(infos)
            current = snapshot_from_uia_names(tokens, title=title)
            if current.waiting:
                if previous.claimed:
                    say("[Copilot] Waiting for next claim...")
                    drafted_key = None
                previous = current
                time.sleep(poll_s)
                continue
            history = parse_messages_from_names(tokens)
            if not history:
                if previous.waiting:
                    say("[Copilot] Claimed chat is live. Waiting for customer messages...")
                previous = current
                time.sleep(poll_s)
                continue
            key = current.chat_id or "|".join(row["text"] for row in history[-3:])
            if key == drafted_key:
                previous = current
                time.sleep(poll_s)
                continue
            _process_live_chat(hwnd, current, logbook)
            drafted_key = key
            if once:
                return 0
            previous = current
            time.sleep(poll_s)
    except KeyboardInterrupt:
        say("\n[copilot] stopped (IX window left open)")
        return 0
    finally:
        _restore_chromium_a11y(prev_a11y)
        say("Disconnected from IX Browser (window left open)")
    return 0


def _process_live_chat(
    hwnd: int,
    snapshot: PageSnapshot,
    logbook: Logbook,
    history: list[dict[str, str]] | None = None,
) -> None:
    del history
    say("[Copilot] Claimed chat is live. Scrolling the thread so older messages can load...")
    _scroll_chat_history(hwnd)
    time.sleep(0.45)
    _text, nodes = _read_uia(hwnd, verbose=False)
    infos = [_node_info(ctrl) for ctrl in nodes]
    _open_customer_profile(hwnd, infos)
    time.sleep(0.35)
    _text, nodes = _read_uia(hwnd, verbose=False)
    infos = [_node_info(ctrl) for ctrl in nodes]
    tokens = _uia_tokens(infos)
    history_now = parse_messages_from_names(tokens)
    current = snapshot_from_uia_names(tokens, title=snapshot.title)
    say(f"[Copilot] Parsed {len(history_now)} visible lines from the IX window.")
    result = handle_claimed_chat(
        history_now,
        client_id=current.chat_id or snapshot.chat_id or snapshot.customer_name or "claimed",
        client_name=current.customer_name or snapshot.customer_name,
        persona_city=snapshot.profile_location,
        logbook=logbook,
    )
    for idx, option in enumerate(result.options, 1):
        say(f"Option {idx}: {option}")
    fields = dict(result.logbook_fields or {})
    if result.save_logbook or fields.get("clientCity") or fields.get("clientName"):
        try:
            if _fill_customer_log(hwnd, infos, fields):
                say("[Copilot] Customer logbook Other comment typed and saved. Send was not clicked.")
        except Exception as exc:
            say(f"[Copilot] Logbook click skipped: {exc}")
    if result.fill_draft:
        _text, nodes = _read_uia(hwnd, verbose=False)
        infos = [_node_info(ctrl) for ctrl in nodes]
        filled = _fill_draft(hwnd, infos, result.fill_draft)
        if filled:
            say("[Copilot] Typed the draft (no paste). Operator still sends — Send was not clicked.")
        else:
            say("[Copilot] Could not find the reply box. Type option 1 yourself. Send was not clicked.")
    elif result.blocked:
        say(f"[Copilot] BLOCKED: {result.reason}. Draft box left empty.")


def _fill_draft(hwnd: int, infos: list[dict], text: str) -> bool:
    if not text:
        return False
    chosen = pick_draft_edit(infos)
    if chosen is None:
        return False
    if is_send_control_name(str(chosen.get("name") or "")):
        return False
    _focus(hwnd)
    time.sleep(0.15)
    ctrl = chosen.get("ctrl")
    if ctrl is not None:
        _uia_click(ctrl)
    else:
        return False
    time.sleep(0.12)
    _clear_focused_edit()
    say("[Copilot] Typing the draft into the reply box (Chat Home Base rejects paste)...")
    _type_into_focused(text)
    return True


def _open_customer_profile(hwnd: int, infos: list[dict]) -> bool:
    chosen = pick_named_control(infos, "profile details", "profiledetails", leftmost=True)
    if chosen is None:
        return False
    say("[Copilot] Clicking customer PROFILE DETAILS...")
    _focus(hwnd)
    if chosen.get("ctrl") is not None:
        _uia_click(chosen["ctrl"])
        return True
    return False


def _fill_customer_log(hwnd: int, infos: list[dict], fields: dict[str, str]) -> bool:
    comment = logbook_comment(fields)
    if not comment:
        return False
    add = pick_named_control(
        infos,
        "add new log",
        "addnewlogbookbutton-customer",
        leftmost=True,
    )
    if add is None:
        say("[Copilot] Customer ADD NEW LOG was not in the window tree.")
        return False
    say("[Copilot] Clicking customer ADD NEW LOG...")
    _focus(hwnd)
    if add.get("ctrl") is not None:
        _uia_click(add["ctrl"])
    time.sleep(0.45)
    _text, nodes = _read_uia(hwnd, verbose=False)
    after = [_node_info(ctrl) for ctrl in nodes]
    category = pick_named_control(after, "logbookcategoryselect", "category")
    if category and category.get("ctrl") is not None:
        _uia_click(category["ctrl"])
        time.sleep(0.25)
        _text, nodes = _read_uia(hwnd, verbose=False)
        after = [_node_info(ctrl) for ctrl in nodes]
    other = None
    for row in after:
        if str(row.get("name") or "").strip().casefold() == "other":
            other = row
            break
    if other and other.get("ctrl") is not None:
        say("[Copilot] Choosing logbook category Other...")
        _uia_click(other["ctrl"])
        time.sleep(0.2)
        _text, nodes = _read_uia(hwnd, verbose=False)
        after = [_node_info(ctrl) for ctrl in nodes]
    box = pick_named_control(after, "logbookcomment")
    if box is None:
        edits = [
            row
            for row in after
            if is_draft_edit(row) and not is_chat_draft_marker(row)
        ]
        box = edits[0] if edits else None
    if box is None or box.get("ctrl") is None:
        say("[Copilot] Logbook comment box was not found.")
        return False
    _uia_click(box["ctrl"])
    time.sleep(0.12)
    _clear_focused_edit()
    say("[Copilot] Typing the customer logbook comment...")
    _type_into_focused(comment)
    save = pick_named_control(after, "create the log", "logbooksavebutton")
    if save is None:
        _text, nodes = _read_uia(hwnd, verbose=False)
        after = [_node_info(ctrl) for ctrl in nodes]
        save = pick_named_control(after, "create the log", "logbooksavebutton")
    if save is None or is_send_control_name(str(save.get("name") or "")):
        say("[Copilot] Logbook save control was not found (Send was not clicked).")
        return False
    if save.get("ctrl") is not None:
        _uia_click(save["ctrl"])
        return True
    return False


def _scroll_chat_history(hwnd: int) -> None:
    _focus(hwnd)
    left, top, width, height = _window_rect(hwnd)
    x = left + int(width * 0.50)
    y = top + int(height * 0.40)
    _click_screen(x, y)
    time.sleep(0.2)
    for _ in range(10):
        _mouse_wheel(120)
        time.sleep(0.28)
    for _ in range(3):
        _mouse_wheel(-120)
        time.sleep(0.18)


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return int(rect.left), int(rect.top), int(rect.right - rect.left), int(rect.bottom - rect.top)


def _mouse_wheel(delta: int) -> None:
    import ctypes

    ctypes.windll.user32.mouse_event(0x0800, 0, 0, int(delta), 0)


def _uia_tokens(infos: list[dict]) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for row in infos:
        for key in ("name", "automation_id"):
            value = str(row.get(key) or "").strip()
            if not value:
                continue
            folded = value.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            tokens.append(value)
    return tokens


def _uia_automation_id(ctrl: Any) -> str:
    try:
        value = getattr(ctrl.element_info, "automation_id", None) or ""
        return str(value).strip()
    except Exception:
        return ""


def _node_info(ctrl: Any) -> dict:
    name = _uia_name(ctrl)
    control_type = _uia_type(ctrl)
    top = left = width = height = 0
    try:
        rect = ctrl.rectangle()
        left = int(rect.left)
        top = int(rect.top)
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
    except Exception:
        pass
    return {
        "name": name,
        "automation_id": _uia_automation_id(ctrl),
        "control_type": control_type,
        "top": top,
        "left": left,
        "width": width,
        "height": height,
        "ctrl": ctrl,
    }


def _pick_ix_window() -> tuple[int, str]:
    deadline = time.time() + PICK_WAIT_S
    attempt = 0
    last_skipped: list[str] = []
    logged_skips = False
    seen_notes: set[str] = set()
    while True:
        attempt += 1
        found, skipped, notes = _enumerate_task_windows()
        last_skipped = skipped
        if not logged_skips:
            for title in skipped[:8]:
                say(f"Skipping non-task window: {title}")
            logged_skips = True
        for line in notes[:8]:
            if line in seen_notes:
                continue
            seen_notes.add(line)
            say(line)
        chosen = select_ix_window(found)
        if chosen is not None:
            exe = chosen.get("exe_path") or ""
            title = chosen.get("title") or ""
            if chosen.get("minimized"):
                say(f"SensorFusionLab was minimized; restoring {title or '(no title)'}")
            say(f"IX process: {exe or '(path unknown)'}")
            return int(chosen["hwnd"]), title
        if time.time() >= deadline:
            break
        say(
            f"Waiting for SensorFusionLab Chromium ({attempt})... "
            "click Open on the IX profile if that window is not on screen."
        )
        time.sleep(PICK_INTERVAL_S)
    seen = last_skipped[:8]
    raise RuntimeError(
        "Could not find the IX Chromium task window (SensorFusionLab). "
        "ixBrowser | v2.9.20 is the profile manager, not the task. "
        "Click Open on the profile, leave SensorFusionLab visible (not minimized), then retry. "
        f"Saw: {seen}"
    )


def _enumerate_task_windows() -> tuple[list[dict], list[str], list[str]]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[dict] = []
    skipped: list[str] = []
    notes: list[str] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        ex_style = user32.GetWindowLongW(hwnd, -20)
        if ex_style & 0x00000080:  # WS_EX_TOOLWINDOW
            return True
        visible = bool(user32.IsWindowVisible(hwnd))
        minimized = bool(user32.IsIconic(hwnd))
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        length = user32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buf, length + 1)
        class_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buf, 256)
        title = title_buf.value
        class_name = class_buf.value
        exe_path = _hwnd_exe(hwnd)
        if is_ix_chromium_exe(exe_path) or is_ix_launcher(title, exe_path):
            state = "minimized" if minimized else f"{width}x{height}"
            notes.append(f"Saw IX window ({state}): {title or '(no title)'}")
        if not keep_enumerated_window(
            width,
            height,
            visible=visible,
            minimized=minimized,
            title=title,
            class_name=class_name,
            exe_path=exe_path,
        ):
            if title and (
                any(token in title.lower() for token in REJECT_TITLE_TOKENS)
                or is_stock_chrome_path(exe_path)
                or is_ix_launcher(title, exe_path)
            ):
                skipped.append(title)
            return True
        points = score_window(title, class_name, exe_path)
        if points <= 0:
            if title and (
                any(token in title.lower() for token in REJECT_TITLE_TOKENS)
                or is_stock_chrome_path(exe_path)
                or is_ix_launcher(title, exe_path)
            ):
                skipped.append(title)
            return True
        found.append(
            {
                "hwnd": int(hwnd),
                "title": title,
                "class_name": class_name,
                "exe_path": exe_path,
                "minimized": minimized,
            }
        )
        return True

    user32.EnumWindows(callback, 0)
    return found, skipped, notes


def _hwnd_exe(hwnd: int) -> str:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    handle = kernel32.OpenProcess(0x1000, False, pid.value)
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
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(fg_thread, current_thread, False)
    user32.AttachThreadInput(target_thread, current_thread, False)


def _enable_chromium_a11y() -> int:
    import ctypes

    user32 = ctypes.windll.user32
    prev = ctypes.c_int(0)
    user32.SystemParametersInfoW(0x0046, 0, ctypes.byref(prev), 0)
    user32.SystemParametersInfoW(0x0047, 1, None, 0)
    return int(prev.value)


def _ensure_dpi_aware() -> None:
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


def _uia_type(ctrl: Any) -> str:
    for getter in (
        lambda: ctrl.element_info.control_type,
        lambda: getattr(ctrl.element_info, "localized_control_type", None),
        lambda: ctrl.friendly_class_name(),
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


def _click_screen(x: int, y: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.SetCursorPos(x, y)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


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


def _read_uia(hwnd: int, verbose: bool = True) -> tuple[str, list[Any]]:
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
            if verbose:
                say("UIA: SensorFusionLab window handle not found")
            return "", []
        for ctrl in _iter_uia_controls(target):
            nodes.append(ctrl)
            name = _uia_name(ctrl)
            if name:
                texts.append(name)
    except Exception as exc:
        if verbose:
            say(f"UIA read failed: {exc}")
        logger.debug("UIA read skipped", exc_info=True)
    named = [item for item in texts if item]
    if verbose:
        say(f"UIA named controls: {len(named)}")
        preview = [item for item in named if looks_like_chat_line(item) or is_send_control_name(item)][:12]
        if preview:
            say("UIA names: " + " | ".join(preview))
    return "\n".join(named), nodes


def _send_vk(vk: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)


def _send_ctrl_a() -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(0x11, 0, 0, 0)
    user32.keybd_event(0x41, 0, 0, 0)
    user32.keybd_event(0x41, 0, 2, 0)
    user32.keybd_event(0x11, 0, 2, 0)


def _clear_focused_edit() -> None:
    """Select all, then Backspace. Never paste. Never Enter."""
    _send_ctrl_a()
    time.sleep(0.05)
    _send_vk(0x08)


def _type_into_focused(text: str, delay_s: float = 0.02) -> None:
    """Key-by-key typing. Chat Home Base flags clipboard paste. Never Enter."""
    try:
        from pywinauto.keyboard import send_keys

        send_keys(_escape_keys(text), with_spaces=True, pause=delay_s)
        return
    except Exception:
        logger.debug("pywinauto send_keys failed; using SendInput", exc_info=True)
    _send_unicode(text, delay_s=delay_s)


def _escape_keys(text: str) -> str:
    out: list[str] = []
    for ch in text:
        if ch in {"\n", "\r"}:
            continue
        if ch == "{":
            out.append("{{}")
        elif ch == "}":
            out.append("{}}")
        elif ch in "+^%~()":
            out.append("{" + ch + "}")
        else:
            out.append(ch)
    return "".join(out)


def _send_unicode(text: str, delay_s: float = 0.02) -> None:
    import ctypes

    extra = ctypes.c_ulong(0)
    ulong_ptr = ctypes.POINTER(ctypes.c_ulong)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = (
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ulong_ptr),
        )

    class INPUT(ctypes.Structure):
        _fields_ = (("type", ctypes.c_ulong), ("ki", KEYBDINPUT))

    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_KEYUP = 0x0002
    INPUT_KEYBOARD = 1
    user32 = ctypes.windll.user32
    for ch in text:
        if ch in {"\n", "\r"}:
            continue
        code = ord(ch)
        down = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, ctypes.pointer(extra)))
        up = INPUT(
            type=INPUT_KEYBOARD,
            ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, ctypes.pointer(extra)),
        )
        user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
        user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))
        if delay_s:
            time.sleep(delay_s)
