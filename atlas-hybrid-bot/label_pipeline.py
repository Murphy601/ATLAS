"""ATLAS official annotation guide compliant label pipeline (no LLM)."""

from __future__ import annotations

import re

from config import (
    ARTICLE_PATTERN,
    COMMA_AND_PATTERN,
    DIGIT_PATTERN,
    MAX_ACTIONS_PER_LABEL,
    NUMBER_MAP,
    PLURAL_ONLY_TOOLS,
    SEMICOLON_PATTERN,
    SLASH_PATTERN,
    VERB_CORRECTIONS,
    VERB_REPLACEMENTS,
)
from frame_utils import frames_from_base64_list
from hybrid_annotator import AtlasHybridPipeline, _hand_tag_from_draft
from label_generator import (
    GlobalVideoContext,
    _int_to_words,
    apply_state_continuity,
    split_actions,
    usable_draft,
)

# Guide: comma separators OK; ", and" / slash / semicolon are banned.
_COMMA_AND = re.compile(r",\s*and\b", re.IGNORECASE)
_SLASH = re.compile(r"\s*/\s*")
_SEMICOLON = re.compile(r"\s*;\s*")

_TOOL_IN_HAND = re.compile(
    r"\bwith\s+\S+(?:\s+\S+)*\s+in\s+(?:left|right|both)\s+hands?\b",
    re.IGNORECASE,
)

# Broken tool syntax produced by over-eager hand normalization.
_DOUBLE_WITH_HAND = re.compile(
    r"\bwith\s+(.+?)\s+with\s+(left|right|both)\s+hands?\b",
    re.IGNORECASE,
)


def _normalize_draft_separators(text: str) -> str:
    text = _SLASH.sub(", ", text)
    text = _SEMICOLON.sub(", ", text)
    text = _COMMA_AND.sub(",", text)
    text = re.sub(r"\s+then\s+", ", ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+and\s+", ", ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*,\s*", ", ", text)
    return " ".join(text.split()).strip(" ,")


def _fix_tool_hand_syntax(clause: str) -> str:
    """Restore guide format: with [tool] in [hand], never with [tool] with [hand]."""
    if _TOOL_IN_HAND.search(clause):
        return clause.strip()

    def repl(match: re.Match[str]) -> str:
        tool = match.group(1).strip()
        hand = match.group(2).lower()
        hand_word = "hands" if hand == "both" else "hand"
        return f"with {tool} in {hand} {hand_word}"

    fixed = _DOUBLE_WITH_HAND.sub(repl, clause)
    return fixed.strip()


def _normalize_hand_prepositions(text: str) -> str:
    """Guide format: with [hand]. Preserve tool syntax: with [tool] in [hand]."""
    clauses = split_actions(text)
    if not clauses:
        return text
    fixed: list[str] = []
    for clause in clauses:
        clause = _fix_tool_hand_syntax(clause)
        if _TOOL_IN_HAND.search(clause):
            fixed.append(clause.strip())
            continue
        updated = re.sub(r"\bin both hands\b", "with both hands", clause, flags=re.IGNORECASE)
        updated = re.sub(r"\bin left hand\b", "with left hand", updated, flags=re.IGNORECASE)
        updated = re.sub(r"\bin right hand\b", "with right hand", updated, flags=re.IGNORECASE)
        fixed.append(_fix_tool_hand_syntax(updated.strip()))
    return ", ".join(fixed)


def _apply_safe_syntax_fixes(text: str) -> str:
    """Lightweight Atlas syntax fixes — no verb swaps, noun swaps, or clause surgery."""
    if not text or text.strip().lower() in {"no action", "no action."}:
        return "No Action"

    cleaned = text.strip().strip('"').strip("'")
    if cleaned.endswith("."):
        cleaned = cleaned[:-1].strip()

    def replace_digit(match: re.Match[str]) -> str:
        digit_str = match.group(0)
        if digit_str in NUMBER_MAP:
            return NUMBER_MAP[digit_str]
        try:
            return _int_to_words(int(digit_str))
        except ValueError:
            return digit_str

    cleaned = DIGIT_PATTERN.sub(replace_digit, cleaned)

    for continuous, imperative in sorted(
        VERB_CORRECTIONS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        cleaned = re.sub(
            rf"\b{re.escape(continuous)}\b",
            imperative,
            cleaned,
            flags=re.IGNORECASE,
        )

    for banned, replacement in VERB_REPLACEMENTS.items():
        cleaned = re.sub(rf"\b{banned}\b", replacement, cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\breach\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = ARTICLE_PATTERN.sub("", cleaned)
    cleaned = COMMA_AND_PATTERN.sub(",", cleaned)
    cleaned = SLASH_PATTERN.sub(", ", cleaned)
    cleaned = SEMICOLON_PATTERN.sub(", ", cleaned)

    for singular, plural in PLURAL_ONLY_TOOLS.items():
        cleaned = re.sub(rf"\b{re.escape(singular)}\b", plural, cleaned, flags=re.IGNORECASE)

    cleaned = " ".join(cleaned.split()).strip(" ,")
    if not cleaned or cleaned.lower() in {"and", "with", "no action"}:
        return "No Action"
    return cleaned


def _cap_clauses_simple(text: str, limit: int = MAX_ACTIONS_PER_LABEL) -> str:
    clauses = split_actions(text)[:limit]
    return ", ".join(clause.strip() for clause in clauses if clause.strip())


def _infer_missing_hand_from_motion(draft: str, mp_hand: str) -> str:
    """Append hand tag only when the draft/clauses lack any hand attribution."""
    if _hand_tag_from_draft(draft):
        return draft
    if re.search(
        r"\b(?:left hand|right hand|both hands)\b",
        draft,
        re.IGNORECASE,
    ):
        return draft
    hand = mp_hand if mp_hand.startswith("with ") else f"with {mp_hand}"
    return f"{draft} {hand}".strip()


def draft_preserving_cleaner(
    draft_text: str,
    *,
    previous_label: str | None = None,
    mp_hand_tag: str = "with right hand",
    duration_seconds: float | None = None,
) -> str:
    """
    Trust the Atlas AI draft; apply only safe syntax normalization.

    Does NOT: hold→pick up, noun swaps, fake off-hand holds, location injection,
    _cap_actions drop scoring, or full sanitize_label heuristics.
    """
    _ = duration_seconds
    label = (draft_text or "").strip()
    if not label or label.casefold() == "no action":
        return "No Action"

    label = _normalize_draft_separators(label)
    label = _apply_safe_syntax_fixes(label)
    if label == "No Action":
        return label

    label = _normalize_hand_prepositions(label)
    label = _infer_missing_hand_from_motion(label, mp_hand_tag)
    label = _cap_clauses_simple(label, MAX_ACTIONS_PER_LABEL)

    if previous_label:
        label = apply_state_continuity(label, previous_label)

    return label


def atlas_guide_cleaner(
    draft_text: str,
    *,
    previous_label: str | None = None,
    mp_hand_tag: str = "with right hand",
    duration_seconds: float | None = None,
) -> str:
    """Draft-preserving Atlas guide linter (alias for draft_preserving_cleaner)."""
    return draft_preserving_cleaner(
        draft_text,
        previous_label=previous_label,
        mp_hand_tag=mp_hand_tag,
        duration_seconds=duration_seconds,
    )


def resolve_hand_tag(draft_label: str, mp_hand_tag: str) -> str:
    """Prefer explicit hand in draft; MediaPipe is fallback for missing tags."""
    return _hand_tag_from_draft(draft_label) or mp_hand_tag or "with right hand"


def generate_label_hybrid(
    base64_frames: list[str],
    pipeline: AtlasHybridPipeline,
    *,
    previous_label: str | None = None,
    draft_label: str | None = None,
    duration_seconds: float | None = None,
    frame_timestamps: list[float] | None = None,
    frames_have_video: bool = False,
    next_label: str | None = None,
    global_context=None,
    segment_start_seconds: float | None = None,
) -> str:
    """Guide-compliant label from Atlas draft + optional MediaPipe hand fallback."""
    draft_label = usable_draft(draft_label)
    previous_label = usable_draft(previous_label)
    _ = (
        next_label,
        frame_timestamps,
        frames_have_video,
        global_context,
        segment_start_seconds,
    )

    if not draft_label:
        return "No Action"

    mp_hand = "with right hand"
    if base64_frames:
        frame_arrays = frames_from_base64_list(base64_frames)
        if frame_arrays:
            motion = pipeline.analyze_frame_motion_from_memory(
                frame_arrays,
                draft_label=draft_label,
            )
            mp_hand = motion.detected_hand

    return draft_preserving_cleaner(
        draft_label,
        previous_label=previous_label,
        mp_hand_tag=resolve_hand_tag(draft_label, mp_hand),
        duration_seconds=duration_seconds,
    )


def build_draft_global_context(segment_drafts: list[str]) -> GlobalVideoContext:
    """Guide mode uses per-segment drafts only — no cross-clip LLM glossary."""
    return GlobalVideoContext(objects=tuple())


# Back-compat alias from earlier iteration
minimal_atlas_cleaner = atlas_guide_cleaner
