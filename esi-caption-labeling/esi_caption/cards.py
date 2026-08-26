"""Parse L3/L2 sidebar cards from UIA names."""

from __future__ import annotations

import re

from .planner import timestamp_to_seconds

RANGE_RE = re.compile(r"^(\d+:\d+(?:\.\d+)?)\s*[-–]\s*(\d+:\d+(?:\.\d+)?)$")
A_RE = re.compile(r"^A(\d+)$", re.I)
S_RE = re.compile(r"^S(\d+)$", re.I)


def parse_sidebar_cards(names: list[str]) -> list[dict]:
    cards: list[dict] = []
    i = 0
    while i < len(names):
        raw = (names[i] or "").strip()
        kind = ""
        ident = ""
        match_a = A_RE.fullmatch(raw)
        match_s = S_RE.fullmatch(raw)
        if match_a:
            kind, ident = "L3", f"A{match_a.group(1)}"
        elif match_s:
            kind, ident = "L2", f"S{match_s.group(1)}"
        if kind:
            card = {
                "level": kind,
                "id": ident,
                "empty": False,
                "start_s": None,
                "end_s": None,
                "label": raw,
            }
            for look in names[i + 1 : i + 8]:
                text = (look or "").strip()
                lowered = text.casefold()
                if "empty" in lowered:
                    card["empty"] = True
                rng = RANGE_RE.fullmatch(text)
                if rng:
                    card["start_s"] = timestamp_to_seconds(rng.group(1))
                    card["end_s"] = timestamp_to_seconds(rng.group(2))
                    break
                if A_RE.fullmatch(text) or S_RE.fullmatch(text):
                    break
            cards.append(card)
        i += 1
    return cards


def empty_cards(names: list[str], level: str) -> list[dict]:
    return [card for card in parse_sidebar_cards(names) if card["level"] == level and card["empty"]]


def task_blob_hints(blob: str) -> bool:
    lowered = (blob or "").casefold()
    return any(
        token in lowered
        for token in (
            "video caption labeling",
            "hierarchical egocentric",
            "generate with ai",
            "action (empty)",
            "level 3 — actions",
            "level 3 - actions",
            "left hand only",
        )
    )
