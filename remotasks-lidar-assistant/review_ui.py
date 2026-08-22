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


def is_clip_export_tab(name: str) -> bool:
    n = (name or "").strip().casefold()
    if "sub-goal" in n or "subgoal" in n:
        return False
    return n in {"clip export", "clip_export", "clipexport"} or "clip export" in n


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
