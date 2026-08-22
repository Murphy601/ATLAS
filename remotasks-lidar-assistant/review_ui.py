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
    x_min_frac: float = 0.0,
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
        if cx < width * x_min_frac or cx > width * x_max_frac:
            continue
        return cx, cy
    return None


def find_caption_field_click(
    words: list[dict[str, Any]],
    phrase: str,
    width: int,
    height: int,
) -> tuple[int, int] | None:
    """Click a caption in Focused Timeline or the Review sidebar, never the video overlay."""
    hit = find_phrase_click(
        words,
        phrase,
        width,
        height,
        y_min_frac=0.62,
        y_max_frac=0.92,
        x_min_frac=0.02,
        x_max_frac=0.88,
    )
    if hit:
        return hit
    return find_phrase_click(
        words,
        phrase,
        width,
        height,
        y_min_frac=0.10,
        y_max_frac=0.58,
        x_min_frac=0.62,
        x_max_frac=0.99,
    )


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
    """Focused Timeline clip chips. The Review tab is not a clip."""
    n = (name or "").strip().casefold()
    return n in {"pending", "edited", "idle", "done"}


def sort_hits_by_y(hits: list[tuple]) -> list[tuple]:
    """Sort click targets by y (or x) only. Never compare UIA wrapper objects."""
    return sorted(hits, key=lambda row: row[0])


def count_subgoal_spans(names: list[str], ocr_blob: str = "") -> int:
    """How many Sub-goal cards to mirror on Clip Export.

    Visible UIA chips are often only the on-screen cards. Prefer the largest
    of chips, OCR 'done', duration labels, and action captions.
    """
    chips = sum(1 for name in names if is_timeline_status_label(name))
    done = len(re.findall(r"\bdone\b", ocr_blob or "", re.I))
    durs = len(clip_durations_from_ocr(ocr_blob))
    caps = sum(1 for name in names if looks_like_neighbor_action(name))
    best = max(chips, done, durs, caps)
    return best if best >= 2 else 0


NEIGHBOR_ACTION_VERBS = (
    "grab",
    "shake",
    "unstack",
    "fold",
    "smooth",
    "drop",
    "transfer",
    "put",
    "hold",
    "pick",
    "place",
    "move",
)
NEIGHBOR_ACTION_OBJECTS = (
    "pants",
    "shirt",
    "blouse",
    "table",
    "laundry",
    "jar",
    "bowl",
    "basin",
)
MIN_IDLE_NEIGHBOR_GAP = 150
MIN_IDLE_CARD_SPAN = 280


def looks_like_neighbor_action(name: str) -> bool:
    """True for a real Sub-goal caption next to Idle (not a QA error row)."""
    text = (name or "").strip()
    if len(text) < 12:
        return False
    lowered = text.casefold()
    if lowered.startswith(("error", "warning")):
        return False
    if "quality assistant" in lowered or "unless" in lowered:
        return False
    if "must " in lowered or "must contain" in lowered:
        return False
    if "hand" in lowered:
        return True
    padded = f" {lowered} "
    if any(f" {verb} " in padded or lowered.startswith(verb) for verb in NEIGHBOR_ACTION_VERBS):
        return any(obj in lowered for obj in NEIGHBOR_ACTION_OBJECTS)
    return False


def neighbor_action_captions(names: list[str]) -> bool:
    return any(looks_like_neighbor_action(n) for n in names)


def idle_is_opening_clip(
    named_rects: list[tuple[str, tuple[int, int, int, int]]] | None,
    min_y: int = 0,
) -> bool:
    """True when Idle is the first Focused Timeline card (no action to its left).

    Mid-video Idle after a Grab/Shake card is a real pause and must be K-split.
    Names-only callers pass no rects and are treated as opening so neighbor
    laundry captions can still trigger a recaption.
    """
    if not named_rects:
        return True
    idles: list[tuple[int, int, int, int]] = []
    actions: list[tuple[int, int, int, int]] = []
    for name, rect in named_rects:
        _left, top, _right, bottom = rect
        mid_y = (top + bottom) / 2
        if min_y and mid_y < min_y:
            continue
        if (name or "").strip().casefold() == "idle":
            idles.append(rect)
        elif looks_like_neighbor_action(name):
            actions.append(rect)
    if not idles:
        return True
    idle = min(idles, key=lambda row: (row[0], row[1]))
    idle_mid = (idle[1] + idle[3]) / 2
    for act in actions:
        act_mid = (act[1] + act[3]) / 2
        if abs(act_mid - idle_mid) > 90:
            continue
        if act[0] + 8 < idle[0]:
            return False
    return True


def should_recaption_false_idle(
    names: list[str],
    named_rects: list[tuple[str, tuple[int, int, int, int]]] | None = None,
    min_y: int = 0,
) -> bool:
    """Rewrite a first-clip Idle that is actually action. Do not K-split that card."""
    action_errors = any(is_false_idle_review_error(n) for n in names)
    idle_long = any(is_idle_too_long_error(n) for n in names)
    idle_name = any((n or "").strip().casefold() == "idle" for n in names)
    empty = any(is_empty_clip_label(n) for n in names)
    if action_errors and (idle_name or idle_long or empty):
        return True
    if idle_name and idle_long and neighbor_action_captions(names):
        return idle_is_opening_clip(named_rects, min_y)
    return False


def should_split_overlong_idle(
    names: list[str],
    named_rects: list[tuple[str, tuple[int, int, int, int]]] | None = None,
    min_y: int = 0,
) -> bool:
    """Split only a true Idle >5s. Opening false-Idle must be recaptioned instead."""
    if should_recaption_false_idle(names, named_rects, min_y):
        return False
    if any(is_false_idle_review_error(n) for n in names):
        return False
    return any(is_idle_too_long_error(n) for n in names)


def should_fill_clip_export(names: list[str], already_filled: bool = False) -> bool:
    """Fill Clip Export whenever QA still lists Clip Export rows, or once from Sub-goals."""
    if has_clip_export_quality_error(names):
        return True
    if already_filled:
        return False
    return neighbor_action_captions(names)


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
    """Interior cut points from real Sub-goal durations. Never equal-percentage guesses."""
    del n_segments
    if not durations or len(durations) < 2:
        return []
    total = sum(max(float(d), 0.01) for d in durations) or 1.0
    acc = 0.0
    out: list[float] = []
    for dur in durations[:-1]:
        acc += max(float(dur), 0.01)
        frac = acc / total
        if 0.04 <= frac <= 0.96:
            out.append(frac)
    return out


def clip_export_end_fractions_from_status_rects(
    rects: list[tuple[int, int, int, int]],
    timeline_left: int,
    timeline_right: int,
) -> list[float]:
    """Sub-goal ends as Full Timeline fractions.

    Status chips sit at the start of each clip. The next chip's left edge is this
    clip's end, which Clip Export must match. The last clip already ends at the
    bar's right, so it is not a K-cut.
    """
    if len(rects) < 2 or timeline_right <= timeline_left:
        return []
    span = float(timeline_right - timeline_left)
    ordered = sorted(rects, key=lambda row: row[0])
    deduped: list[tuple[int, int, int, int]] = []
    for rect in ordered:
        if deduped and rect[0] - deduped[-1][0] < MIN_IDLE_NEIGHBOR_GAP:
            continue
        deduped.append(rect)
    out: list[float] = []
    for nxt in deduped[1:]:
        frac = (nxt[0] - timeline_left) / span
        if 0.04 <= frac <= 0.96:
            out.append(round(frac, 4))
    return out


def clip_export_end_fractions_from_times(
    end_times: list[float], total_s: float | None = None
) -> list[float]:
    """Interior Clip Export K-cuts from Sub-goal end seconds (not equal-percentage guesses)."""
    if not end_times:
        return []
    last = max(float(end_times[-1]), 0.01)
    span = float(total_s) if total_s and total_s > last + 0.2 else last
    cuts = list(end_times) if total_s and total_s > last + 0.2 else list(end_times[:-1])
    out: list[float] = []
    for end in cuts:
        frac = float(end) / span
        if 0.04 <= frac <= 0.96:
            out.append(round(frac, 4))
    return out


def clip_export_slot_mid_fractions(end_fracs: list[float], n_slots: int) -> list[float]:
    """Playhead positions in the middle of each Clip Export span after Sub-goal-end cuts."""
    n = max(int(n_slots or 0), 1)
    bounds = [0.0]
    for frac in end_fracs or []:
        f = max(0.02, min(0.98, float(frac)))
        if all(abs(f - b) > 0.02 for b in bounds):
            bounds.append(f)
    bounds.append(1.0)
    bounds.sort()
    mids = [round((bounds[i] + bounds[i + 1]) / 2, 4) for i in range(len(bounds) - 1)]
    if len(mids) >= n:
        return mids[:n]
    return [round((i + 0.45) / n, 4) for i in range(n)]


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
    """Quality Assistant row that jumps to a Sub-goal clip with no caption.

    Clip Export empty/short rows are filled by the Clip Export pass, not by
    typing Idle into whatever field this click opens.
    """
    n = (name or "").strip().casefold()
    compact = n.replace(" ", "")
    if "clipexport" in compact or "clip export" in n:
        return False
    if "in parallel" in n:
        return False
    return "must contain text" in n


def is_clip_export_missing_error(name: str) -> bool:
    n = (name or "").strip().casefold().replace(" ", "")
    if "clipexport" not in n:
        return False
    return "inparallel" in n or "fullyfilled" in n


def is_clip_export_empty_error(name: str) -> bool:
    n = (name or "").strip().casefold()
    compact = n.replace(" ", "")
    if "clipexport" not in compact and "clip export" not in n:
        return False
    return "contain text" in n or "must contain" in n


def is_clip_export_short_error(name: str) -> bool:
    n = (name or "").strip().casefold()
    compact = n.replace(" ", "")
    if "clipexport" not in compact and "clip export" not in n:
        return False
    return "15 word" in n or "at least 15" in n


def is_clip_export_duplicate_timeline(name: str) -> bool:
    n = (name or "").strip().casefold()
    if "more than one timeline" not in n:
        return False
    return "clipexport" in n.replace(" ", "") or "clip export" in n or "same type" in n


def has_clip_export_quality_error(names: list[str]) -> bool:
    return any(
        is_clip_export_missing_error(n)
        or is_clip_export_hands_error(n)
        or is_clip_export_end_mismatch(n)
        or is_clip_export_empty_error(n)
        or is_clip_export_short_error(n)
        or is_clip_export_duplicate_timeline(n)
        for n in names
    )


def fillable_clip_export_qa(names: list[str]) -> bool:
    """True for Clip Export rows the engine can still fix. Duplicate-only is not fillable."""
    return any(
        is_clip_export_missing_error(n)
        or is_clip_export_hands_error(n)
        or is_clip_export_end_mismatch(n)
        or is_clip_export_empty_error(n)
        or is_clip_export_short_error(n)
        for n in names
    )


def duplicate_clip_export_only(names: list[str], text: str = "") -> bool:
    """Extra Clip Export track with no empty/parallel/end-match work left."""
    blob = "\n".join([*(names or []), text or ""])
    has_dup = any(is_clip_export_duplicate_timeline(n) for n in names or []) or (
        "more than one timeline" in blob.casefold()
    )
    return has_dup and not fillable_clip_export_qa(names or []) and not fixable_review_work_remaining(blob)


def is_clip_export_end_mismatch(name: str) -> bool:
    n = (name or "").strip().casefold()
    compact = n.replace(" ", "")
    if "endmustmatch" in compact:
        return True
    return "clip" in n and "end must match" in n


def is_clip_export_hands_error(name: str) -> bool:
    n = (name or "").strip().casefold()
    if "hand" not in n:
        return False
    compact = n.replace(" ", "")
    return "clipexport" in compact or "clip export" in n


def is_clip_export_style_caption(name: str) -> bool:
    """True for a third-person Clip Export sentence, not a Sub-goal."""
    return (name or "").strip().casefold().startswith("the person")


def clip_export_caption_needs_rewrite(name: str) -> bool:
    """Old Clip Export text that still fails QA (hands, hold, on the blouse)."""
    n = (name or "").strip().casefold()
    if not n.startswith("the person"):
        return False
    if "hand" in n:
        return True
    if " on the blouse" in n or " on the shirt" in n or " on the pants" in n:
        return True
    if re.search(r"\bhold the\b", n) or re.search(r"\bfold the\b", n):
        return True
    return False


def clip_export_other_caption_does_not_block_fill(names: list[str]) -> bool:
    """A The-person sentence on another chip must not skip an empty slot."""
    if any(is_empty_clip_label(n) for n in names):
        return True
    if any(clip_export_caption_needs_rewrite(n) for n in names):
        return True
    return False


def is_clip_export_caption_label(name: str) -> bool:
    """True for a Clip Export caption field, not a Quality Assistant error row."""
    n = (name or "").strip()
    if len(n) < 20:
        return False
    lowered = n.casefold()
    if lowered.startswith("error") or lowered.startswith("warning"):
        return False
    if "must not" in lowered or "must be" in lowered or "must match" in lowered:
        return False
    if (
        is_clip_export_missing_error(n)
        or is_clip_export_hands_error(n)
        or is_clip_export_end_mismatch(n)
        or is_clip_export_empty_error(n)
        or is_clip_export_short_error(n)
        or is_clip_export_duplicate_timeline(n)
    ):
        return False
    return lowered.startswith("the person") or ("the person" in lowered and "hand" in lowered)


def is_slow_around_transitions_label(name: str) -> bool:
    n = (name or "").strip().casefold()
    return "slow around" in n


def is_ignore_warning_label(name: str) -> bool:
    """Single Ignore on a QA warning. Never Ignore all."""
    return (name or "").strip().casefold() == "ignore"


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


def is_clip_export_review_chip(name: str) -> bool:
    """Focused Timeline chip on Clip Export. review/done/pending, not the Review tab."""
    n = (name or "").strip()
    if n == "Review":
        return False
    return n.casefold() in {"review", "done", "pending"}


MIN_CLIP_EXPORT_CHIP_GAP = 150


def pick_clip_export_review_rects(
    named_rects: list[tuple[str, tuple[int, int, int, int]]],
    min_y: int,
) -> list[tuple[int, int, int, int]]:
    """Left-to-right Clip Export cards on Focused Timeline (not the Review tab)."""
    chips: list[tuple[int, int, int, int]] = []
    for name, rect in named_rects:
        if is_hte_clip_caption(name):
            continue
        if not (
            is_clip_export_review_chip(name) or is_clip_export_style_caption(name)
        ):
            continue
        _left, top, _right, bottom = rect
        if (top + bottom) / 2 < min_y:
            continue
        chips.append(rect)
    chips.sort(key=lambda row: (row[0], row[1]))
    out: list[tuple[int, int, int, int]] = []
    for rect in chips:
        if out and rect[0] - out[-1][0] < MIN_CLIP_EXPORT_CHIP_GAP:
            continue
        out.append(rect)
    return out


def pick_review_description_rects(
    named_rects: list[tuple[str, tuple[int, int, int, int]]],
    win_left: int,
    win_top: int,
    win_width: int,
    win_height: int,
) -> list[tuple[int, int, int, int]]:
    """Review sidebar editor: empty 'click to add text' or an existing The-person caption."""
    if win_width < 1 or win_height < 1:
        return []
    min_x = win_left + int(win_width * 0.48)
    max_y = win_top + int(win_height * 0.58)
    placeholders: list[tuple[int, int, int, int]] = []
    captions: list[tuple[int, int, int, int]] = []
    for name, rect in named_rects:
        n = (name or "").strip().casefold()
        if n in {"(empty clip)", "empty clip"}:
            continue
        if is_hte_clip_caption(name):
            continue
        is_placeholder = "click to add" in n or "add text" in n
        is_caption = is_clip_export_style_caption(name)
        if not is_placeholder and not is_caption:
            continue
        cx = (rect[0] + rect[2]) / 2
        cy = (rect[1] + rect[3]) / 2
        if cx < min_x or cy > max_y:
            continue
        if is_placeholder:
            placeholders.append(rect)
        else:
            captions.append(rect)
    placeholders.sort(key=lambda row: (row[1], row[0]))
    captions.sort(key=lambda row: (row[1], row[0]))
    return placeholders + captions


def review_description_click_xy(rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """Click inside the description box, a bit below the placeholder label."""
    left, top, right, bottom = rect
    x = int((left + right) / 2)
    y = int((top + bottom) / 2) + max(14, int(max(bottom - top, 1) * 0.35))
    return x, y


def review_description_fallback_xy(width: int, height: int) -> tuple[int, int]:
    """Review description box: between the video and Quality Assistant."""
    return int(width * 0.70), int(height * 0.30)


def is_plausible_edit_rect(rect: tuple[int, int, int, int]) -> bool:
    """True for a compact placeholder, not a window-wide Chromium container."""
    width = rect[2] - rect[0]
    height = rect[3] - rect[1]
    return 60 <= width <= 520 and 14 <= height <= 160


def pick_click_to_add_text_target(
    named_rects: list[tuple[str, tuple[int, int, int, int]]],
    win_left: int,
    win_top: int,
    win_width: int,
    win_height: int,
) -> tuple[tuple[int, int, int, int], tuple[int, int]] | None:
    """One click on the real 'click to add text' field. Never a giant chrome box center."""
    ranked: list[tuple[int, int, tuple[int, int, int, int]]] = []
    for name, rect in named_rects:
        n = (name or "").strip().casefold()
        if "click to add" not in n and n != "add text":
            continue
        if n in {"(empty clip)", "empty clip"}:
            continue
        width = rect[2] - rect[0]
        score = 0
        if is_plausible_edit_rect(rect):
            score += 50
        if width > 700:
            score -= 30
        cy = (rect[1] + rect[3]) / 2
        cx = (rect[0] + rect[2]) / 2
        if win_height and cy > win_top + win_height * 0.60:
            score += 10
        if (
            win_width
            and cx > win_left + win_width * 0.52
            and cy < win_top + win_height * 0.58
            and is_plausible_edit_rect(rect)
        ):
            score += 15
        ranked.append((score, width, rect))
    if not ranked:
        return None
    ranked.sort(key=lambda row: (-row[0], row[1]))
    rect = ranked[0][2]
    if is_plausible_edit_rect(rect):
        return rect, review_description_click_xy(rect)
    x = int(rect[0] + max(rect[2] - rect[0], 1) * 0.72)
    y = int((rect[1] + rect[3]) / 2)
    return rect, (x, y)


def should_skip_observe(watched_pct: int | None, names: list[str] | None = None) -> bool:
    """When Watched is already high, do not replay 24s. QA rows are often missing from UIA."""
    del names
    return watched_pct is not None and watched_pct >= 80


def should_snap_clip_export_ends(
    names: list[str],
    *,
    chip_count: int = 0,
    duplicate: bool = False,
) -> bool:
    """K-split on Focused Timeline when ends or parallel slots are still wrong.

    A second Full Timeline track is a different problem. Focused Timeline K does
    not create another Clip Export type.
    """
    del duplicate
    if any(is_clip_export_end_mismatch(n) for n in names):
        return True
    if any(is_clip_export_missing_error(n) for n in names):
        return True
    if chip_count >= 2:
        return False
    if any(is_clip_export_review_chip(n) for n in names) and any(is_empty_clip_label(n) for n in names):
        return False
    if any(is_clip_export_empty_error(n) or is_clip_export_short_error(n) for n in names):
        return False
    return True


QA_FRAME_RE = re.compile(r"on frames?:\s*([\d,\s]+)", re.I)


def qa_end_mismatch_seconds(names: list[str], fps: float = 30.0) -> list[float]:
    """Frame 297 at 30 fps is the 9.9s first Sub-goal end."""
    times: list[float] = []
    rate = max(float(fps or 30.0), 1.0)
    for name in names:
        if not is_clip_export_end_mismatch(name):
            continue
        for match in QA_FRAME_RE.finditer(name or ""):
            for tok in match.group(1).split(","):
                tok = tok.strip()
                if tok.isdigit():
                    times.append(round(int(tok) / rate, 3))
    return times


def clip_durations_from_ocr(blob: str) -> list[float]:
    """Timeline card lengths like 9.9s / 27.0s / 5.3s. Ignore FPS and Watched 100."""
    vals: list[float] = []
    for raw in re.findall(r"(\d+(?:\.\d+)?)\s*s\b", blob or "", flags=re.I):
        val = float(raw)
        if 0.4 <= val <= 180 and val not in {15.0, 60.0}:
            vals.append(val)
    return vals


def duration_end_fractions(durations: list[float]) -> list[float]:
    """Clip ends as fractions of the summed card lengths."""
    if not durations:
        return []
    total = sum(max(float(d), 0.01) for d in durations) or 1.0
    acc = 0.0
    out: list[float] = []
    for dur in durations[:-1]:
        acc += max(float(dur), 0.01)
        frac = acc / total
        if 0.04 <= frac <= 0.96:
            out.append(round(frac, 4))
    return out


def clip_export_interior_cut_fracs(
    needed: list[float],
    existing: list[float],
    min_sep: float = 0.03,
) -> list[float]:
    """Sub-goal ends that are not already a Clip Export card edge."""
    out: list[float] = []
    for frac in needed or []:
        f = max(0.04, min(0.96, float(frac)))
        if any(abs(f - seen) < min_sep for seen in (existing or [])):
            continue
        if any(abs(f - seen) < min_sep for seen in out):
            continue
        out.append(round(f, 4))
    return out


def long_card_interior_fracs(
    durations: list[float], max_ok: float = 10.0, step_s: float = 5.0
) -> list[float]:
    """A 27s Clip Export covers several Sub-goals; cut inside that card, not on its ends."""
    if not durations:
        return []
    total = sum(max(float(d), 0.01) for d in durations) or 1.0
    acc = 0.0
    out: list[float] = []
    for dur in durations:
        start = acc
        acc += max(float(dur), 0.01)
        if float(dur) <= max_ok:
            continue
        t = start + max(float(step_s), 2.0)
        while t < acc - 1.0:
            frac = t / total
            if 0.04 <= frac <= 0.96:
                out.append(round(frac, 4))
            t += max(float(step_s), 2.0)
    return out


def clip_export_visible_card_count(chip_count: int, duration_count: int) -> int:
    """Write the cards on screen, not a guessed 9-slot list."""
    return max(int(chip_count or 0), int(duration_count or 0), 1)


def pick_ocr_duration_centers(
    words: list[dict[str, Any]], min_y: int
) -> list[tuple[int, int, float]]:
    """Focused Timeline duration chips such as 9.9s / 27.0s / 5.3s."""
    hits: list[tuple[int, int, float]] = []
    for word in words or []:
        text = str(word.get("text") or "").strip()
        match = re.fullmatch(r"(\d+(?:\.\d+)?)s", text, flags=re.I)
        if not match:
            continue
        val = float(match.group(1))
        if val < 0.4 or val > 180 or val in {15.0, 60.0}:
            continue
        cx, cy = _center(word)
        if cy < min_y:
            continue
        hits.append((cx, cy, val))
    hits.sort(key=lambda row: row[0])
    out: list[tuple[int, int, float]] = []
    for row in hits:
        if out and row[0] - out[-1][0] < 80:
            continue
        out.append(row)
    return out


def should_open_subgoal_pending(names: list[str]) -> bool:
    """Do not leave Clip Export to sit on a Sub-goal pending / red playhead."""
    return not has_clip_export_quality_error(names)


def is_quality_run_now_label(name: str) -> bool:
    n = (name or "").strip().casefold()
    return n in {"run now", "run", "rerun"} or n.startswith("run now")


def clip_export_caption_committed(
    names: list[str], ocr_blob: str = "", typed: str = ""
) -> bool:
    """True when a Clip Export field kept a The-person sentence after typing."""
    if any(is_clip_export_caption_label(n) for n in names):
        return True
    snippet = " ".join((typed or "").split()[:6]).casefold()
    if len(snippet) >= 12:
        blob = " ".join(names) + " " + (ocr_blob or "")
        if snippet in blob.casefold():
            return True
    return False


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


def is_hte_clip_caption(name: str) -> bool:
    """HTE track text. Never type or K-split this as a Clip Export."""
    n = (name or "").strip().casefold()
    compact = n.replace(" ", "_")
    return "missing_hand" in n or compact in {
        "missing_hand_predictions",
        "hand_tracking_error",
    }


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
        if is_clip_export_missing_error(name):
            continue
        if is_hte_label(name):
            return "hte"
        if is_clip_export_tab(name):
            return "clip export"
        if (name or "").strip().casefold() in {"sub-goal", "subgoal"}:
            return "sub-goal"
    return None


def should_stop_clip_export_k(
    chip_count_before: int, chip_count_after: int, names: list[str]
) -> bool:
    """Stop Focused Timeline K if it did not add a Clip Export card or landed on HTE."""
    if selected_timeline_kind(names) == "hte":
        return True
    if any(is_hte_clip_caption(n) for n in names):
        return True
    return chip_count_after <= chip_count_before


def review_sidebar_open(names: list[str]) -> bool:
    return any((name or "").strip().casefold() == "review" for name in names)


def quality_linters_remaining(names: list[str]) -> bool:
    return any(
        is_idle_too_long_error(n)
        or is_clip_export_missing_error(n)
        or is_clip_export_hands_error(n)
        or is_clip_export_empty_error(n)
        or is_clip_export_short_error(n)
        or is_clip_export_duplicate_timeline(n)
        or is_clip_export_end_mismatch(n)
        or is_false_idle_review_error(n)
        for n in names
    )


def pick_idle_split_rects(
    named_rects: list[tuple[str, tuple[int, int, int, int]]],
    min_y: int,
) -> tuple[tuple[int, int, int, int] | None, tuple[int, int, int, int] | None]:
    """First Focused-Timeline Idle card and the next real clip to its right.

    Ignores the overlay Idle label on the video (higher on screen / smaller y).
    The pending chip sitting on the same Idle card (~40px to the right of the
    Idle word) is not a card boundary; K on that chip does nothing.
    """
    idles: list[tuple[int, int, int, int]] = []
    boundaries: list[tuple[int, int, int, int]] = []
    for name, rect in named_rects:
        left, top, _right, bottom = rect
        mid_y = (top + bottom) / 2
        if mid_y < min_y:
            continue
        n = (name or "").strip().casefold()
        if n == "idle":
            idles.append(rect)
        elif is_pending_clip_label(name) or looks_like_neighbor_action(name):
            boundaries.append(rect)
    if not idles:
        return None, None
    idle = min(idles, key=lambda row: (row[0], row[1]))
    next_hit = None
    idle_mid = (idle[1] + idle[3]) / 2
    for cand in boundaries:
        if cand[0] - idle[0] < MIN_IDLE_NEIGHBOR_GAP:
            continue
        cand_mid = (cand[1] + cand[3]) / 2
        if abs(cand_mid - idle_mid) > 90:
            continue
        if next_hit is None or cand[0] < next_hit[0]:
            next_hit = cand
    if next_hit is None:
        expanded = (
            idle[0],
            idle[1],
            max(idle[2], idle[0] + MIN_IDLE_CARD_SPAN),
            idle[3],
        )
        return expanded, None
    return idle, next_hit


def idle_card_split_xy(
    idle_rect: tuple[int, int, int, int],
    next_rect: tuple[int, int, int, int] | None,
    fraction: float = 0.45,
) -> tuple[int, int]:
    """Click inside the Idle *card*, not the tiny Idle word.

    The UIA Idle control is a short label at the left of the 9.9s card. 45% of
    the gap to the next pending is ~4.5s; 90% is ~9.0s.
    """
    left, top, right, bottom = idle_rect
    if next_rect is not None and next_rect[0] >= left + MIN_IDLE_NEIGHBOR_GAP:
        span = max(next_rect[0] - left, 1)
    else:
        width = max(right - left, 1)
        span = width if width >= MIN_IDLE_CARD_SPAN else MIN_IDLE_CARD_SPAN
    x = int(left + span * fraction)
    y = int((top + bottom) / 2)
    return x, y


def clip_export_needs_new_clip(names: list[str]) -> bool:
    """Press K only when Clip Export has no clip to type into.

    Empty/short/parallel QA rows mean clips already exist. A second K on Full
    Timeline creates another Clip Export track (QA: more than one timeline).
    """
    if any(is_clip_export_duplicate_timeline(n) for n in names):
        return False
    if any(
        is_clip_export_empty_error(n)
        or is_clip_export_short_error(n)
        or is_clip_export_missing_error(n)
        for n in names
    ):
        return False
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


def fixable_review_work_remaining(text: str) -> bool:
    """True when Grammar / empty / parallel / end-match still need a click or type.

    A leftover second Clip Export track cannot be deleted safely.
    """
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
    if "at least 15" in n or "15 word" in n:
        return True
    if "end must match" in n:
        return True
    return False


def review_work_remaining(text: str) -> bool:
    n = (text or "").casefold()
    if fixable_review_work_remaining(n):
        return True
    if "more than one timeline" in n:
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
    """Skip the required 1x watch only after Watched is already high.

    Quality Assistant reds and Review Use do not mean the video was watched.
    Watched 0% / 48% must still play the full clip.
    """
    del use_ready, quality_ready
    return watched_pct is not None and watched_pct >= 80


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
        "done",
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
