"""ATLAS official annotation guide compliant label pipeline (no LLM)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

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
    CLOTH_PATTERN,
    CLOTH_WORK_VERBS,
    DISH_PATTERN,
    GlobalVideoContext,
    HOLD_CLAUSE_PATTERN,
    PLACE_LOCATION_PATTERN,
    WIPE_VERBS,
    _int_to_words,
    _leading_verb,
    apply_state_continuity,
    split_actions,
    usable_draft,
)

if TYPE_CHECKING:
    from hybrid_annotator import HandMotionProfile

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

# Do not rewrite valid imperatives (gold labels use smooth, not smoothen).
_DRAFT_VERB_CORRECTIONS = {
    key: value
    for key, value in VERB_CORRECTIONS.items()
    if key not in {"smooth", "smoothe"} and value != "smoothen"
}
_DRAFT_VERB_CORRECTIONS["smoothing"] = "smooth"


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
        _DRAFT_VERB_CORRECTIONS.items(), key=lambda item: len(item[0]), reverse=True
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


def _clause_object_phrase(clause: str) -> str:
    """Object noun phrase after the leading verb (hand/tool tags stripped)."""
    verb = _leading_verb(clause)
    if not verb:
        return clause.strip()
    text = re.sub(rf"^{re.escape(verb)}\b", "", clause, count=1, flags=re.IGNORECASE).strip()
    text = re.sub(
        r"\s+with\s+(.+?)\s+in\s+(?:left hand|right hand|both hands)\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s+(?:with|in)\s+(?:left hand|right hand|both hands)\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip(" ,")


def _is_dish_clause(clause: str) -> bool:
    return bool(DISH_PATTERN.search(clause or ""))


def _is_cloth_clause(clause: str) -> bool:
    return bool(CLOTH_PATTERN.search(clause or ""))


def _cloth_implement(clause: str) -> str:
    match = re.search(r"\b(cloth|rag|towel|sponge)\b", clause or "", re.IGNORECASE)
    return match.group(1).lower() if match else "cloth"


def _apply_plural_nouns(label: str, draft_text: str, previous_label: str | None) -> str:
    """Keep plural object forms when draft or prior segment uses them (e.g. papers)."""
    context = f"{previous_label or ''} {draft_text}".lower()
    updated = label
    if "papers" in context:
        updated = re.sub(r"\bpaper\b(?!s)", "papers", updated, flags=re.IGNORECASE)
    return updated


def _split_false_both_hands(label: str) -> str:
    """Split hold + work when a single both-hands clause hides bimanual roles."""
    clauses = split_actions(label)
    if len(clauses) == 1:
        clause = clauses[0]
        verb = _leading_verb(clause)
        if "both hands" not in clause.lower():
            return label
        if verb in WIPE_VERBS and _is_dish_clause(clause):
            obj = _clause_object_phrase(clause) or "plate"
            implement = _cloth_implement(clause)
            return (
                f"hold {obj} with left hand, "
                f"{verb} {obj} with {implement} in right hand"
            )
        if (
            verb in CLOTH_WORK_VERBS
            and _is_cloth_clause(clause)
            and not PLACE_LOCATION_PATTERN.search(clause)
        ):
            obj = _clause_object_phrase(clause) or "cloth"
            return f"hold {obj} in left hand, {clause.replace('both hands', 'right hand')}"
        return label
    if len(clauses) == 2:
        first, second = clauses[0], clauses[1]
        if _leading_verb(first) == "hold":
            hold, work = first, second
        elif _leading_verb(second) == "hold":
            hold, work = second, first
        else:
            return label
        if "both hands" not in hold.lower():
            return label
        work_verb = _leading_verb(work)
        if work_verb in WIPE_VERBS and (_is_dish_clause(hold) or _is_dish_clause(work)):
            obj = _clause_object_phrase(hold) or _clause_object_phrase(work) or "plate"
            implement = _cloth_implement(work)
            return (
                f"hold {obj} with left hand, "
                f"{work_verb} {obj} with {implement} in right hand"
            )
        if work_verb in CLOTH_WORK_VERBS and (
            _is_cloth_clause(hold) or _is_cloth_clause(work)
        ):
            obj = _clause_object_phrase(hold) or _clause_object_phrase(work) or "cloth"
            work_clause = re.sub(r"\bboth hands\b", "right hand", work, flags=re.IGNORECASE)
            return f"hold {obj} in left hand, {work_clause}"
    return label


def _ensure_offhand_hold(label: str) -> str:
    """Add stabilize clause when draft names one working hand on cloth/dish work."""
    clauses = split_actions(label)
    if len(clauses) != 1:
        return label
    clause = clauses[0]
    if HOLD_CLAUSE_PATTERN.search(clause) or "both hands" in clause.lower():
        return label
    verb = _leading_verb(clause)
    uses_right = re.search(r"\b(?:in|with) right hand\b", clause, re.IGNORECASE)
    uses_left = re.search(r"\b(?:in|with) left hand\b", clause, re.IGNORECASE)
    if verb in WIPE_VERBS and _is_dish_clause(clause):
        obj = _clause_object_phrase(clause) or "plate"
        if uses_right and not uses_left:
            return f"hold {obj} with left hand, {clause}"
        if uses_left and not uses_right:
            return f"hold {obj} with right hand, {clause}"
    if (
        verb in CLOTH_WORK_VERBS
        and _is_cloth_clause(clause)
        and not PLACE_LOCATION_PATTERN.search(clause)
    ):
        obj = _clause_object_phrase(clause) or "cloth"
        if uses_right and not uses_left:
            return f"hold {obj} in left hand, {clause}"
        if uses_left and not uses_right:
            return f"hold {obj} in right hand, {clause}"
    return label


def _fix_hand_attribution(label: str, motion: HandMotionProfile | None) -> str:
    """Correct false both-hands tags using motion asymmetry and bimanual splits."""
    if not label or label == "No Action":
        return label

    split = _split_false_both_hands(label)
    if split != label:
        label = split

    if motion is None:
        return label

    clauses = split_actions(label)
    if not clauses:
        return label

    threshold = 0.015
    v_left = motion.v_left
    v_right = motion.v_right
    dominant_left = v_left > threshold and v_left >= v_right * 1.5
    dominant_right = v_right > threshold and v_right >= v_left * 1.5
    both_active = v_left > threshold and v_right > threshold and not dominant_left and not dominant_right

    if both_active:
        return label

    def single_hand_for_both(clause: str) -> str:
        if "both hands" not in clause.lower():
            return clause
        if dominant_left:
            return re.sub(r"\bboth hands\b", "left hand", clause, flags=re.IGNORECASE)
        if dominant_right:
            return re.sub(r"\bboth hands\b", "right hand", clause, flags=re.IGNORECASE)
        return clause

    if len(clauses) == 1 and "both hands" in clauses[0].lower():
        retry = _split_false_both_hands(label)
        if retry != label:
            return retry
        fixed = single_hand_for_both(clauses[0])
        if fixed != clauses[0]:
            return fixed

    return ", ".join(single_hand_for_both(clause) for clause in clauses)


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
    motion: HandMotionProfile | None = None,
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
    label = _apply_plural_nouns(label, draft_text, previous_label)
    label = _ensure_offhand_hold(label)
    label = _fix_hand_attribution(label, motion)
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
    motion: HandMotionProfile | None = None,
) -> str:
    """Draft-preserving Atlas guide linter (alias for draft_preserving_cleaner)."""
    return draft_preserving_cleaner(
        draft_text,
        previous_label=previous_label,
        mp_hand_tag=mp_hand_tag,
        duration_seconds=duration_seconds,
        motion=motion,
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

    motion = None
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
        motion=motion,
    )


def build_draft_global_context(segment_drafts: list[str]) -> GlobalVideoContext:
    """Guide mode uses per-segment drafts only — no cross-clip LLM glossary."""
    return GlobalVideoContext(objects=tuple())


# Back-compat alias from earlier iteration
minimal_atlas_cleaner = atlas_guide_cleaner
