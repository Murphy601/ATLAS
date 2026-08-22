"""SensorFusionLab Review pane helpers (no Win32).

The Review sidebar shows Grammar suggestions with Ignore / Use. Red timeline
clips are fixed by clicking Use, never Submit.
"""

from __future__ import annotations

import re
from typing import Any

WATCHED_RE = re.compile(r"Watched\s+(\d+)\s*%", re.I)


def parse_watched_percent(text: str) -> int | None:
    match = WATCHED_RE.search(text or "")
    if not match:
        return None
    return int(match.group(1))


def ocr_text(words: list[dict[str, Any]]) -> str:
    return " ".join(str(word.get("text") or "") for word in words)


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
    """Fallback click inside the right-hand Review card (Grammar Use)."""
    tab = min(max(int(height * 0.16), 110), 160)
    x = int(width * 0.88)
    y = tab + int((height - tab) * 0.22)
    return x, y


def _norm(word: dict[str, Any]) -> str:
    return str(word.get("text") or "").strip().lower()


def _center(word: dict[str, Any]) -> tuple[int, int]:
    x = int(word.get("x") or 0)
    y = int(word.get("y") or 0)
    w = int(word.get("w") or 0)
    h = int(word.get("h") or 0)
    return x + w // 2, y + h // 2
