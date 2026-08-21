"""Decide thumbs up/down and missing-action answers for Human Verifier clips."""

from __future__ import annotations

import re

from label_generator import split_actions, validate_clause_syntax
from label_pipeline import normalize_segment_label

_LEADING_VERB = re.compile(
    r"^(hold|pick up|place|pass|scoop|scrub|wipe|trim|dig|rotate|strip|insert|pull|"
    r"open|close|fold|smooth|smoothen|iron|mop|sweep|rake|gather|water|fill|cut|"
    r"align|reposition|move|set|put)\b",
    re.IGNORECASE,
)


def _normalize_clause(text: str) -> str:
    return normalize_segment_label((text or "").strip())


def _clauses_match(left: str, right: str) -> bool:
    a = _normalize_clause(left).casefold()
    b = _normalize_clause(right).casefold()
    if not a or not b:
        return False
    return a == b or a in b or b in a


def decide_clause_verification(
    clause: str,
    all_clauses: list[str],
    *,
    expected_clauses: list[str] | None = None,
    index: int = 0,
) -> bool:
    """
    Return True for thumbs up (approve), False for thumbs down (reject).
    """
    text = (clause or "").strip()
    if not text or not _LEADING_VERB.search(text):
        return False

    normalized = _normalize_clause(text)
    if not validate_clause_syntax(normalized):
        return False

    if index > 0 and text.casefold() == (all_clauses[index - 1] or "").strip().casefold():
        return False

    if expected_clauses:
        return any(_clauses_match(text, expected) for expected in expected_clauses)

    return True


def decide_missing_action(
    displayed_clauses: list[str],
    *,
    expected_label: str | None = None,
) -> bool:
    """
    Return True to click Yes (important action missing), False for No.
    """
    if not expected_label or expected_label == "No Action":
        return False

    expected_parts = split_actions(_normalize_clause(expected_label))
    shown = [_normalize_clause(clause) for clause in displayed_clauses if clause.strip()]
    if not expected_parts:
        return False

    matched = 0
    for expected in expected_parts:
        if any(_clauses_match(expected, shown_clause) for shown_clause in shown):
            matched += 1

    return matched < len(expected_parts)


def expected_clauses_from_label(label: str) -> list[str]:
    if not label or label == "No Action":
        return []
    return split_actions(_normalize_clause(label))
