"""SensorFusionLab Review pane helpers (no Win32).

The Review sidebar shows Grammar suggestions with Ignore / Use. Red timeline
clips are fixed by clicking Use, never Submit. Empty clips show
"click to add text".
"""

from __future__ import annotations

import re
from typing import Any

WATCHED_RE = re.compile(r"Watched\s+(\d+)\s*%", re.I)
GRAMMAR_COUNT_RE = re.compile(r"grammar\s+(\d+)\s+clips?", re.I)
EMPTY_CLIP_PHRASES = (
    "click to add text",
    "click to add",
    "(empty clip)",
    "empty clip",
)


def parse_watched_percent(text: str) -> int | None:
    match = WATCHED_RE.search(text or "")
    if not match:
        return None
    return int(match.group(1))


def ocr_text(words: list[dict[str, Any]]) -> str:
    return " ".join(str(word.get("text") or "") for word in words)


def _norm(word: dict[str, Any] | str) -> str:
    if isinstance(word, str):
        return word.strip().lower()
    return str(word.get("text") or "").strip().lower()


def _center(word: dict[str, Any]) -> tuple[int, int]:
    x = int(word.get("x") or 0)
    y = int(word.get("y") or 0)
    w = int(word.get("w") or 0)
    h = int(word.get("h") or 0)
    return x + w // 2, y + h // 2


def find_review_use_clicks(
    words: list[dict[str, Any]],
    width: int,
    height: int,
) -> list[tuple[int, int]]:
    """Screen-relative-to-bitmap centers of Review 'Use' buttons.

    Ignores the left video area, the tab strip, the bottom timeline, and Submit.
    Prefers a Use that sits on the same row as Ignore (screenshot layout).
    """
    if width < 1 or height < 1:
        return []
    ignores = [_center(word) for word in words if _norm(word) == "ignore"]
    submits = [_center(word) for word in words if "submit" in _norm(word)]
    ranked: list[tuple[int, int, int]] = []
    for word in words:
        if _norm(word) != "use":
            continue
        cx, cy = _center(word)
        if cx < width * 0.50:
            continue
        if cy < height * 0.10 or cy > height * 0.70:
            continue
        if any(abs(sx - cx) < 90 and abs(sy - cy) < 36 for sx, sy in submits):
            continue
        score = 0
        if any(abs(ix - cx) < 160 and abs(iy - cy) < 28 for ix, iy in ignores):
            score += 10
        ranked.append((score, cx, cy))
    ranked.sort(key=lambda row: (-row[0], row[2], row[1]))
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []
    for _score, cx, cy in ranked:
        key = (cx // 8, cy // 8)
        if key in seen:
            continue
        seen.add(key)
        out.append((cx, cy))
    return out


def find_word_click(
    words: list[dict[str, Any]],
    needle: str,
    width: int,
    height: int,
    *,
    x_min_frac: float = 0.0,
    y_min_frac: float = 0.0,
    y_max_frac: float = 1.0,
) -> tuple[int, int] | None:
    want = needle.strip().lower()
    for word in words:
        if _norm(word) != want:
            continue
        cx, cy = _center(word)
        if cx < width * x_min_frac:
            continue
        if cy < height * y_min_frac or cy > height * y_max_frac:
            continue
        return cx, cy
    return None


def estimated_use_point(width: int, height: int) -> tuple[int, int]:
    """Fallback click inside the right-hand Review card (Grammar Use).

    Kept for tests/layout docs. The engine must not click this guess and
    count it as a successful caption write.
    """
    tab = min(max(int(height * 0.16), 110), 160)
    x = int(width * 0.88)
    y = tab + int((height - tab) * 0.22)
    return x, y


def find_phrase_click(
    words: list[dict[str, Any]],
    phrase: str,
    width: int,
    height: int,
    *,
    y_min_frac: float = 0.45,
    y_max_frac: float = 0.95,
    x_max_frac: float = 0.85,
) -> tuple[int, int] | None:
    """Click the center of a consecutive OCR phrase (timeline 'click to add text')."""
    tokens = [tok for tok in phrase.lower().split() if tok]
    if not tokens or width < 1 or height < 1:
        return None
    norms = [_norm(word) for word in words]
    for i in range(len(words) - len(tokens) + 1):
        if norms[i : i + len(tokens)] != tokens:
            continue
        first = _center(words[i])
        last = _center(words[i + len(tokens) - 1])
        cx = (first[0] + last[0]) // 2
        cy = (first[1] + last[1]) // 2
        if cy < height * y_min_frac or cy > height * y_max_frac:
            continue
        if cx > width * x_max_frac:
            continue
        return cx, cy
    return None


def is_play_control_label(name: str) -> bool:
    """True for the video Play button, not Playback speed / Playback mode."""
    n = (name or "").strip().casefold()
    if not n or n.startswith("playback"):
        return False
    return n in {"play", "play video", "play clip"}


def is_pause_control_label(name: str) -> bool:
    n = (name or "").strip().casefold()
    return n in {"pause", "pause video"} or n.startswith("pause ")


def playback_confirmed(names: list[str]) -> bool:
    """True only when Pause is visible. A Play click alone does not mean the video is playing."""
    return any(is_pause_control_label(n) for n in names)


def is_timeline_status_label(name: str) -> bool:
    n = (name or "").strip().casefold()
    return n in {"pending", "edited", "review", "idle"}


def should_recaption_false_idle(names: list[str]) -> bool:
    """QA is rejecting Idle (missing hands / 10 words / format), so rewrite; do not K-split."""
    action_errors = any(is_false_idle_review_error(n) for n in names)
    idle_long = any(is_idle_too_long_error(n) for n in names)
    idle_name = any((n or "").strip().casefold() == "idle" for n in names)
    if action_errors and (idle_name or idle_long):
        return True
    return bool(idle_name and action_errors)


def should_split_overlong_idle(names: list[str]) -> bool:
    """Split only a true Idle >5s. False-Idle action clips must be recaptioned instead."""
    if any(is_false_idle_review_error(n) for n in names):
        return False
    return any(is_idle_too_long_error(n) for n in names)


def full_timeline_xy(
    bar_rect: tuple[int, int, int, int],
    frac: float,
    window_rect: tuple[int, int, int, int],
) -> tuple[int, int]:
    """Click inside the Full Timeline *bar*, not the left-edge label or the window chrome."""
    left, top, right, bottom = bar_rect
    wleft, _wtop, ww, _wh = window_rect
    if (right - left) < 200:
        left = wleft + int(ww * 0.08)
        right = wleft + int(ww * 0.92)
        y = int((top + bottom) / 2) + 16
    else:
        y = int((top + bottom) / 2)
    frac = min(max(frac, 0.02), 0.98)
    x = int(left + (right - left) * frac)
    return x, y


def clip_export_cut_fractions(durations: list[float] | None, n_segments: int) -> list[float]:
    """Interior cut points so Clip Export lines up with each Sub-goal span."""
    if durations and len(durations) >= 2:
        total = sum(max(float(d), 0.01) for d in durations) or 1.0
        acc = 0.0
        out: list[float] = []
        for dur in durations[:-1]:
            acc += max(float(dur), 0.01)
            out.append(min(max(acc / total, 0.04), 0.96))
        return out
    n = max(int(n_segments), 2)
    return [i / n for i in range(1, n)]


def clip_export_needs_parallel_splits(names: list[str], subgoal_count: int) -> bool:
    """One filled Clip Export is not enough when QA still wants clips in parallel."""
    if not any(is_clip_export_missing_error(n) for n in names):
        return False
    if subgoal_count >= 2:
        return True
    pending = sum(1 for n in names if is_pending_clip_label(n))
    return pending <= 1


def is_review_use_label(name: str) -> bool:
    """True for the Grammar Review Use button (not Find & Replace / Submit)."""
    n = (name or "").strip().casefold()
    if not n or n in {"ignore", "similar", "review", "submit", "user"}:
        return False
    if "find" in n and "replace" in n:
        return False
    if "submit" in n:
        return False
    if n in {"use", "use suggestion", "apply"}:
        return True
    return n.startswith("use ") or n.endswith(" use")


def is_empty_clip_label(name: str) -> bool:
    """True for a timeline clip that still needs a caption."""
    n = (name or "").strip().casefold()
    if not n:
        return False
    if "click to add" in n or "add text" in n:
        return True
    if n in {"(empty clip)", "empty clip", "empty"}:
        return True
    if "placeholder" in n:
        return True
    return False


def is_quality_empty_error(name: str) -> bool:
    """Quality Assistant row that jumps to a clip with no caption."""
    n = (name or "").strip().casefold()
    if "in parallel" in n:
        return False
    if "must contain text" in n:
        return True
    if "clipexport" in n and "contain text" in n:
        return True
    return False


def is_clip_export_missing_error(name: str) -> bool:
    n = (name or "").strip().casefold().replace(" ", "")
    if "clipexport" not in n:
        return False
    return "inparallel" in n or "fullyfilled" in n


def is_idle_too_long_error(name: str) -> bool:
    n = (name or "").strip().casefold()
    if "idle" not in n:
        return False
    return "more than 5" in n or "split" in n


def is_false_idle_review_error(name: str) -> bool:
    """Review is rejecting Idle: this clip has action and needs a real caption."""
    n = (name or "").strip().casefold()
    if "at least 10 words" in n:
        return True
    if "format expected" in n:
        return True
    if "left hand" in n and "idle" in n and "unless" in n:
        return True
    return False


def is_ignore_all_label(name: str) -> bool:
    n = (name or "").strip().casefold()
    return n == "ignore all" or n == "ignoreall"


def is_grammar_row_label(name: str) -> bool:
    n = (name or "").strip().casefold()
    if is_ignore_all_label(n):
        return False
    return "grammar" in n and "clip" in n


def is_pending_clip_label(name: str) -> bool:
    n = (name or "").strip().casefold()
    return n == "pending" or n.startswith("pending ")


def is_split_control_label(name: str) -> bool:
    n = (name or "").strip().casefold()
    if not n or is_idle_too_long_error(n):
        return False
    if n in {"split", "split clip", "split sub-goal", "split subgoal"}:
        return True
    if n.startswith("split ") and "segment" not in n:
        return True
    return False


def is_create_clip_hint(name: str) -> bool:
    n = (name or "").strip().casefold()
    return "press k" in n or "click or press k" in n


def is_hte_label(name: str) -> bool:
    n = (name or "").strip().casefold()
    return "hand tracking" in n or n in {"hte", "hand_tracking_error"}


def is_timeline_kind_label(name: str) -> bool:
    n = (name or "").strip().casefold()
    return n in {"sub-goal", "subgoal", "clip export", "clip_export", "clipexport"}


def is_clip_export_tab(name: str) -> bool:
    n = (name or "").strip().casefold()
    if "sub-goal" in n or "subgoal" in n:
        return False
    if "parallel" in n or "fully filled" in n:
        return False
    return n in {"clip export", "clip_export", "clipexport"} or n == "clip export"


def timeline_dropdown_is_open(names: list[str]) -> bool:
    """True when the Sub-goal / ClipExport / HTE menu is still expanded."""
    kinds: set[str] = set()
    for name in names:
        if is_hte_label(name):
            kinds.add("hte")
        elif is_clip_export_tab(name):
            kinds.add("clip export")
        elif (name or "").strip().casefold() in {"sub-goal", "subgoal"}:
            kinds.add("sub-goal")
    return {"sub-goal", "clip export", "hte"} <= kinds


def selected_timeline_kind(names: list[str]) -> str | None:
    """Toolbar kind when the dropdown is closed. None if the menu is open."""
    if timeline_dropdown_is_open(names):
        return None
    for name in names:
        if is_hte_label(name) or is_clip_export_missing_error(name):
            continue
        if is_clip_export_tab(name):
            return "clip export"
        if (name or "").strip().casefold() in {"sub-goal", "subgoal"}:
            return "sub-goal"
    return None


def review_sidebar_open(names: list[str]) -> bool:
    return any((name or "").strip().casefold() == "review" for name in names)


def quality_linters_remaining(names: list[str]) -> bool:
    return any(
        is_idle_too_long_error(n) or is_clip_export_missing_error(n) or is_false_idle_review_error(n)
        for n in names
    )


def pick_idle_split_rects(
    named_rects: list[tuple[str, tuple[int, int, int, int]]],
    min_y: int,
) -> tuple[tuple[int, int, int, int] | None, tuple[int, int, int, int] | None]:
    """First Focused-Timeline Idle card and the pending clip to its right.

    Ignores the overlay Idle label on the video (higher on screen / smaller y).
    """
    idles: list[tuple[int, int, int, int]] = []
    pendings: list[tuple[int, int, int, int]] = []
    for name, rect in named_rects:
        left, top, _right, bottom = rect
        mid_y = (top + bottom) / 2
        if mid_y < min_y:
            continue
        n = (name or "").strip().casefold()
        if n == "idle":
            idles.append(rect)
        elif is_pending_clip_label(name):
            pendings.append(rect)
    if not idles:
        return None, None
    idle = min(idles, key=lambda row: (row[0], row[1]))
    next_pending = None
    idle_mid = (idle[1] + idle[3]) / 2
    for pending in pendings:
        if pending[0] <= idle[0] + 8:
            continue
        pending_mid = (pending[1] + pending[3]) / 2
        if abs(pending_mid - idle_mid) > 90:
            continue
        if next_pending is None or pending[0] < next_pending[0]:
            next_pending = pending
    return idle, next_pending


def idle_card_split_xy(
    idle_rect: tuple[int, int, int, int],
    next_rect: tuple[int, int, int, int] | None,
    fraction: float = 0.45,
) -> tuple[int, int]:
    """Click inside the Idle *card*, not the tiny Idle word.

    The UIA Idle control is a short label at the left of the 5.5s card. 45% of
    the gap to the next pending is ~2.5s; 90% is ~5.0s.
    """
    left, top, right, bottom = idle_rect
    if next_rect is not None and next_rect[0] > left + 8:
        span = max(next_rect[0] - left, 1)
    else:
        width = max(right - left, 1)
        span = width if width >= 80 else 200
    x = int(left + span * fraction)
    y = int((top + bottom) / 2)
    return x, y


def clip_export_needs_new_clip(names: list[str]) -> bool:
    """Press K only when Clip Export has no clip to type into."""
    for name in names:
        n = (name or "").strip().casefold()
        if is_pending_clip_label(name):
            return False
        if is_empty_clip_label(name):
            return False
        if "the person" in n or "focus annotation" in n:
            return False
    return True


def is_clip_export_placeholder(text: str) -> bool:
    n = (text or "").casefold()
    if "kitchen" in n or "refrigerator" in n:
        return False
    if "the person stands at" in n:
        return True
    if "indoor room" in n and "household demonstration" in n:
        return True
    return False


def parse_grammar_clip_count(text: str) -> int | None:
    match = GRAMMAR_COUNT_RE.search(text or "")
    if not match:
        return None
    return int(match.group(1))


def review_work_remaining(text: str) -> bool:
    n = (text or "").casefold()
    count = parse_grammar_clip_count(n)
    if count:
        return True
    if "click to add" in n or "must contain text" in n:
        return True
    if "fully filled" in n or "in parallel" in n:
        return True
    if "more than 5" in n and "idle" in n:
        return True
    return False


def is_quality_assistant_text(text: str) -> bool:
    n = (text or "").casefold()
    return "quality assistant" in n or "must contain text" in n


def should_skip_watch(
    watched_pct: int | None,
    *,
    use_ready: bool = False,
    quality_ready: bool = False,
) -> bool:
    """Skip another 1x watch when Review is already on screen.

    Empty clips alone do not skip the required first watch.
    """
    if watched_pct is not None and watched_pct >= 80:
        return True
    return bool(use_ready or quality_ready)


def interesting_uia_names(names: list[str], limit: int = 60) -> list[str]:
    """Prefer Review / timeline labels when logging the accessibility tree."""
    keys = (
        "use",
        "ignore",
        "click to add",
        "add text",
        "idle",
        "quality",
        "watched",
        "play",
        "submit",
        "pending",
        "sub-goal",
        "review",
        "empty",
        "export",
        "grammar",
        "split",
        "parallel",
        "error",
    )
    ranked = [n for n in names if any(k in n.casefold() for k in keys)]
    if ranked:
        return ranked[:limit]
    return names[:limit]
