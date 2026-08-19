"""ATLAS official annotation guide compliant label pipeline (no LLM)."""

from __future__ import annotations

import re

from config import MAX_ACTIONS_PER_LABEL
from frame_utils import frames_from_base64_list
from hybrid_annotator import AtlasHybridPipeline, _hand_tag_from_draft
from label_generator import (
    GlobalVideoContext,
    _cap_actions,
    _ensure_place_location,
    apply_state_continuity,
    enforce_atlas_template,
    lint_atlas_syntax,
    sanitize_label,
    split_actions,
    usable_draft,
)

# Guide: comma separators OK; ", and" / slash / semicolon are banned.
_COMMA_AND = re.compile(r",\s*and\b", re.IGNORECASE)
_SLASH = re.compile(r"\s*/\s*")
_SEMICOLON = re.compile(r"\s*;\s*")


def _normalize_draft_separators(text: str) -> str:
    text = _SLASH.sub(", ", text)
    text = _SEMICOLON.sub(", ", text)
    text = _COMMA_AND.sub(",", text)
    text = re.sub(r"\s+then\s+", ", ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+and\s+", ", ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*,\s*", ", ", text)
    return " ".join(text.split()).strip(" ,")


_TOOL_IN_HAND = re.compile(
    r"\bwith\s+\S+(?:\s+\S+)*\s+in\s+(?:left|right|both)\s+hands?\b",
    re.IGNORECASE,
)


def _normalize_hand_prepositions(text: str) -> str:
    """Guide format: with [hand]. Preserve tool syntax: with [tool] in [hand]."""
    clauses = split_actions(text)
    if not clauses:
        return text
    fixed: list[str] = []
    for clause in clauses:
        if _TOOL_IN_HAND.search(clause):
            fixed.append(clause.strip())
            continue
        updated = re.sub(r"\bin both hands\b", "with both hands", clause, flags=re.IGNORECASE)
        updated = re.sub(r"\bin left hand\b", "with left hand", updated, flags=re.IGNORECASE)
        updated = re.sub(r"\bin right hand\b", "with right hand", updated, flags=re.IGNORECASE)
        fixed.append(updated.strip())
    return ", ".join(fixed)


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


def atlas_guide_cleaner(
    draft_text: str,
    *,
    previous_label: str | None = None,
    mp_hand_tag: str = "with right hand",
    duration_seconds: float | None = None,
) -> str:
    """
    Official ATLAS guide linter on the Atlas AI draft:
    - Keep up to 3 comma-separated actions (off-hand hold + work allowed)
    - Imperative verbs, no articles/digits, banned verb replacement
    - place requires location; plural tools; hand on every clause
    """
    _ = duration_seconds
    label = (draft_text or "").strip()
    if not label or label.casefold() == "no action":
        return label

    label = _normalize_draft_separators(label)
    label = _normalize_hand_prepositions(label)
    label = _infer_missing_hand_from_motion(label, mp_hand_tag)

    # Guide: max 3 distinct actions per segment — never collapse to 1.
    clauses = split_actions(label)[:MAX_ACTIONS_PER_LABEL]
    label = ", ".join(clauses)

    label = sanitize_label(label)
    label = lint_atlas_syntax(label)
    label = enforce_atlas_template(label)

    if previous_label:
        label = apply_state_continuity(label, previous_label)

    label = _ensure_place_location(label, previous_label)
    label = _cap_actions(label, limit=MAX_ACTIONS_PER_LABEL)

    return label


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

    return atlas_guide_cleaner(
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
