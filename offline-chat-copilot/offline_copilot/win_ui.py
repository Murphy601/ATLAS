"""Drive the already-open IX window via the Windows desktop (no DevTools, no Local API).

Same attach model as the lidar bot: SensorFusionLab Chromium is the task window.
ixBrowser | v2.9.20 is the profile manager and is ignored. Never clicks Send.
"""

from __future__ import annotations

import logging
import random
import re
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Iterable

from .chathomebase import (
    CLAIMED_URL,
    PageSnapshot,
    claim_became_live,
    claim_identity,
    is_forbidden_click,
    logbook_comment,
)
from .engine import handle_claimed_chat
from .ix_cdp import is_ix_chromium_exe, is_ix_launcher, is_stock_chrome_path
from .logbook import Logbook
from .parser import clean_client_line, describe_intent, is_timestamp_line, parse_message

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
UIA_READ_TIMEOUT_S = 8.0
UIA_MAX_NODES = 1800
UIA_MAX_DEPTH = 18
HEARTBEAT_S = 8.0
_UIA_WORKER: threading.Thread | None = None
# Chat Home Base ids look like USETN4695969 (country + code + digits), not UUSETN... leftovers.
CHAT_ID_RE = re.compile(r"\b([A-Z]{2}[A-Z]{2,3}\d{5,12})\b")
WAITING_HINTS = (
    "waiting for conversation to be claimed",
    "waiting for a conversation",
    "conversation to be claimed",
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
# UIA often exposes the composer warning, not data-testid="messageTextArea".
LIVE_HINTS = (
    "type your reply here",
    "your message is too short",
    "message is too short",
    "0/75",
    "0 / 75",
)
CHROME_UI_TOKENS = (
    "address and search bar",
    "address bar",
    "search or enter address",
    "search or type a url",
    "search or type to search",
    "type a url",
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
    "waiting for conversation to be claimed",
    "action required",
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
    "waiting for conversation",
    "conversation to be claimed",
    "action required",
    "personal performance",
    "message statistics",
    "wish list",
    "axioserror",
    "failed to retrieve",
    "free messages",
    "paid messages",
    "total messages",
    "get insights about your message",
    "input-135-messages",
    "auto-typing",
    "message was removed",
    "sexual preferences",
    "rental home",
    "ground floor",
    "data analyst",
    "living apart together",
)
PROFILE_FIELD_EXACT = {
    "rental home",
    "ground floor",
    "data analyst",
    "sexual preferences",
    "profile details",
    "add new log",
    "non-smoker",
    "nonsmoker",
    "no smoking",
    "living apart together",
    "widow",
    "widower",
    "divorced",
    "single",
    "athletic",
    "credits",
    "locality",
    "timezone",
    "blond hair",
    "brown hair",
    "black hair",
    "blue eyes",
    "brown eyes",
    "normal",
    "auto",
    "sexy",
    "you are",
    "view_1",
    "view_2",
    "view 1",
}
INTIMATE_LINE_RE = re.compile(
    r"\b(?:cock|dick|clit|pussy|g-?spot|nipples?|balls?|suck|kiss|taste|on top|mouth|wet|tease|horny)\b",
    re.I,
)
PROFILE_LIVE_HINTS = (
    "profile details",
    "add new log",
)
_EXTRA_SLOW_TYPING = False


def say(msg: str) -> None:
    print(msg, flush=True)
    logger.info(msg)


def waiting_reason(names: list[str], title: str = "") -> str:
    """Which waiting-room hint matched. Empty if none."""
    blob = " ".join(names).casefold()
    title_l = (title or "").casefold()
    haystack = f"{blob} {title_l}"
    for hint in WAITING_HINTS:
        if hint in haystack:
            return hint
    return ""


def has_live_composer(names: list[str]) -> bool:
    """Reply box is on screen. UIA often names the 0/75 warning, not messageTextArea."""
    if _has_token(names, *DRAFT_TESTIDS, "messagetextarea"):
        return True
    lowered = " ".join(names).casefold()
    return any(hint in lowered for hint in LIVE_HINTS)


def describe_copilot_state(
    snapshot: PageSnapshot,
    names: list[str],
    *,
    named_count: int | None = None,
    timed_out: bool = False,
) -> str:
    count = named_count if named_count is not None else len(names)
    reason = waiting_reason(names, snapshot.title)
    if timed_out and count == 0:
        return "[Copilot] Still attached. Chromium accessibility is slow; retrying the window read."
    if snapshot.waiting:
        if reason:
            return (
                f"[Copilot] Waiting room on screen ({reason}). "
                "Not typing. Send was not clicked."
            )
        if count == 0:
            return "[Copilot] Still attached. Waiting for a live claimed conversation. Not typing."
        return "[Copilot] Waiting for a live claimed conversation. Not typing."
    who = snapshot.customer_name or "this client"
    cid = snapshot.chat_id or "no chat-id yet"
    n_msgs = len(parse_messages_from_names(names))
    return f"[Copilot] Live claim {cid} / {who} ({n_msgs} visible lines)."


def preview_window_names(names: list[str], limit: int = 10) -> str:
    interesting = (
        "waiting",
        "type your reply",
        "too short",
        "claimed",
        "message",
        "profile",
        "logbook",
        "add new log",
        "you are",
    )
    hits: list[str] = []
    for name in names:
        lowered = name.casefold()
        if CHAT_ID_RE.search(name.replace(" ", "")) or any(token in lowered for token in interesting):
            hits.append(name)
        if len(hits) >= limit:
            break
    return " | ".join(hits)


def walk_control_tree(
    root: Any,
    *,
    get_children: Callable[[Any], Iterable[Any]],
    deadline: float,
    limit: int = UIA_MAX_NODES,
    max_depth: int = UIA_MAX_DEPTH,
) -> list[Any]:
    """Breadth-first walk with a time budget so Chromium a11y cannot freeze the copilot."""
    out: list[Any] = []
    queue: deque[tuple[Any, int]] = deque([(root, 0)])
    while queue:
        if time.monotonic() >= deadline or len(out) >= limit:
            break
        node, depth = queue.popleft()
        out.append(node)
        if depth >= max_depth:
            continue
        try:
            kids = list(get_children(node) or [])
        except Exception:
            continue
        for kid in kids:
            if time.monotonic() >= deadline or len(out) >= limit:
                break
            queue.append((kid, depth + 1))
    return out


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


def is_omnibox(candidate: dict) -> bool:
    name = str(candidate.get("name") or "").casefold()
    auto = str(candidate.get("automation_id") or "").casefold()
    if is_chrome_ui_name(name):
        return True
    if name in {"search", "find", "filter"} or "search" in name:
        return True
    if auto.startswith("input-") or "omnibox" in auto:
        return True
    return any(
        token in name
        for token in (
            "address",
            "omnibox",
            "search or type",
            "type a url",
            "find in page",
        )
    )


def is_search_or_chrome_edit(candidate: dict) -> bool:
    if is_omnibox(candidate):
        return True
    top = int(candidate.get("top") or 0)
    if 0 < top < 180:
        return True
    return False


def is_draft_edit(candidate: dict) -> bool:
    control_type = str(candidate.get("control_type") or "").casefold()
    name = str(candidate.get("name") or "")
    if is_omnibox(candidate):
        return False
    if is_chat_draft_marker(candidate):
        return True
    if "edit" not in control_type:
        return False
    if is_chrome_ui_name(name):
        return False
    if name.strip().casefold() in {"search", "find", "filter"}:
        return False
    if "search" in name.strip().casefold() or str(candidate.get("automation_id") or "").casefold().startswith("input-"):
        return False
    if is_send_control_name(name):
        return False
    return True


def pick_named_control(
    candidates: list[dict],
    *needles: str,
    leftmost: bool = False,
    rightmost: bool = False,
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
    if rightmost:
        hits.sort(key=lambda row: int(row.get("left") or -1), reverse=True)
        return hits[0]
    return hits[0]


def pick_logbook_save(candidates: list[dict]) -> dict | None:
    """Create the log — never Send."""
    for needle in ("create the log", "logbooksavebutton", "create log"):
        hit = pick_named_control(candidates, needle)
        if hit and not is_send_control_name(str(hit.get("name") or "")):
            return hit
    for row in candidates:
        name = str(row.get("name") or "").strip().casefold()
        ctype = str(row.get("control_type") or "").casefold()
        if name in {"save", "create"} and "button" in ctype and not is_send_control_name(name):
            return row
    return None


def pick_draft_edit(
    candidates: list[dict],
    *,
    allow_fallback: bool = False,
    live: bool = False,
    chrome_bottom: int = 180,
) -> dict | None:
    """Only Type your reply here / messageTextArea. Never search, never the address bar."""
    del live  # Unmarked edits include search; only the real composer is safe.
    marked = [
        row
        for row in candidates
        if is_chat_draft_marker(row) and not is_search_or_chrome_edit(row) and int(row.get("top") or 0) >= chrome_bottom
    ]
    if marked:
        marked.sort(key=lambda row: int(row.get("top") or 0), reverse=True)
        return marked[0]
    warning = pick_named_control(candidates, "your message is too short") or pick_named_control(
        candidates, "type your reply here"
    )
    if warning is not None:
        nearby = [
            row
            for row in candidates
            if is_draft_edit(row)
            and not is_search_or_chrome_edit(row)
            and int(row.get("top") or 0) >= chrome_bottom
            and abs(int(row.get("top") or 0) - int(warning.get("top") or 0)) < 120
            and int(row.get("top") or 0) <= int(warning.get("top") or 0)
        ]
        if nearby:
            nearby.sort(key=lambda row: int(row.get("top") or 0), reverse=True)
            return nearby[0]
        # Click just above the 0/75 warning, which sits under the reply box.
        return {
            "name": "Type your reply here...",
            "left": int(warning.get("left") or 0),
            "top": max(chrome_bottom, int(warning.get("top") or 0) - 48),
            "width": max(int(warning.get("width") or 240), 240),
            "height": 40,
            "ctrl": None,
        }
    del allow_fallback
    return None


def latest_client_line_from_infos(infos: list[dict]) -> str:
    """Newest customer bubble in the center column. Never a profile field like Rental home."""
    warning_top = 10**9
    min_x, max_x = _x_bounds(infos)
    for row in infos:
        name = str(row.get("name") or "")
        if "your message is too short" in name.casefold() or "type your reply here" in name.casefold():
            warning_top = min(warning_top, int(row.get("top") or warning_top))
    lines: list[tuple[int, str]] = []
    for row in infos:
        name = str(row.get("name") or "").strip()
        if not looks_like_chat_line(name):
            continue
        left = int(row.get("left") or 0)
        if _column_for_left(left, min_x, max_x) != "chat":
            continue
        if _chat_sender(left, min_x, max_x) != "client":
            continue
        top = int(row.get("top") or 0)
        if top <= 0:
            continue
        if warning_top < 10**9 and top >= warning_top - 8:
            continue
        cleaned = clean_client_line(name)
        if len(cleaned) < 8:
            continue
        lines.append((top, cleaned))
    if not lines:
        for row in infos:
            name = str(row.get("name") or "").strip()
            if not looks_like_chat_line(name):
                continue
            top = int(row.get("top") or 0)
            if top <= 0:
                continue
            if warning_top < 10**9 and top >= warning_top - 8:
                continue
            cleaned = clean_client_line(name)
            if len(cleaned) < 8:
                continue
            lines.append((top, cleaned))
    if not lines:
        return ""
    lines.sort()
    return lines[-1][1]


def choose_latest_client_line(infos: list[dict], history: list[dict[str, str]]) -> str:
    """Last customer bubble that needs a reply. Never a timestamp, profile field, or persona line."""
    latest = latest_client_line_from_infos(infos)
    if latest:
        return latest
    for row in reversed(history or []):
        if (row.get("sender") or "client").casefold() != "client":
            continue
        text = clean_client_line(str(row.get("text") or ""))
        if looks_like_chat_line(text):
            return text
    return ""


def is_profile_field_text(name: str) -> bool:
    lowered = " ".join((name or "").split()).casefold()
    if not lowered:
        return False
    if lowered in PROFILE_FIELD_EXACT:
        return True
    if re.fullmatch(r"view[_\s-]?\d+", lowered):
        return True
    if re.fullmatch(r"\d+\s*credits?", lowered):
        return True
    if re.search(r"\b\d+ft\b", lowered) or re.search(r"\b\d{3}\s*-\s*\d{3}\s*cm\b", lowered):
        return True
    if re.match(r"^america[/, ]", lowered):
        return True
    return False


def looks_like_chat_line(name: str) -> bool:
    cleaned = clean_client_line(name)
    text = cleaned or " ".join((name or "").split())
    if len(cleaned) < 8:
        return False
    lowered = text.casefold()
    if is_profile_field_text(text):
        return False
    if is_timestamp_line(text):
        return False
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
    if len(text) < 22 and not INTIMATE_LINE_RE.search(text) and not any(ch in text for ch in "?!."):
        return False
    return True


def _x_bounds(infos: list[dict]) -> tuple[int, int]:
    lefts = [int(row.get("left") or 0) for row in infos]
    rights = [int(row.get("left") or 0) + max(int(row.get("width") or 0), 1) for row in infos]
    return (min(lefts) if lefts else 0, max(rights) if rights else 1)


def _column_for_left(left: int, min_x: int, max_x: int) -> str:
    span = max_x - min_x
    if span < 120:
        return "chat"
    rel = (left - min_x) / span
    if rel < 0.18:
        return "customer_profile"
    if rel > 0.80:
        return "persona_profile"
    return "chat"


def _chat_sender(left: int, min_x: int, max_x: int) -> str:
    span = max_x - min_x
    if span < 120:
        return "client"
    rel = (left - min_x) / span
    if rel < 0.50:
        return "client"
    return "operator"


def parse_messages_from_infos(infos: list[dict]) -> list[dict[str, str]]:
    min_x, max_x = _x_bounds(infos)
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in infos:
        text = clean_client_line(str(row.get("name") or "")) or " ".join(str(row.get("name") or "").split())
        if not looks_like_chat_line(str(row.get("name") or "")):
            continue
        left = int(row.get("left") or 0)
        if _column_for_left(left, min_x, max_x) != "chat":
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append({"sender": _chat_sender(left, min_x, max_x), "text": text})
    return out


def parse_messages_from_names(names: list[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in names:
        text = clean_client_line(name) or " ".join(name.split())
        if not looks_like_chat_line(name):
            continue
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
        match = CHAT_ID_RE.search(name or "")
        if match:
            start = match.start()
            if start == 0 or not (name or "")[start - 1].isalpha():
                return match.group(1)
        if "chat-id" in (name or "").casefold() or _norm_token(name) == "chatid":
            if idx + 1 < len(names):
                nxt = names[idx + 1].replace(" ", "").strip()
                if CHAT_ID_RE.fullmatch(nxt):
                    return nxt
    return ""


HANDLE_SKIP = {
    "widow",
    "widower",
    "bald",
    "retired",
    "nurse",
    "villa",
    "customer",
    "profile",
    "chromium",
    "document",
    "toolbar",
    "non-smoker",
    "nonsmoker",
    "trying",
    "search",
    "view_1",
    "view_2",
    "credits",
    "athletic",
    "single",
    "divorced",
}


def _looks_like_firebase_id(text: str) -> bool:
    """Reject Chat Home Base / Firebase random ids like fmsRjh9xNik3lfpt5DPC."""
    value = (text or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{16,28}", value):
        return False
    uppers = sum(1 for ch in value if ch.isupper())
    lowers = sum(1 for ch in value if ch.islower())
    digits = sum(1 for ch in value if ch.isdigit())
    return uppers >= 3 and lowers >= 3 and digits >= 1


def _looks_like_handle(text: str) -> bool:
    value = (text or "").strip()
    if not value or len(value) > 32:
        return False
    lowered = value.casefold()
    if lowered in CHAT_CHROME_EXACT or lowered in HANDLE_SKIP:
        return False
    if is_send_control_name(value) or is_chrome_ui_name(value):
        return False
    if CHAT_ID_RE.search(value) or CHAT_ID_RE.fullmatch(value.replace(" ", "")):
        return False
    if _looks_like_firebase_id(value):
        return False
    if value.isdigit():
        return False
    if re.fullmatch(r"view[_\s-]?\d+", lowered):
        return False
    if " " in value:
        return len(value.split()) <= 2 and value[0].isalpha()
    return bool(re.match(r"^[A-Za-z0-9_]{3,24}$", value))


def extract_customer_name(names: list[str]) -> str:
    """Left-column client handle. Never the persona under 'you are'."""
    blocked: set[str] = set()
    for idx, name in enumerate(names):
        if name.strip().casefold() in {"you are", "youare"}:
            if idx + 1 < len(names):
                blocked.add(names[idx + 1].strip().casefold())
            if idx + 2 < len(names):
                blocked.add(names[idx + 2].strip().casefold())
    for idx, name in enumerate(names):
        token = _norm_token(name)
        if token in {"logbookcustomername", "logbookcustomer"}:
            if idx + 1 < len(names):
                nxt = names[idx + 1].strip()
                if _looks_like_handle(nxt) and nxt.casefold() not in blocked:
                    return nxt
    for idx, name in enumerate(names):
        if "customer" in name.casefold() and idx + 1 < len(names):
            nxt = names[idx + 1].strip()
            if _looks_like_handle(nxt) and nxt.casefold() not in blocked:
                return nxt
    for name in names:
        value = name.strip()
        if _looks_like_handle(value) and value.casefold() not in blocked:
            if re.search(r"\d", value) or value[0].islower():
                return value
    return ""


def extract_sidebar_facts(infos: list[dict]) -> dict[str, str]:
    """Likes/places/details from the left customer column and right persona column."""
    min_x, max_x = _x_bounds(infos)
    customer_bits: list[str] = []
    persona_bits: list[str] = []
    customer_name = ""
    persona_name = ""
    customer_city = ""
    persona_city = ""
    for row in infos:
        text = " ".join(str(row.get("name") or "").split())
        if not text or looks_like_chat_line(text):
            continue
        col = _column_for_left(int(row.get("left") or 0), min_x, max_x)
        lowered = text.casefold()
        if col == "customer_profile":
            if _looks_like_handle(text) and re.search(r"\d", text):
                customer_name = customer_name or text
            if re.search(r"\b[A-Z][a-z]+,\s*[A-Z][a-z]+", text):
                customer_city = customer_city or text
            if is_profile_field_text(text) or lowered in {"widow", "single", "divorced", "athletic", "rental home", "ground floor"}:
                customer_bits.append(text)
        elif col == "persona_profile":
            if _looks_like_handle(text) and not re.fullmatch(r"view[_\s-]?\d+", lowered):
                if not persona_name and not re.search(r"\d", text):
                    persona_name = text
            if re.search(r"\b[A-Z][a-z]+,\s*[A-Z][a-z]+", text):
                persona_city = persona_city or text
            if is_profile_field_text(text) or "data analyst" in lowered or "rental home" in lowered:
                persona_bits.append(text)
    return {
        "clientName": customer_name,
        "clientCity": customer_city.split(",")[0].strip() if customer_city else "",
        "clientNotes": "; ".join(dict.fromkeys(customer_bits) ),
        "personaName": persona_name,
        "personaCity": persona_city.split(",")[0].strip() if persona_city else "",
        "personaNotes": "; ".join(dict.fromkeys(persona_bits)),
    }


def pick_logbook_comment(candidates: list[dict], *, composer_top: int | None = None) -> dict | None:
    hit = pick_named_control(candidates, "logbookcomment", "logbook comment", "add a comment")
    if hit and not is_search_or_chrome_edit(hit) and not is_chat_draft_marker(hit):
        return hit
    edits: list[dict] = []
    for row in candidates:
        ctype = str(row.get("control_type") or "").casefold()
        if "edit" not in ctype:
            continue
        if is_search_or_chrome_edit(row) or is_chat_draft_marker(row) or is_send_control_name(str(row.get("name") or "")):
            continue
        top = int(row.get("top") or 0)
        if composer_top and abs(top - composer_top) < 90:
            continue
        name = str(row.get("name") or "").casefold()
        if name in {"search", "find", "filter"}:
            continue
        if "comment" in name or not name.strip() or "logbook" in name:
            edits.append(row)
    if not edits:
        return None
    edits.sort(key=lambda row: int(row.get("top") or 0))
    return edits[0]


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
    waiting_copy = (
        _has_token(names, *LOADER_TESTIDS)
        or any(hint in lowered for hint in WAITING_HINTS)
        or any(hint in title_l for hint in WAITING_HINTS)
    )
    composer = has_live_composer(names)
    has_profile = any(hint in lowered for hint in PROFILE_LIVE_HINTS)
    live_bubbles = any(looks_like_chat_line(name) for name in names)
    noise = any(
        token in lowered
        for token in (
            "personal performance",
            "message statistics",
            "wish list",
            "axioserror",
            "failed to retrieve",
            "get insights about your message",
            "input-135-messages",
        )
    )
    chat_id = extract_chat_id(names)
    loader_only = waiting_copy and not composer and not has_profile
    # Wish-list / stats overlays mention PROFILE DETAILS. Those are not a claimed thread.
    if noise and not composer:
        live = False
    elif loader_only:
        live = False
    else:
        live = bool(composer or has_profile or (chat_id and live_bubbles))
    waiting = not live
    customer_name = extract_customer_name(names)
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
    last_status = ""
    last_beat = 0.0
    say("Waiting for a live claimed conversation (loader is not a claim)...")
    say("You should keep seeing status lines here. Silence means the window read is stuck.")
    try:
        hwnd, title = _pick_ix_window()
        say(f"Using IX window: {title or '(no title)'}")
        _focus(hwnd)
        time.sleep(0.4)
        first_read = True
        while True:
            title = _hwnd_title(hwnd) or title
            try:
                infos, timed_out = _read_window(hwnd, announce=first_read)
            except Exception as exc:
                say(f"[Copilot] Window read failed, retrying: {exc}")
                time.sleep(poll_s)
                continue
            first_read = False
            tokens = _uia_tokens(infos)
            current = snapshot_from_uia_names(tokens, title=title)
            status = describe_copilot_state(
                current,
                tokens,
                named_count=len(tokens),
                timed_out=timed_out,
            )
            now = time.monotonic()
            beat_s = 30.0 if current.waiting else HEARTBEAT_S
            if status != last_status or (now - last_beat) >= beat_s:
                say(status)
                preview = preview_window_names(tokens)
                if preview and status != last_status:
                    say(f"[Copilot] Window text: {preview}")
                last_status = status
                last_beat = now
            if current.waiting:
                if previous.claimed:
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
            latest_preview = choose_latest_client_line(infos, history)
            key = f"{claim_identity(current)}|{latest_preview.casefold()[:160]}"
            if not claim_became_live(previous, current) and key == drafted_key:
                previous = current
                time.sleep(poll_s)
                continue
            if previous.claimed and drafted_key and key != drafted_key:
                say("[Copilot] Next claim is on screen. Clients rotate; starting this one.")
            say(f"[Copilot] Working claim {current.chat_id or 'no chat-id yet'} / {current.customer_name or 'this client'}")
            _process_live_chat(hwnd, current, logbook, infos=infos)
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
    infos: list[dict] | None = None,
) -> None:
    del history, infos
    if snapshot.waiting:
        say("[Copilot] Page is still waiting for a conversation to be claimed. Not typing.")
        return
    say("[Copilot] Claimed chat is live. Scrolling the thread so older messages can load...")
    _scroll_load_older(hwnd)
    _scroll_to_latest(hwnd)
    time.sleep(0.35)
    infos, _timed_out = _read_window(hwnd, announce=False)
    tokens = _uia_tokens(infos)
    lowered_blob = " ".join(tokens).casefold()
    if "auto-typing" in lowered_blob or "message was removed" in lowered_blob:
        global _EXTRA_SLOW_TYPING
        _EXTRA_SLOW_TYPING = True
        say("[Copilot] Site warned about auto-typing. Slowing the keys more. Send was not clicked.")
    history_now = parse_messages_from_infos(infos) or parse_messages_from_names(tokens)
    current = snapshot_from_uia_names(tokens, title=snapshot.title)
    if current.waiting:
        still_live = snapshot.claimed and (
            any(looks_like_chat_line(name) for name in tokens)
            or any(hint in lowered_blob for hint in PROFILE_LIVE_HINTS)
        )
        if still_live:
            say("[Copilot] Still on the claimed thread after scroll. Not treating this as the waiting room.")
            current = snapshot
        else:
            say("[Copilot] Still waiting for a conversation to be claimed. Not typing.")
            return
    say(f"[Copilot] Parsed {len(history_now)} visible lines from the IX window.")
    latest = choose_latest_client_line(infos, history_now)
    if latest:
        history_now = [row for row in history_now if row["text"].casefold() != latest.casefold()]
        history_now.append({"sender": "client", "text": latest})
        say(f"[Copilot] Latest client line: {latest[:180]}")
        parsed_latest = parse_message(latest)
        say(f"[Copilot] Rule match: {describe_intent(parsed_latest)}")
        say("[Copilot] Older bubbles are context only. The draft answers that last customer line.")
    else:
        say("[Copilot] No real customer bubble found yet. Not typing.")
        return
    client_id = current.chat_id or snapshot.chat_id or "claimed"
    client_name = current.customer_name or snapshot.customer_name
    if client_name and (CHAT_ID_RE.search(client_name) or CHAT_ID_RE.fullmatch(client_name.replace(" ", ""))):
        client_name = ""
    say(f"[Copilot] Client on screen: {client_name or 'this client'} ({client_id})")
    result = handle_claimed_chat(
        history_now,
        client_id=client_id,
        client_name=client_name,
        header_name=client_name,
        persona_city=snapshot.profile_location,
        logbook=logbook,
        remember=False,
    )
    for idx, option in enumerate(result.options, 1):
        say(f"Option {idx}: {option}")
    if result.fill_draft:
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
    tokens = _uia_tokens(infos)
    lowered_blob = " ".join(tokens).casefold()
    live_thread = has_live_composer(tokens) or any(hint in lowered_blob for hint in PROFILE_LIVE_HINTS)
    if not live_thread:
        infos, _timed_out = _read_window(hwnd, announce=False)
        tokens = _uia_tokens(infos)
        lowered_blob = " ".join(tokens).casefold()
        live_thread = has_live_composer(tokens) or any(hint in lowered_blob for hint in PROFILE_LIVE_HINTS)
    if not live_thread:
        say("[Copilot] No Type-your-reply box on screen. Not typing.")
        return False
    left, top, width, height = _window_rect(hwnd)
    chrome_bottom = top + 180
    chosen = pick_draft_edit(infos, allow_fallback=False, live=False, chrome_bottom=chrome_bottom)
    if chosen is None:
        infos, _timed_out = _read_window(hwnd, announce=False)
        chosen = pick_draft_edit(infos, allow_fallback=False, live=False, chrome_bottom=chrome_bottom)
    if chosen is None:
        say("[Copilot] Composer not in the UIA tree. Clicking the reply area by position, not search.")
        chosen = {
            "name": "Type your reply here...",
            "left": left + int(width * 0.52) - 120,
            "top": top + int(height * 0.86) - 20,
            "width": 240,
            "height": 40,
            "ctrl": None,
        }
    if is_search_or_chrome_edit(chosen) or int(chosen.get("top") or 0) < chrome_bottom:
        say("[Copilot] Refusing to type in the address/search bar.")
        return False
    if is_send_control_name(str(chosen.get("name") or "")):
        return False
    chosen = dict(chosen)
    chosen["ctrl"] = None  # Coordinate click only. UIA click can look like paste.
    _focus(hwnd)
    time.sleep(0.12)
    if not _click_composer(hwnd, chosen):
        return False
    time.sleep(0.2)
    _clear_focused_edit()
    say("[Copilot] Typing into the reply box with real keys (no paste, no search bar)...")
    _type_into_focused(text, extra_slow=_EXTRA_SLOW_TYPING)
    return True


def _click_composer(hwnd: int, chosen: dict) -> bool:
    """Click the reply box in the lower-center chat column, never the top search/address bar."""
    left, top, width, height = _window_rect(hwnd)
    x = int(chosen.get("left") or 0) + max(int(chosen.get("width") or 0), 40) // 2
    y = int(chosen.get("top") or 0) + max(int(chosen.get("height") or 0), 24) // 2
    if y < top + 180:
        say("[Copilot] Refusing to click the address/search bar.")
        return False
    safe_x = left + int(width * 0.52)
    safe_y = top + int(height * 0.86)
    if x < left + int(width * 0.28):
        x = safe_x
    if y < top + int(height * 0.55):
        y = safe_y
    _focus(hwnd)
    _click_screen(x, y)
    return True


def _open_named(hwnd: int, infos: list[dict], needle: str, *, leftmost: bool = True) -> bool:
    chosen = pick_named_control(infos, needle, leftmost=leftmost, rightmost=not leftmost)
    if chosen is None:
        return False
    say(f"[Copilot] Clicking {needle.upper()}...")
    _focus(hwnd)
    return _click_candidate(hwnd, chosen)


def _scroll_profile_column(hwnd: int, x_ratio: float) -> None:
    _focus(hwnd)
    left, top, width, height = _window_rect(hwnd)
    x = left + int(width * x_ratio)
    y = top + int(height * 0.48)
    _click_screen(x, y)
    time.sleep(0.15)
    for _ in range(7):
        _mouse_wheel(-120)
        time.sleep(0.16)


def _open_customer_profile(hwnd: int, infos: list[dict]) -> bool:
    return _open_named(hwnd, infos, "profile details", leftmost=True)


def _fill_sided_log(hwnd: int, infos: list[dict], comment: str, *, leftmost: bool) -> bool:
    if not comment:
        return False
    side = "customer" if leftmost else "persona"
    add = pick_named_control(
        infos,
        "add new log",
        "addnewlogbookbutton-customer",
        "addnewlogbookbutton-profile",
        leftmost=leftmost,
        rightmost=not leftmost,
    )
    if add is None:
        say(f"[Copilot] {side} ADD NEW LOG was not in the window tree.")
        return False
    say(f"[Copilot] Clicking {side} ADD NEW LOG...")
    _focus(hwnd)
    _click_candidate(hwnd, add)
    time.sleep(0.7)
    after, _timed_out = _read_window(hwnd, announce=False)
    category = pick_named_control(after, "logbookcategoryselect", "category")
    if category:
        _click_candidate(hwnd, category)
        time.sleep(0.25)
        after, _timed_out = _read_window(hwnd, announce=False)
    other = None
    for row in after:
        if str(row.get("name") or "").strip().casefold() == "other":
            other = row
            break
    if other:
        say("[Copilot] Choosing logbook category Other...")
        _click_candidate(hwnd, other)
        time.sleep(0.25)
        after, _timed_out = _read_window(hwnd, announce=False)
    warning = pick_named_control(after, "your message is too short")
    composer_top = int(warning.get("top") or 0) if warning else None
    box = pick_logbook_comment(after, composer_top=composer_top)
    if box is None:
        say("[Copilot] Logbook comment box was not found.")
        return False
    if not _click_candidate(hwnd, box):
        say("[Copilot] Logbook comment box was not found.")
        return False
    time.sleep(0.18)
    _clear_focused_edit()
    say(f"[Copilot] Typing the {side} logbook comment slowly...")
    say(f"[Copilot] Logbook: {comment}")
    _type_into_focused(comment)
    time.sleep(0.6)
    after, _timed_out = _read_window(hwnd, announce=False)
    save = pick_logbook_save(after)
    if save is None:
        time.sleep(0.55)
        after, _timed_out = _read_window(hwnd, announce=False)
        save = pick_logbook_save(after)
    if save is None or is_send_control_name(str(save.get("name") or "")):
        say("[Copilot] Logbook save control was not found (Send was not clicked).")
        _dismiss_overlays()
        return False
    say("[Copilot] Saving the log (Send was not clicked)...")
    return _click_candidate(hwnd, save)


def _fill_customer_log(hwnd: int, infos: list[dict], fields: dict[str, str]) -> bool:
    return _fill_sided_log(hwnd, infos, logbook_comment(fields), leftmost=True)


def _scroll_chat_history(hwnd: int) -> None:
    _scroll_load_older(hwnd)
    _scroll_to_latest(hwnd)


def _scroll_load_older(hwnd: int) -> None:
    _focus(hwnd)
    left, top, width, height = _window_rect(hwnd)
    x = left + int(width * 0.52)
    y = top + int(height * 0.42)
    _click_screen(x, y)
    time.sleep(0.2)
    for _ in range(4):
        _mouse_wheel(120)
        time.sleep(0.16)


def _scroll_to_latest(hwnd: int) -> None:
    _focus(hwnd)
    left, top, width, height = _window_rect(hwnd)
    x = left + int(width * 0.52)
    y = top + int(height * 0.42)
    _click_screen(x, y)
    time.sleep(0.15)
    for _ in range(8):
        _mouse_wheel(-120)
        time.sleep(0.10)
    _send_vk(0x23)  # End — newest bubble, not leftover older history.
    time.sleep(0.25)


def _dismiss_overlays() -> None:
    """Close logbook / wish-list popups. Never Enter. Never Ctrl+V."""
    _send_vk(0x1B)
    time.sleep(0.12)


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


def _hwnd_title(hwnd: int) -> str:
    if sys.platform != "win32":
        return ""
    import ctypes

    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _click_candidate(hwnd: int, chosen: dict | None) -> bool:
    if not chosen:
        return False
    ctrl = chosen.get("ctrl")
    if ctrl is not None and _uia_click(ctrl):
        return True
    left = int(chosen.get("left") or 0)
    top = int(chosen.get("top") or 0)
    width = int(chosen.get("width") or 0)
    height = int(chosen.get("height") or 0)
    if width <= 2 or height <= 2:
        return False
    _focus(hwnd)
    _click_screen(left + width // 2, top + height // 2)
    return True


def _wrapper_children(ctrl: Any) -> list[Any]:
    try:
        kids = ctrl.children()
    except Exception:
        return []
    return list(kids or [])


def _collect_window_infos(hwnd: int, deadline: float) -> list[dict]:
    from pywinauto import Application

    remaining = max(0.4, deadline - time.monotonic())
    app = Application(backend="uia").connect(handle=hwnd, timeout=min(2.0, remaining))
    target = app.window(handle=hwnd)
    nodes = walk_control_tree(
        target,
        get_children=_wrapper_children,
        deadline=deadline,
        limit=UIA_MAX_NODES,
        max_depth=UIA_MAX_DEPTH,
    )
    infos: list[dict] = []
    for ctrl in nodes:
        if time.monotonic() >= deadline:
            break
        row = _node_info(ctrl)
        row["ctrl"] = None  # wrappers from the scan thread are not used for clicks
        infos.append(row)
    return infos


def _read_window(hwnd: int, *, announce: bool = False, timeout_s: float = UIA_READ_TIMEOUT_S) -> tuple[list[dict], bool]:
    """Read named controls with a timeout. Never freeze the copilot on Chromium descendants()."""
    global _UIA_WORKER
    if _UIA_WORKER is not None and _UIA_WORKER.is_alive():
        if announce:
            say("[Copilot] Previous window scan still running. Retrying shortly...")
        return [], True
    if announce:
        say("[Copilot] Reading the Chat Home Base window...")
    payload: dict[str, Any] = {"infos": [], "error": None}

    def work() -> None:
        try:
            if sys.platform == "win32":
                try:
                    import pythoncom

                    pythoncom.CoInitialize()
                except Exception:
                    pass
            payload["infos"] = _collect_window_infos(hwnd, time.monotonic() + timeout_s)
        except Exception as exc:
            payload["error"] = exc
        finally:
            if sys.platform == "win32":
                try:
                    import pythoncom

                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    worker = threading.Thread(target=work, daemon=True, name="chb-uia")
    _UIA_WORKER = worker
    worker.start()
    started = time.monotonic()
    while worker.is_alive() and (time.monotonic() - started) < timeout_s:
        worker.join(1.2)
        if worker.is_alive() and announce:
            say("[Copilot] Still reading the window...")
    timed_out = worker.is_alive()
    if payload["error"] is not None:
        say(f"[Copilot] Window read failed: {payload['error']}")
    infos = list(payload.get("infos") or [])
    named = [row for row in infos if str(row.get("name") or "").strip()]
    if announce:
        elapsed = time.monotonic() - started
        if timed_out:
            say(
                f"[Copilot] Stopped the window scan after {elapsed:.0f}s so PowerShell does not freeze. "
                f"Named controls so far: {len(named)}."
            )
        else:
            say(f"[Copilot] Saw {len(named)} named controls in {elapsed:.1f}s.")
    return infos, timed_out


def _iter_uia_controls(target: Any, limit: int = UIA_MAX_NODES):
    deadline = time.monotonic() + UIA_READ_TIMEOUT_S
    for ctrl in walk_control_tree(
        target,
        get_children=_wrapper_children,
        deadline=deadline,
        limit=limit,
        max_depth=UIA_MAX_DEPTH,
    ):
        yield ctrl


def _read_uia(hwnd: int, verbose: bool = True) -> tuple[str, list[Any]]:
    infos, _timed_out = _read_window(hwnd, announce=verbose)
    names = [str(row.get("name") or "") for row in infos if str(row.get("name") or "").strip()]
    nodes = [row.get("ctrl") for row in infos if row.get("ctrl") is not None]
    return "\n".join(names), nodes


def _send_vk(vk: int) -> None:
    _tap_vk(vk, shift=False)


def _send_ctrl_a() -> None:
    """Unused. Ctrl+A is skipped so we never brush the clipboard path."""
    return None


def _clear_focused_edit() -> None:
    """Backspace the focused field. Never clipboard paste. Never Enter. Never Ctrl+A."""
    for _ in range(24):
        _tap_vk(0x08, shift=False, hold_s=0.02)
        time.sleep(0.025)


def human_key_delay_s(ch: str, index: int) -> float:
    """Human-like pause. Fast enough for a 2-minute claim, slow enough to avoid auto-typing."""
    base = 0.18 + (index % 5) * 0.018
    if _EXTRA_SLOW_TYPING:
        base += 0.08
    if ch in ".!?":
        return base + 0.38
    if ch in ",;:":
        return base + 0.18
    if ch == " ":
        return base + 0.05
    return base


def keyboard_safe_text(text: str) -> str:
    """US-keyboard characters only. Curly quotes become ASCII. Skip anything else later."""
    out = text or ""
    for src, dst in (
        ("\u2018", "'"),
        ("\u2019", "'"),
        ("\u201c", '"'),
        ("\u201d", '"'),
        ("\u2013", "-"),
        ("\u2014", "-"),
        ("\u00a0", " "),
    ):
        out = out.replace(src, dst)
    return out


def _type_into_focused(text: str, delay_s: float = 0.13, extra_slow: bool = False) -> None:
    """US-keyboard virtual keys only. Never Ctrl, never clipboard, never Unicode SendInput."""
    del delay_s
    for index, ch in enumerate(keyboard_safe_text(text)):
        if ch in {"\n", "\r", "\t"}:
            continue
        pair = us_vk_for_char(ch)
        if pair is None:
            continue
        vk, shift = pair
        if vk in {0x11, 0x12}:
            continue
        _tap_vk(vk, shift=shift, hold_s=random.uniform(0.04, 0.09))
        pause = human_key_delay_s(ch, index) + random.uniform(0.04, 0.12)
        if extra_slow:
            pause += 0.10
        if index and index % 11 == 0:
            pause += random.uniform(0.12, 0.28)
        time.sleep(pause)


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


VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_OEM_1 = 0xBA
VK_OEM_PLUS = 0xBB
VK_OEM_COMMA = 0xBC
VK_OEM_MINUS = 0xBD
VK_OEM_PERIOD = 0xBE
VK_OEM_2 = 0xBF
VK_OEM_3 = 0xC0
VK_OEM_4 = 0xDB
VK_OEM_5 = 0xDC
VK_OEM_6 = 0xDD
VK_OEM_7 = 0xDE


def _us_char_vk_map() -> dict[str, tuple[int, bool]]:
    mapping: dict[str, tuple[int, bool]] = {" ": (0x20, False)}
    for idx, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        mapping[letter] = (0x41 + idx, True)
        mapping[letter.lower()] = (0x41 + idx, False)
    for idx, digit in enumerate("123456789"):
        mapping[digit] = (0x31 + idx, False)
    mapping["0"] = (0x30, False)
    for digit, mark in zip("1234567890", "!@#$%^&*()"):
        mapping[mark] = (mapping[digit][0], True)
    mapping.update(
        {
            ";": (VK_OEM_1, False),
            ":": (VK_OEM_1, True),
            "=": (VK_OEM_PLUS, False),
            "+": (VK_OEM_PLUS, True),
            ",": (VK_OEM_COMMA, False),
            "<": (VK_OEM_COMMA, True),
            "-": (VK_OEM_MINUS, False),
            "_": (VK_OEM_MINUS, True),
            ".": (VK_OEM_PERIOD, False),
            ">": (VK_OEM_PERIOD, True),
            "/": (VK_OEM_2, False),
            "?": (VK_OEM_2, True),
            "`": (VK_OEM_3, False),
            "~": (VK_OEM_3, True),
            "[": (VK_OEM_4, False),
            "{": (VK_OEM_4, True),
            "\\": (VK_OEM_5, False),
            "|": (VK_OEM_5, True),
            "]": (VK_OEM_6, False),
            "}": (VK_OEM_6, True),
            "'": (VK_OEM_7, False),
            '"': (VK_OEM_7, True),
        }
    )
    return mapping


_US_CHAR_VK = _us_char_vk_map()


def us_vk_for_char(ch: str) -> tuple[int, bool] | None:
    """US layout virtual key and shift. None means Unicode fallback. Never Ctrl."""
    if not ch:
        return None
    pair = _US_CHAR_VK.get(ch)
    if pair is None:
        return None
    vk, _shift = pair
    if vk == VK_CONTROL:
        return None
    return pair


def _tap_vk(vk: int, *, shift: bool, hold_s: float = 0.05) -> None:
    import ctypes

    if vk == VK_CONTROL:
        return
    user32 = ctypes.windll.user32
    scan = user32.MapVirtualKeyW(vk, 0)
    if shift:
        user32.keybd_event(VK_SHIFT, 0, 0, 0)
    user32.keybd_event(vk, scan, 0, 0)
    time.sleep(max(hold_s, 0.03))
    user32.keybd_event(vk, scan, 2, 0)
    if shift:
        user32.keybd_event(VK_SHIFT, 0, 2, 0)


def _send_unicode_char(ch: str) -> None:
    """Last-resort WM_CHAR. ASCII drafts should not reach here (apostrophe is VK_OEM_7)."""
    import ctypes
    from ctypes import wintypes

    extra = ctypes.c_ulong(0)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = (
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        )

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = (
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        )

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = (
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        )

    class INPUTUNION(ctypes.Union):
        _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT))

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = (("type", wintypes.DWORD), ("u", INPUTUNION))

    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_KEYUP = 0x0002
    INPUT_KEYBOARD = 1
    user32 = ctypes.windll.user32
    code = ord(ch)
    if code > 0xFFFF:
        return
    down = INPUT(type=INPUT_KEYBOARD)
    down.ki = KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, ctypes.pointer(extra))
    up = INPUT(type=INPUT_KEYBOARD)
    up.ki = KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, ctypes.pointer(extra))
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))


def _send_unicode(text: str, delay_s: float = 0.05) -> None:
    for ch in text:
        if ch in {"\n", "\r"}:
            continue
        pair = us_vk_for_char(ch)
        if pair is None:
            _send_unicode_char(ch)
        else:
            vk, shift = pair
            _tap_vk(vk, shift=shift)
        time.sleep(max(delay_s, 0.05))
