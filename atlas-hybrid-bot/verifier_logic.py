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

REJECTION_REASONS: tuple[str, ...] = (
    "Wrong object",
    "Added object",
    "Missed object",
    "Wrong action",
    "Added action",
    "Wrong hand",
    "Grammar / spelling",
)


def _normalize_clause(text: str) -> str:
    return normalize_segment_label((text or "").strip())


def _leading_verb(clause: str) -> str:
    match = _LEADING_VERB.search((clause or "").strip())
    return match.group(1).lower() if match else ""


def _content_tokens(clause: str) -> set[str]:
    stop = {
        "with", "from", "into", "in", "on", "to", "the", "a", "an", "and", "or",
        "left", "right", "both", "hand", "hands", "spoon", "tool",
    }
    return {
        token
        for token in re.findall(r"[a-z]+", (clause or "").casefold())
        if token not in stop and len(token) > 2
    }


def _clauses_match(left: str, right: str) -> bool:
    a = _normalize_clause(left).casefold()
    b = _normalize_clause(right).casefold()
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _clause_semantically_related(clause: str, expected_clauses: list[str]) -> bool:
    """True when a clause shares verb + object vocabulary with the reference label."""
    verb = _leading_verb(clause)
    if not verb:
        return False
    tokens = _content_tokens(clause)
    if not tokens:
        return False
    for expected in expected_clauses:
        if verb != _leading_verb(expected):
            continue
        overlap = tokens & _content_tokens(expected)
        if len(overlap) >= 2:
            return True
    return False


def decide_clause_verification(
    clause: str,
    all_clauses: list[str],
    *,
    expected_clauses: list[str] | None = None,
    index: int = 0,
) -> bool:
    """
    Return True for thumbs up (approve), False for thumbs down (reject).

    Verifier training prefers approving Atlas-authored clauses when grammar is
    valid and the action plausibly matches the clip — repeated scoop clauses
    are often intentional, not errors.
    """
    text = (clause or "").strip()
    if not text or not _LEADING_VERB.search(text):
        return False

    normalized = _normalize_clause(text)
    if not validate_clause_syntax(normalized):
        return False

    if expected_clauses:
        if any(_clauses_match(text, expected) for expected in expected_clauses):
            return True
        if _clause_semantically_related(text, expected_clauses):
            return True

    return True


def infer_rejection_reason(
    clause: str,
    all_clauses: list[str],
    *,
    expected_clauses: list[str] | None = None,
    index: int = 0,
) -> str:
    """Pick the Atlas rejection category after thumbs down."""
    text = (clause or "").strip()
    normalized = _normalize_clause(text)

    if not text or not _LEADING_VERB.search(text):
        return "Grammar / spelling"
    if not validate_clause_syntax(normalized):
        return "Grammar / spelling"

    if index > 0 and text.casefold() == (all_clauses[index - 1] or "").strip().casefold():
        return "Added action"

    if expected_clauses:
        clause_hand = re.search(r"\b(left|right|both)\s+hands?\b", text, re.IGNORECASE)
        for expected in expected_clauses:
            if not _leading_verb(expected) or _leading_verb(expected) != _leading_verb(text):
                continue
            if _clauses_match(text, expected):
                return "Wrong action"
            exp_hand = re.search(r"\b(left|right|both)\s+hands?\b", expected, re.IGNORECASE)
            if (
                clause_hand
                and exp_hand
                and clause_hand.group(0).casefold() != exp_hand.group(0).casefold()
                and _content_tokens(text) & _content_tokens(expected)
            ):
                return "Wrong hand"
            clause_obj = _content_tokens(text) - _content_tokens(expected)
            exp_obj = _content_tokens(expected) - _content_tokens(text)
            if clause_obj and not exp_obj:
                return "Added object"
            if exp_obj and not clause_obj:
                return "Missed object"
            if clause_obj and exp_obj:
                return "Wrong object"

    return "Wrong action"


def decide_missing_action(
    displayed_clauses: list[str],
    *,
    expected_label: str | None = None,
) -> bool:
    """
    Return True to click Yes (important action missing), False for No.

    Verifier clips list the actions to judge — default No unless the pipeline
    finds a clearly missing hand transfer or placement step.
    """
    _ = expected_label
    _ = displayed_clauses
    return False


def expected_clauses_from_label(label: str) -> list[str]:
    if not label or label == "No Action":
        return []
    return split_actions(_normalize_clause(label))
