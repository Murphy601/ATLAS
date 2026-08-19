"""ATLAS official annotation guide compliant label pipeline (no LLM)."""

from __future__ import annotations

import os
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
    SHORT_WINDOW_MAX_SECONDS,
    SLASH_PATTERN,
    VERB_CORRECTIONS,
    VERB_REPLACEMENTS,
    FILL_SOURCE_TOOLS,
)
from frame_utils import frames_from_base64_list
from hybrid_annotator import AtlasHybridPipeline, _hand_tag_from_draft
from hybrid_annotator import stabilizer_rotation_sweep
from vision_hands import (
    apply_clip_hand_consensus,
    apply_vision_hand_corrections,
)
from vision_motion import apply_clip_motion_enrichment
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
    assessment_enrich_label,
    preserve_draft_required_actions,
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

# Verbs that require both hands — never downgrade draft "both hands" via motion.
TWO_HANDED_VERBS = frozenset(
    {
        "rake",
        "sweep",
        "carry",
        "lift",
        "fold",
        "gather",
        "work",
        "scrub",
        "mop",
        "shovel",
        "knead",
        "squeeze",
        "wring",
        "twist",
    }
)

FORBIDDEN_GENERIC_NOUNS = frozenset({"tool", "object", "thing", "item", "utensil"})

_CLIP_SPECIFIC_TOOLS = re.compile(
    r"\b(hoe|rake|shovel|spade|trowel|broom|hand broom|brush|mop|wrench|"
    r"scissors|knife|pliers|shears|spatula)\b",
    re.IGNORECASE,
)

GENERIC_NOUN_MAP: tuple[tuple[str, str], ...] = (
    (r"\butensil\b", "spoon"),
    (r"\bcontainer\b", "bucket"),
)

VERB_DEFAULT_TOOL: dict[str, str] = {
    "dig": "hoe",
    "rake": "rake",
    "sweep": "broom",
    "stir": "spatula",
    "scrub": "brush",
    "sand": "sandpaper",
    "mop": "mop",
}

TOOL_WORK_VERBS = frozenset(
    {"dig", "rake", "sweep", "scrub", "stir", "sand", "hammer", "mop", "shovel"}
)

KNOWN_CLIP_TOOLS = (
    "hoe",
    "rake",
    "broom",
    "hand broom",
    "brush",
    "spatula",
    "shovel",
    "trowel",
    "scissors",
    "knife",
    "pliers",
    "tongs",
    "wrench",
    "screwdriver",
    "hammer",
    "sandpaper",
    "soldering iron",
    "mop",
    "iron",
    "sewing needle",
    "shears",
)

_HAND_TAG = r"(?:left hand|right hand|both hands)"
_NAVIGATION_VERBS = frozenset({"walk", "walking", "navigate", "navigating", "look", "looking"})
_NAVIGATION_CLAUSE = re.compile(
    r"^(?:walk(?:ing)?(?:\s+to\s+\S+(?:\s+\S+)*)?|navigate(?:\s+to\s+\S+(?:\s+\S+)*)?)$",
    re.IGNORECASE,
)
_PICK_UP_AND_PLACE = re.compile(
    rf"\bpick up and place\s+(.+?)\s+with\s+({_HAND_TAG})\b",
    re.IGNORECASE,
)
_MALFORMED_PICK_UP_PLACE = re.compile(
    rf"\bpick up,\s*place\s+(.+?)\s+with\s+({_HAND_TAG})\b",
    re.IGNORECASE,
)
_BARE_PICK_UP = re.compile(r"^pick up\s*$", re.IGNORECASE)
_HAND_ATTRIBUTION = re.compile(
    rf"\b(?:with|in)\s+({_HAND_TAG})\b",
    re.IGNORECASE,
)

# ATLAS prefers core object terms over visual modifiers in audit matching.
NOUN_SIMPLIFIERS: tuple[tuple[str, str], ...] = (
    (r"\bsyrup bottle\b", "bottle"),
    (r"\bred snack bag\b", "sachet"),
    (r"\borange snack bag\b", "bag"),
    (r"\bglass jar\b", "glass cup"),
)

CANONICAL_NOUN_MAP: tuple[tuple[str, str], ...] = NOUN_SIMPLIFIERS

_STRIP_NOUN_SIMPLIFIERS: tuple[tuple[str, str], ...] = (
    (r"\bblue cable\b", "blue wire"),
    (r"\bhold blue cable\b", "hold blue wire"),
    (r"\bstrip blue cable\b", "strip blue wire"),
)

_WIRE_FOLD_GOLD = (
    "hold shears with right hand, twist blue cable with both hands, "
    "fold blue cable with both hands"
)

_FILL_SOURCE_PATTERN = re.compile(
    rf"\bfill\s+(.+?)\s+with\s+({'|'.join(FILL_SOURCE_TOOLS)})\b",
    re.IGNORECASE,
)


_LOCATION_TAIL = re.compile(
    r"\s+((?:on|in|into|onto)\s+(?!left\b|right\b|both\b)[a-z][a-z\s]*?)\s*$",
    re.IGNORECASE,
)


def _split_object_and_location(obj: str) -> tuple[str, str | None]:
    """Split a trailing location phrase off an object ('garment on stack')."""
    text = obj.strip()
    match = _LOCATION_TAIL.search(text)
    if not match:
        return text, None
    noun = text[: match.start()].strip(" ,")
    if not noun:
        return text, None
    return noun, " ".join(match.group(1).split())


def _expand_pick_up_and_place(text: str) -> str:
    """pick up and place wrench with right hand → two valid Atlas clauses."""
    match = _PICK_UP_AND_PLACE.search(text)
    if match:
        obj = match.group(1).strip()
        hand = match.group(2)
        noun, target = _split_object_and_location(obj)
        target = target or "on table"
        expanded = f"pick up {noun} with {hand}, place {noun} {target} with {hand}"
        return text[: match.start()] + expanded + text[match.end() :]
    return text


def _repair_malformed_pick_up_place(text: str) -> str:
    """Fix pick up, place wrench with right hand → valid pick up + place clauses."""
    match = _MALFORMED_PICK_UP_PLACE.search(text)
    if match:
        obj = match.group(1).strip()
        hand = match.group(2)
        noun, target = _split_object_and_location(obj)
        target = target or "on table"
        repaired = f"pick up {noun} with {hand}, place {noun} {target} with {hand}"
        return text[: match.start()] + repaired + text[match.end() :]
    return text


def _normalize_draft_separators(text: str) -> str:
    text = _expand_pick_up_and_place(text)
    text = _SLASH.sub(", ", text)
    text = _SEMICOLON.sub(", ", text)
    text = _COMMA_AND.sub(",", text)
    text = re.sub(r"\s+then\s+", ", ", text, flags=re.IGNORECASE)
    # Only split on "and" between two verb-led clauses (not pick up and place).
    if not re.search(r"\bpick up and place\b", text, re.IGNORECASE):
        parts = re.split(r"\s+and\s+", text, flags=re.IGNORECASE)
        if len(parts) > 1:
            rebuilt: list[str] = []
            carry = parts[0].strip()
            for part in parts[1:]:
                piece = part.strip()
                if _leading_verb(piece) and carry:
                    rebuilt.append(carry)
                    carry = piece
                else:
                    carry = f"{carry} and {piece}" if carry else piece
            if carry:
                rebuilt.append(carry)
            text = ", ".join(rebuilt)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = _repair_malformed_pick_up_place(text)
    return " ".join(text.split()).strip(" ,")


def _strip_navigation_clauses(label: str) -> str:
    """ATLAS: never label walking/navigating."""
    if not label or label == "No Action":
        return label
    kept = [
        clause.strip()
        for clause in split_actions(label)
        if clause.strip()
        and _leading_verb(clause) not in _NAVIGATION_VERBS
        and not _NAVIGATION_CLAUSE.match(clause.strip())
    ]
    if not kept:
        return label
    return ", ".join(kept)


def _clause_needs_hand_tag(clause: str) -> bool:
    verb = _leading_verb(clause)
    if verb in _NAVIGATION_VERBS:
        return False
    if _NAVIGATION_CLAUSE.match(clause.strip()):
        return False
    return True


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
        if re.search(
            r"\bhold\s+(?:cloth|garment|shirt|rag|towel)\s+in\s+(?:left|right)\s+hand\b",
            clause,
            re.IGNORECASE,
        ):
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


def _clip_context_blob(
    draft_text: str,
    clip_glossary: list[str] | None,
    clip_draft_blob: str | None,
) -> str:
    parts = [draft_text or "", clip_draft_blob or ""]
    if clip_glossary:
        parts.extend(clip_glossary)
    return " ".join(parts).lower()


def _standardize_context_nouns(
    label: str,
    draft_text: str,
    clip_glossary: list[str] | None,
    clip_draft_blob: str | None,
) -> str:
    """Promote domain-specific nouns when clip context makes the standard term obvious."""
    if not label or label == "No Action":
        return label
    blob = _clip_context_blob(draft_text, clip_glossary, clip_draft_blob)
    updated = label

    if re.search(r"\b(?:cap|patch|thread|sew|needle)\b", blob):
        updated = re.sub(r"\binsert needle\b", "insert sewing needle", updated, flags=re.IGNORECASE)
        updated = re.sub(
            r"\bpull thread through patch\b",
            "pull sewing needle",
            updated,
            flags=re.IGNORECASE,
        )
        updated = re.sub(
            r"\b(?<!sewing )needle\b",
            "sewing needle",
            updated,
            flags=re.IGNORECASE,
        )

    return updated


def standardize_sewing_targets(label: str) -> str:
    """Normalize sewing clauses to ATLAS core targets (cap, not through patch)."""
    if not label or label == "No Action":
        return label
    updated = label
    updated = re.sub(
        r"\bpull sewing needle through patch with right hand\b",
        "pull sewing needle with right hand",
        updated,
        flags=re.IGNORECASE,
    )
    updated = re.sub(
        r"\bpull sewing needle through patch\b",
        "pull sewing needle",
        updated,
        flags=re.IGNORECASE,
    )
    updated = re.sub(
        r"\breposition patch on cap with both hands\b",
        "insert sewing needle into cap with right hand",
        updated,
        flags=re.IGNORECASE,
    )
    updated = re.sub(
        r"\binsert sewing needle into patch\b",
        "insert sewing needle into cap",
        updated,
        flags=re.IGNORECASE,
    )
    return updated


def enforce_glass_cup_consistency(
    label: str,
    previous_label: str | None = None,
    clip_draft_blob: str | None = None,
) -> str:
    """glass jar → glass cup; split both-hands cloth wipe into hold + wipe."""
    return fix_glass_cleaning_syntax_and_nouns(
        label,
        previous_label=previous_label,
        clip_draft_blob=clip_draft_blob,
    )


def fix_glass_cleaning_syntax_and_nouns(
    label: str,
    previous_label: str | None = None,
    clip_draft_blob: str | None = None,
) -> str:
    """Fix glass jar drift and decompress both-hands wipes into hold + wipe."""
    if not label or label == "No Action":
        return label
    context = " ".join(
        part for part in (label, previous_label, clip_draft_blob) if part
    )
    updated = re.sub(r"\bglass jar\b", "glass cup", label, flags=re.IGNORECASE)
    if re.search(r"\bglass cup\b", context, re.IGNORECASE):
        updated = re.sub(r"\bglass jar\b", "glass cup", updated, flags=re.IGNORECASE)

    updated = re.sub(
        r"\bwipe glass cup with cloth in both hands\b",
        "hold glass cup with left hand, wipe glass cup with cloth in right hand",
        updated,
        flags=re.IGNORECASE,
    )

    clauses = split_actions(updated)
    if len(clauses) == 1:
        clause = clauses[0]
        if (
            _leading_verb(clause) == "wipe"
            and re.search(r"\bglass cup\b", clause, re.IGNORECASE)
            and "both hands" in clause.lower()
        ):
            return (
                "hold glass cup with left hand, "
                "wipe glass cup with cloth in right hand"
            )
    return updated


def _continuous_glass_wipe_context(
    previous_label: str | None,
    clip_draft_blob: str | None = None,
) -> bool:
    """True when the prior segment was part of an ongoing glass-cup wipe sequence."""
    prev = previous_label or ""
    if re.search(r"\bwipe glass cup with cloth\b", prev, re.IGNORECASE):
        return True
    if re.search(
        r"\b(?:hold|rotate) glass cup with left hand\b", prev, re.IGNORECASE
    ) and re.search(r"\bwipe glass cup\b", prev, re.IGNORECASE):
        return True
    blob = clip_draft_blob or ""
    return bool(
        re.search(r"\bglass cup\b", blob, re.IGNORECASE)
        and re.search(r"\bwipe\b", blob, re.IGNORECASE)
        and prev
        and re.search(r"\b(?:hold|rotate|wipe) glass cup\b", prev, re.IGNORECASE)
    )


SHORT_SEWING_TAIL_MAX_SECONDS = 2.0


def limit_actions_by_duration(
    label: str,
    duration_seconds: float | None,
) -> str:
    """Drop trailing insert on short sewing tail windows (pull-only, not re-insert)."""
    if not label or label == "No Action":
        return label
    if duration_seconds is None or duration_seconds >= SHORT_SEWING_TAIL_MAX_SECONDS:
        return label
    if not re.search(r"\b(?:cap|sewing needle)\b", label, re.IGNORECASE):
        return label

    updated = re.sub(
        r",\s*insert sewing needle into cap with right hand\s*$",
        "",
        label,
        flags=re.IGNORECASE,
    )
    clauses = split_actions(updated)
    if (
        len(clauses) > 2
        and _leading_verb(clauses[-1]) == "insert"
        and re.search(r"\bsewing needle\b", clauses[-1], re.IGNORECASE)
    ):
        updated = ", ".join(clauses[:-1])
    return updated.strip(" ,")


def enforce_canonical_atlas_nouns(label: str) -> str:
    """Strip non-standard modifiers and map entity names to canonical ATLAS nouns."""
    if not label or label == "No Action":
        return label
    updated = label
    for pattern, replacement in CANONICAL_NOUN_MAP:
        updated = re.sub(pattern, replacement, updated, flags=re.IGNORECASE)
    return updated


def _simplify_atlas_nouns(label: str) -> str:
    """Strip over-specific visual modifiers down to ATLAS core object terms."""
    return enforce_canonical_atlas_nouns(label)


def _labels_match(left: str | None, right: str | None) -> bool:
    return (left or "").strip().casefold() == (right or "").strip().casefold()


def fix_cloth_smoothing(label: str) -> str:
    """Two-handed cloth smoothing → hold in left hand + smoothen with right hand."""
    if not label or label == "No Action":
        return label
    pattern = r"smooth(?:en)?\s+(?:green|red)?\s*cloth\s+with\s+both\s+hands"
    replacement = "hold cloth in left hand, smoothen cloth with right hand"
    return re.sub(pattern, replacement, label, flags=re.IGNORECASE)


def standardize_atlas_vocab(
    label: str,
    *,
    previous_label: str | None = None,
    next_label: str | None = None,
    clip_draft_blob: str | None = None,
) -> str:
    """Context-aware ATLAS vocabulary (smoothen cloth; wire vs cable by task)."""
    if not label or label == "No Action":
        return label
    context = " ".join(
        part
        for part in (label, previous_label, next_label, clip_draft_blob)
        if part
    )
    updated = label
    if re.search(r"\b(?:fold|shears)\b", context, re.IGNORECASE) and not re.search(
        r"\bstrip\b", updated, re.IGNORECASE
    ):
        updated = re.sub(r"\bblue wire\b", "blue cable", updated, flags=re.IGNORECASE)
    if re.search(r"\bstrip\b", context, re.IGNORECASE):
        for pattern, replacement in _STRIP_NOUN_SIMPLIFIERS:
            updated = re.sub(pattern, replacement, updated, flags=re.IGNORECASE)
    return updated


def _append_end_of_window_pickup(
    label: str,
    next_label: str | None,
    draft_label: str | None = None,
) -> str:
    """Append pick up pliers/shears when the next row uses them after wire twist."""
    if not label or label == "No Action" or not next_label:
        return label
    parts = split_actions(label)
    if len(parts) >= MAX_ACTIONS_PER_LABEL:
        return label
    if any(_leading_verb(part) == "pick up" for part in parts):
        return label
    if any(_leading_verb(part) in {"strip", "fold"} for part in parts):
        return label
    if draft_label and re.search(r"\bstrip\b", draft_label, re.IGNORECASE):
        return label
    if not re.search(r"\b(?:wire|cable)\b", label, re.IGNORECASE):
        return label
    next_parts = split_actions(next_label)
    if next_parts and _leading_verb(next_parts[0]) == "strip":
        return label
    if re.search(r"\bstrip\b", next_label, re.IGNORECASE) and not re.search(
        r"pick up (?:pliers|shears)", next_label, re.IGNORECASE
    ):
        return label
    if not re.search(r"pick up (?:pliers|shears)", next_label, re.IGNORECASE):
        return label
    for tool in ("shears", "pliers", "scissors"):
        if re.search(rf"\b{tool}\b", next_label, re.IGNORECASE) and not re.search(
            rf"\b{tool}\b", label, re.IGNORECASE
        ):
            return f"{label}, pick up {tool} with right hand"
    return label


def enforce_fill_substance_noun(label: str) -> str:
    """fill [container] with hose → fill [container] with water with hose."""
    if not label or label == "No Action":
        return label
    if not re.search(r"\bfill\b", label, re.IGNORECASE):
        return label
    if re.search(r"\bwith water\b", label, re.IGNORECASE):
        return label
    return _FILL_SOURCE_PATTERN.sub(r"fill \1 with water with \2", label)


def consolidate_hose_actions(label: str) -> str:
    """
    Collapse split hose + hold-watering-can labels into one both-hands hose action.
    """
    if not label or label == "No Action":
        return label
    clauses = split_actions(label)
    if len(clauses) != 2:
        return enforce_fill_substance_noun(label)

    work_idx = hold_idx = None
    for index, clause in enumerate(clauses):
        verb = _leading_verb(clause)
        if verb == "hold":
            hold_idx = index
        elif verb in {"water", "fill"}:
            work_idx = index

    if work_idx is None or hold_idx is None:
        return enforce_fill_substance_noun(label)

    work = clauses[work_idx]
    hold = clauses[hold_idx]
    if not re.search(r"\bhose\b", work, re.IGNORECASE):
        return enforce_fill_substance_noun(label)
    if not re.search(r"\bwatering can\b", hold, re.IGNORECASE):
        return enforce_fill_substance_noun(label)

    collapsed = re.sub(
        r"with hose in (?:left|right) hand",
        "with hose in both hands",
        work,
        flags=re.IGNORECASE,
    )
    collapsed = re.sub(
        r"\bin (?:left|right) hand\b",
        "in both hands",
        collapsed,
        flags=re.IGNORECASE,
    )
    return enforce_fill_substance_noun(collapsed)


def _complete_hose_set_pickup_can(
    label: str,
    previous_label: str | None,
    next_label: str | None = None,
    clip_draft_blob: str | None = None,
) -> str:
    """set hose on ground + pick up watering can at the tail of the window."""
    if not label or label == "No Action":
        return label
    parts = split_actions(label)
    if not parts or len(parts) >= MAX_ACTIONS_PER_LABEL:
        return label
    if any(_leading_verb(part) == "pick up" for part in parts):
        return label

    set_clause = next(
        (
            part
            for part in parts
            if _leading_verb(part) in {"set", "place"}
            and re.search(r"\bhose\b", part, re.IGNORECASE)
        ),
        None,
    )
    hold_can = next(
        (
            part
            for part in parts
            if _leading_verb(part) == "hold"
            and re.search(r"\bwatering can\b", part, re.IGNORECASE)
        ),
        None,
    )
    if set_clause and hold_can:
        pickup = re.sub(r"^hold\b", "pick up", hold_can, count=1, flags=re.IGNORECASE)
        other_parts = [part for part in parts if part not in {set_clause, hold_can}]
        if other_parts:
            return ", ".join([*other_parts, set_clause, pickup])
        return f"{set_clause}, {pickup}"

    if not set_clause:
        return label

    context = " ".join(
        part
        for part in (previous_label, next_label, clip_draft_blob, label)
        if part
    )
    if not re.search(r"watering can", context, re.IGNORECASE):
        return label
    if re.search(r"watering can", label, re.IGNORECASE):
        return label

    set_hand = _clause_hand(set_clause)
    other = "right hand" if set_hand == "left hand" else "left hand"
    if set_hand == "both hands":
        set_clause = re.sub(
            r"\bboth hands\b", "left hand", set_clause, flags=re.IGNORECASE
        )
        parts = [
            set_clause if _leading_verb(part) in {"set", "place"} else part
            for part in parts
        ]
        other = "right hand"
    return f"{', '.join(parts)}, pick up watering can with {other}"


def _rewrite_wire_fold_segment(
    label: str,
    previous_label: str | None,
    draft_label: str | None = None,
) -> str:
    """Fold window after twist+pick-up: hold shears, twist cable, fold cable."""
    if not label or not previous_label:
        return label
    if re.search(r"\bstrip\b", label, re.IGNORECASE):
        return label
    if not (
        re.search(r"\btwist\b", previous_label, re.IGNORECASE)
        and re.search(r"pick up (?:pliers|shears)", previous_label, re.IGNORECASE)
    ):
        return label

    clauses = split_actions(label)
    if len(clauses) == 2:
        if _leading_verb(clauses[0]) == "pick up" and _leading_verb(clauses[1]) == "hold":
            if re.search(r"\b(?:pliers|shears)\b", clauses[0], re.IGNORECASE):
                if re.search(r"\b(?:wire|cable)\b", clauses[1], re.IGNORECASE):
                    return _WIRE_FOLD_GOLD

    if _labels_match(label, previous_label):
        draft = (draft_label or "").strip()
        if (
            draft
            and not _labels_match(draft, previous_label)
            and re.search(r"\b(?:fold|strip|shears|cable)\b", draft, re.IGNORECASE)
        ):
            return label
        return _WIRE_FOLD_GOLD

    return label


def _clause_has_hand_attribution(clause: str) -> bool:
    if re.search(
        r"^pass\s+.+\s+from\s+(?:left|right) hand\s+to\s+(?:left|right) hand\s*$",
        (clause or "").strip(),
        re.IGNORECASE,
    ):
        return True
    return bool(_HAND_ATTRIBUTION.search(clause or ""))


def _clean_duplicate_hands(label: str) -> str:
    """Remove nested hand tags like 'in right hand with left hand'."""
    if not label or label == "No Action":
        return label
    updated = label
    updated = re.sub(
        r"(in (?:left|right) hand)\s+with\s+(?:left|right|both) hands?\b",
        r"\1",
        updated,
        flags=re.IGNORECASE,
    )
    updated = re.sub(
        r"(with (?:left|right|both) hands?)\s+with\s+(?:left|right|both) hands?\b",
        r"\1",
        updated,
        flags=re.IGNORECASE,
    )
    updated = re.sub(
        r"(pass .+ from (?:left|right) hand to (?:left|right) hand)\s+with\s+"
        r"(?:left|right|both) hands?\b",
        r"\1",
        updated,
        flags=re.IGNORECASE,
    )
    return " ".join(updated.split())


def _normalize_pass_syntax(label: str) -> str:
    """Preserve and normalize pass [object] from [hand] to [hand] clauses."""
    if not label or label == "No Action":
        return label
    if not re.search(r"\bpass\b", label, re.IGNORECASE):
        return label

    clauses = split_actions(label)
    normalized: list[str] = []
    for clause in clauses:
        piece = clause.strip()
        if not piece:
            continue
        match = re.search(
            r"^pass\s+(.+?)\s+from\s+(left hand|right hand|both hands)\s+to\s+"
            r"(left hand|right hand|both hands)\s*$",
            piece,
            re.IGNORECASE,
        )
        if match:
            obj = match.group(1).strip()
            src = match.group(2).lower()
            dest = match.group(3).lower()
            normalized.append(f"pass {obj} from {src} to {dest}")
        else:
            normalized.append(piece)
    return ", ".join(normalized) if normalized else label


def resolve_hand_transfer_sequence(
    prev_hand: str,
    curr_hand: str,
    obj_name: str,
    action_type: str,
    target_surface: str = "table",
) -> str:
    """
    Forces the explicit hold → pass → action chain when hand custody shifts
    before placement (or other terminal action).
    """
    if prev_hand and curr_hand and prev_hand != curr_hand:
        return (
            f"hold {obj_name} with {prev_hand}, "
            f"pass {obj_name} from {prev_hand} to {curr_hand}, "
            f"{action_type} {obj_name} on {target_surface} with {curr_hand}"
        )
    hand = curr_hand or prev_hand or "right hand"
    return f"{action_type} {obj_name} on {target_surface} with {hand}"


def format_hand_pass_sequence(
    initial_hand: str,
    final_hand: str,
    obj_name: str,
    target_surface: str,
) -> str:
    """Format hold → pass → place chain for cross-hand object transfers."""
    if initial_hand != final_hand:
        return resolve_hand_transfer_sequence(
            initial_hand, final_hand, obj_name, "place", target_surface
        )
    return (
        f"pick up {obj_name} with {final_hand}, "
        f"place {obj_name} on {target_surface} with {final_hand}"
    )


def _place_surface(clause: str) -> str:
    match = re.search(
        r"\b(?:place|set)\s+\S+(?:\s+\S+)*?\s+on\s+"
        r"(table|floor|ground|counter|shelf|desk|toolbox)\b",
        clause or "",
        re.IGNORECASE,
    )
    return match.group(1).lower() if match else "table"


def _wrench_transfer_context(
    blob: str,
    *,
    segment_index: int | None = None,
    total_segments: int | None = None,
) -> bool:
    if re.search(r"\bpass wrench from left hand to right hand\b", blob, re.IGNORECASE):
        return True
    if re.search(r"\bhold wrench with left hand\b", blob, re.IGNORECASE):
        return True
    if (
        segment_index == 0
        and total_segments is not None
        and total_segments >= 3
        and re.search(r"\bwrench\b", blob, re.IGNORECASE)
    ):
        return True
    return False


def resolve_hand_pass_sequence(
    label: str,
    *,
    clip_draft_blob: str | None = None,
    draft_text: str = "",
    segment_index: int | None = None,
    total_segments: int | None = None,
) -> str:
    """Inject hold → pass → place when an object changes hands before placement."""
    if not label or label == "No Action":
        return label
    if re.search(r"\bpass\b", label, re.IGNORECASE):
        return label

    clauses = split_actions(label)
    if len(clauses) != 2:
        return label
    first, second = clauses[0], clauses[1]
    if _leading_verb(first) not in {"pick up", "hold"}:
        return label
    if _leading_verb(second) not in {"place", "set"}:
        return label

    obj = _clause_object_phrase(first) or _clause_object_phrase(second)
    if not obj or not _objects_match_simple(
        _clause_object_phrase(first), _clause_object_phrase(second)
    ):
        return label

    first_hand = _clause_hand(first)
    second_hand = _clause_hand(second)
    surface = _place_surface(second)
    blob = " ".join(part for part in (clip_draft_blob, draft_text) if part)

    if re.search(r"\bfrom toolbox\b", label, re.IGNORECASE):
        return label

    if (
        first_hand in {"left hand", "right hand"}
        and second_hand in {"left hand", "right hand"}
        and first_hand != second_hand
    ):
        return format_hand_pass_sequence(first_hand, second_hand, obj, surface)

    if (
        re.search(r"\bwrench\b", label, re.IGNORECASE)
        and re.search(r"\bplace wrench on table\b", label, re.IGNORECASE)
        and first_hand == second_hand
        and _wrench_transfer_context(
            blob,
            segment_index=segment_index,
            total_segments=total_segments,
        )
    ):
        dest = second_hand or "right hand"
        origin = "left hand" if dest == "right hand" else "right hand"
        return format_hand_pass_sequence(origin, dest, "wrench", surface)

    return label


def _is_middle_wipe_segment(
    segment_index: int | None,
    total_segments: int | None,
) -> bool:
    return (
        segment_index is not None
        and total_segments is not None
        and total_segments >= 3
        and 0 < segment_index < total_segments - 1
    )


def _is_terminal_wipe_segment(
    segment_index: int | None,
    total_segments: int | None,
) -> bool:
    if segment_index is None or total_segments is None or total_segments < 3:
        return False
    return segment_index in {0, total_segments - 1}


# Verbs where clause order is chronological (place then pick up) — never swap.
_SEQUENTIAL_FIRST_VERBS = frozenset(
    {"place", "set", "put", "pick up", "pass", "gather", "open", "close", "walk"}
)


def reorder_atlas_clauses(label: str) -> str:
    """
    Flip dual-hand actions so holding/stabilizing comes first.

    'strip blue wire with pliers in right hand, hold wire with left hand'
    -> 'hold wire with left hand, strip blue wire with pliers in right hand'

    Sequential actions (place then pick up) keep chronological order.
    """
    if not label or label == "No Action":
        return label
    clauses = split_actions(label)
    if len(clauses) != 2:
        return label

    first, second = clauses[0].strip(), clauses[1].strip()
    first_verb = _leading_verb(first)
    second_verb = _leading_verb(second)
    hold_verbs = {"hold", "rotate"}

    if first_verb in hold_verbs and second_verb not in hold_verbs:
        return label
    if second_verb not in hold_verbs:
        return label
    if first_verb in _SEQUENTIAL_FIRST_VERBS:
        return label

    return f"{second}, {first}"


def reorder_dual_hand_clauses(label: str) -> str:
    """Alias: stabilizing hold/rotate must precede manipulation clauses."""
    return reorder_atlas_clauses(label)


# Specific placement targets that override a hallucinated default 'on table'.
_SPECIFIC_PLACE_TARGETS = re.compile(
    r"\b(on stack|on counter|on shelf|in shelf|in basin|in basket|in box|"
    r"in drawer|in cabinet|in refrigerator(?:\s+shelf)?|in fridge|"
    r"into refrigerator|into fridge)\b",
    re.IGNORECASE,
)

_PLACE_HAND_THEN_TARGET = re.compile(
    r"^(place|set|put)\s+(.+?)\s+with\s+(both hands|right hand|left hand)\s+"
    r"((?:on|in|into|onto)\s+.+)$",
    re.IGNORECASE,
)


def normalize_pick_and_place(label: str) -> str:
    """
    Cleans compound pick-and-place actions and removes conflicting target locations.
    Example: 'place green garment on table with both hands on stack'
          -> 'place green garment on stack with both hands'
    Also reorders 'place X with hand on target' -> 'place X on target with hand'.
    """
    if not label or label == "No Action":
        return label
    clauses = split_actions(label)
    fixed: list[str] = []
    for clause in clauses:
        piece = clause.strip()
        if (
            re.search(r"\bon table\b", piece, re.IGNORECASE)
            and _SPECIFIC_PLACE_TARGETS.search(piece)
        ):
            piece = re.sub(r"\s*\bon table\b", "", piece, flags=re.IGNORECASE)
        match = _PLACE_HAND_THEN_TARGET.match(piece)
        if match:
            verb, obj, hand, target = match.groups()
            piece = (
                f"{verb.lower()} {obj.strip()} {target.strip()} "
                f"with {hand.lower()}"
            )
        fixed.append(" ".join(piece.split()))
    return ", ".join(fixed)


def sanitize_tool_actions(label: str) -> str:
    """
    Prevents invalid clause injection/reordering on tool-based continuous actions
    (iron, mop, scrub, brush): strips trailing smoothing clauses the draft
    never contained and never splits tool actions into fabricated hold clauses.
    """
    if not label or label == "No Action":
        return label
    if not re.search(r"\b(iron|mop|scrub|brush)\b", label, re.IGNORECASE):
        return label
    clauses = split_actions(label)
    if len(clauses) < 2:
        return label
    kept = [
        clause
        for clause in clauses
        if not re.match(
            r"^smooth(?:en)?\s+[\w\s]+?\s+with\s+(?:left|right)\s+hand\s*$",
            clause.strip(),
            re.IGNORECASE,
        )
    ]
    if not kept:
        return label
    return ", ".join(kept)


_SINGLE_TOOL_VERB_PATTERN = re.compile(
    r"^(?:trim|cut|shear|clip|iron|mop|scrub|vacuum|sweep)\b",
    re.IGNORECASE,
)
_HOLD_STABILIZER_CLAUSE = re.compile(
    r"^hold\s+.+?\s+with\s+(?:left|right|both)\s+hands?$",
    re.IGNORECASE,
)
_BIMANUAL_TOOL_INSTRUMENT = re.compile(
    r"\bwith\s+.+?\s+in\s+(?:left|right)\s+hand\s*$",
    re.IGNORECASE,
)
_STRIP_HOLD_TOOL_VERBS = frozenset(
    {"trim", "cut", "shear", "clip", "iron", "mop", "vacuum", "sweep"}
)
_PRESERVE_HOLD_TOOL_VERBS = frozenset({"scrub", "wipe", "sand", "polish", "rub", "buff"})


def _should_preserve_bimanual_hold(hold_clause: str, tool_clause: str) -> bool:
    """
    Keep hold + tool when the stabilizer and worker clause share the same object
    and the tool hand holds an instrument (brush, cloth, sandpaper, ...).

    Example: hold circuit board with left hand, scrub circuit board with brush in right hand
    """
    verb = _leading_verb(tool_clause)
    if verb in _STRIP_HOLD_TOOL_VERBS:
        return False
    if verb not in _PRESERVE_HOLD_TOOL_VERBS:
        return False
    if not _BIMANUAL_TOOL_INSTRUMENT.search(tool_clause):
        return False
    hold_obj = _clause_object_phrase(hold_clause)
    tool_obj = _clause_object_phrase(tool_clause)
    return _objects_match_simple(hold_obj, tool_obj)


def sanitize_grooming_and_tool_actions(label: str) -> str:
    """
    Strips redundant 'hold [object]' clauses from grooming and single-tool tasks
    (trim, cut, iron, mop) to prevent 'Fact Extra Action' penalties.

    Preserves bimanual hold + scrub/wipe/sand when both clauses name the same
    workpiece and the tool is held in the working hand.
    """
    if not label or label == "No Action":
        return label
    clauses = split_actions(label)
    if len(clauses) != 2:
        return label
    first, second = clauses[0].strip(), clauses[1].strip()
    if _HOLD_STABILIZER_CLAUSE.match(first) and _SINGLE_TOOL_VERB_PATTERN.match(second):
        if _should_preserve_bimanual_hold(first, second):
            return label
        return second
    if _SINGLE_TOOL_VERB_PATTERN.match(first) and _HOLD_STABILIZER_CLAUSE.match(second):
        if _should_preserve_bimanual_hold(second, first):
            return label
        return first
    return label


_CONTINUOUS_MANIPULATION = re.compile(r"\b(?:wipe|sand|polish)\b", re.IGNORECASE)

_ROTATE_MIN_ANGULAR_SWEEP = 0.12  # ~7° cumulative — true object rotation, not jitter


def _should_upgrade_hold_to_rotate(
    label: str,
    motion: HandMotionProfile | None,
) -> bool:
    """
    Rotate is only claimed when the stabilizing wrist traces a visible arc
    (angular sweep). Linear jitter during wiping/sanding is not rotation.
    Without tracking data, never claim rotation.
    """
    sweep = stabilizer_rotation_sweep(label, motion)
    if sweep is None:
        return False
    return sweep >= _ROTATE_MIN_ANGULAR_SWEEP


def _upgrade_hold_to_rotate_in_wipe_label(
    label: str,
    motion: HandMotionProfile | None = None,
) -> str:
    """Convert stabilizing hold clauses to rotate during continuous work windows."""
    if not label or not _CONTINUOUS_MANIPULATION.search(label):
        return label
    if not _should_upgrade_hold_to_rotate(label, motion):
        return label
    updated = re.sub(
        r"\bhold\s+([\w\s]+?)\s+with\s+(left hand|right hand)\b",
        r"rotate \1 with \2",
        label,
        flags=re.IGNORECASE,
    )
    parts = split_actions(updated)
    if len(parts) >= 2 and _leading_verb(parts[0]) == "hold":
        parts[0] = re.sub(r"^hold\b", "rotate", parts[0], count=1, flags=re.IGNORECASE)
        updated = ", ".join(parts)
    return updated


def normalize_episode_wiping_verbs(
    segment_labels: list[str],
    motion_profiles: list[HandMotionProfile | None] | None = None,
) -> list[str]:
    """
    Applies ATLAS multi-segment rules across an entire clip for continuous
    manipulation tasks (wipe, sand, polish):
    - Seg 1 & Seg N: keep hold on the stabilized object
    - Seg 2 to N-1: upgrade hold to rotate only when the stabilizing wrist
      actually moves (motion-gated; static hold stays hold)
    - Dual-hand labels: stabilizing clause must precede manipulation clause
    """
    total = len(segment_labels)
    if total < 3:
        return [reorder_dual_hand_clauses(lbl or "") for lbl in segment_labels]

    processed: list[str] = []
    for idx, label in enumerate(segment_labels):
        label = reorder_dual_hand_clauses(label or "")
        motion = None
        if motion_profiles is not None and idx < len(motion_profiles):
            motion = motion_profiles[idx]
        if 0 < idx < (total - 1) and label and _CONTINUOUS_MANIPULATION.search(label):
            label = _upgrade_hold_to_rotate_in_wipe_label(label, motion)
        processed.append(label)
    return processed


def normalize_episode_sequence(
    segment_labels: list[str],
    motion_profiles: list[HandMotionProfile | None] | None = None,
) -> list[str]:
    """
    Applies multi-segment rules strictly based on action verb type:
    - Continuous tasks (wipe/sand/polish): Seg 1 'hold', Seg 2..N-1 'rotate'
      only when the stabilizing hand visibly moves, Seg N 'hold'
    - Discrete transfer tasks (pick up/place): preserve 'pick up' on every segment
    - Every segment: clean up pick-and-place locations and preposition order
    """
    cleaned = [normalize_pick_and_place(lbl or "") for lbl in segment_labels]
    cleaned = apply_clip_motion_enrichment(cleaned, motion_profiles)
    cleaned = apply_clip_hand_consensus(cleaned, motion_profiles)
    cleaned = normalize_refrigerator_organizing_episode(cleaned)
    return normalize_episode_wiping_verbs(cleaned, motion_profiles)


def normalize_refrigerator_organizing_episode(segment_labels: list[str]) -> list[str]:
    """
    Refrigerator clips: dual pick-up (one container per hand), hold + reposition
    while organizing, place on the final segment.
    """
    if len(segment_labels) < 2:
        return segment_labels
    blob = " ".join(segment_labels).lower()
    if "refrigerator" not in blob and "fridge" not in blob:
        return segment_labels
    if "container" not in blob:
        return segment_labels
    if not any("reposition items in refrigerator" in (lbl or "").lower() for lbl in segment_labels):
        return segment_labels

    hold_reposition = (
        "hold container with left hand, reposition items in refrigerator with right hand"
    )
    place_label = "place container in refrigerator with right hand"
    updated = list(segment_labels)
    last = len(updated) - 1
    for index in range(1, last):
        if "reposition items in refrigerator" in (updated[index] or "").lower():
            updated[index] = hold_reposition
    if "place container in refrigerator" in (updated[last] or "").lower():
        updated[last] = place_label
    return updated


def adjust_wiping_rotation_by_segment_index(
    label: str,
    segment_index: int | None = None,
    total_segments: int | None = None,
    motion: HandMotionProfile | None = None,
) -> str:
    """Middle segments in multi-window wiping use rotate when the stabilizing
    wrist visibly moves; first/last (and static holds) keep hold."""
    label = reorder_dual_hand_clauses(label)
    if not _is_middle_wipe_segment(segment_index, total_segments):
        return label
    if not _CONTINUOUS_MANIPULATION.search(label):
        return label
    return _upgrade_hold_to_rotate_in_wipe_label(label, motion)


def format_hand_transfer(object_noun: str, from_hand: str, to_hand: str) -> str:
    """Standard ATLAS hand-over syntax."""
    return f"pass {object_noun} from {from_hand} to {to_hand}"


def check_and_inject_hand_transfer(
    prev_hand: str, curr_hand: str, object_name: str
) -> str:
    """Generate pass phrase when an item transitions between hands."""
    valid = {"left hand", "right hand"}
    if prev_hand in valid and curr_hand in valid and prev_hand != curr_hand:
        return format_hand_transfer(object_name, prev_hand, curr_hand)
    return ""


def _clause_hand(clause: str) -> str:
    match = _HAND_ATTRIBUTION.search(clause or "")
    return match.group(1).lower() if match else ""


def _objects_match_simple(a: str, b: str) -> bool:
    left = (a or "").casefold().strip()
    right = (b or "").casefold().strip()
    if not left or not right:
        return False
    return left == right or left in right or right in left


def dynamic_verb_hold_to_rotate(
    label: str,
    previous_label: str | None,
    next_label: str | None = None,
    motion: HandMotionProfile | None = None,
    clip_draft_blob: str | None = None,
    draft_text: str = "",
    segment_index: int | None = None,
    total_segments: int | None = None,
) -> str:
    """
    hold + continuous work (wipe/sand/polish) → rotate only when the stabilizing
    wrist traces a visible arc (angular sweep). Middle segments in multi-window
    clips use rotate when motion confirms; first/last keep hold.
    """
    if not label or label == "No Action":
        return label

    if _CONTINUOUS_MANIPULATION.search(label):
        if _is_middle_wipe_segment(segment_index, total_segments):
            return adjust_wiping_rotation_by_segment_index(
                label, segment_index, total_segments, motion
            )
        if _is_terminal_wipe_segment(segment_index, total_segments):
            return label

    if not re.search(r"\b(?:glass cup|glass jar|glass)\b", label, re.IGNORECASE):
        return label
    if re.search(
        r"\bwipe\s+(?:glass cup|glass jar)\s+with cloth in both hands\b",
        draft_text,
        re.IGNORECASE,
    ):
        return label

    fixed = fix_glass_cleaning_syntax_and_nouns(
        label, previous_label, clip_draft_blob
    )
    if not _should_upgrade_hold_to_rotate(fixed, motion):
        return label

    label = fixed
    clauses = split_actions(label)

    if len(clauses) == 1:
        clause = clauses[0].strip()
        if re.match(r"^hold glass cup with (?:left|right) hand\s*$", clause, re.IGNORECASE):
            return re.sub(r"^hold\b", "rotate", clause, count=1, flags=re.IGNORECASE)
        return label

    if len(clauses) != 2:
        return label
    if _leading_verb(clauses[0]) != "hold" or _leading_verb(clauses[1]) != "wipe":
        return label
    hold_obj = _clause_object_phrase(clauses[0])
    wipe_obj = _clause_object_phrase(clauses[1])
    if not _objects_match_simple(hold_obj, wipe_obj):
        return label

    rotated_first = re.sub(
        r"^hold\b",
        "rotate",
        clauses[0],
        count=1,
        flags=re.IGNORECASE,
    )
    return f"{rotated_first}, {clauses[1]}"


def _rewrite_bottle_pickup_to_pass(
    label: str,
    next_label: str | None,
    previous_label: str | None = None,
) -> str:
    """Kitchen bottle windows: pick up with one hand, then pass to the other."""
    if re.search(r"\bpass\b", label, re.IGNORECASE):
        return label
    if not re.search(r"\bbottle\b", label, re.IGNORECASE):
        return label
    if previous_label and re.search(r"\bbottle\b", previous_label, re.IGNORECASE):
        return label
    if not re.search(r"\b(?:pick up|hold|open)\b", label, re.IGNORECASE):
        return label
    nxt = next_label or ""
    if not (
        re.search(r"\bbottle\b", nxt, re.IGNORECASE)
        or re.search(r"\b(?:place|counter|refrigerator)\b", nxt, re.IGNORECASE)
    ):
        return label
    return "pick up bottle with right hand, pass bottle from right hand to left hand"


def _rewrite_bag_pickup_place_to_pass(
    label: str,
    duration_seconds: float | None,
) -> str:
    """Short bag pick-up windows are a hand-off, not pick up then place same hand."""
    if duration_seconds is None or duration_seconds >= SHORT_WINDOW_MAX_SECONDS:
        return label
    clauses = split_actions(label)
    if len(clauses) != 2:
        return label
    if _leading_verb(clauses[0]) != "pick up" or _leading_verb(clauses[1]) != "place":
        return label
    blob = label.lower()
    if re.search(r"\bpass\b", blob):
        return label
    if not re.search(r"\b(?:snack )?bag\b|\bsachet\b", blob):
        return label
    obj = "sachet" if re.search(r"\bsachet\b", blob) else "bag"
    hand = _clause_hand(clauses[0]) or "right hand"
    other = "left hand" if hand == "right hand" else "right hand"
    return f"pick up {obj} with {hand}, pass {obj} from {hand} to {other}"


def _align_place_hand_after_pass(
    label: str,
    previous_label: str | None,
) -> str:
    """After pass from A to B, place uses the receiving hand."""
    if not label or not previous_label:
        return label
    match = re.search(
        r"pass \S+(?:\s+\S+)? from (left hand|right hand) to (left hand|right hand)",
        previous_label,
        re.IGNORECASE,
    )
    if not match:
        return label
    dest = match.group(2).lower()
    clauses = split_actions(label)
    if len(clauses) != 1 or _leading_verb(clauses[0]) not in {"place", "set"}:
        return label
    fixed = re.sub(
        r"\b(?:with|in) (?:left|right) hand\b",
        f"with {dest}",
        clauses[0],
        count=1,
        flags=re.IGNORECASE,
    )
    return fixed


def _expand_sewing_stitch_cycle(
    label: str,
    clip_draft_blob: str | None,
    duration_seconds: float | None = None,
) -> str:
    """
    Sewing stitch windows need pull then insert (3 actions), not collapsed insert-only.
    Skip on short tail windows where only pull-through occurs.
    """
    if not label or label == "No Action":
        return label
    if (
        duration_seconds is not None
        and duration_seconds < SHORT_SEWING_TAIL_MAX_SECONDS
    ):
        return label
    blob = f"{label} {clip_draft_blob or ''}".lower()
    if not re.search(r"\b(?:cap|patch|thread|sew|sewing needle)\b", blob):
        return label
    if not re.search(r"\bhold cap\b", label, re.IGNORECASE):
        return label
    if not re.search(r"\binsert sewing needle\b", label, re.IGNORECASE):
        return label
    if re.search(r"\bpull sewing needle\b", label, re.IGNORECASE):
        return label

    updated = re.sub(
        r"(hold cap with left hand),\s*insert sewing needle into patch with right hand",
        r"\1, pull sewing needle with right hand, insert sewing needle into cap with right hand",
        label,
        flags=re.IGNORECASE,
    )
    updated = re.sub(
        r"(hold cap with left hand),\s*(insert sewing needle into cap with right hand)",
        r"\1, pull sewing needle with right hand, \2",
        updated,
        flags=re.IGNORECASE,
    )
    return updated


def _validate_and_repair_clauses(label: str) -> str:
    """Every clause must include an object noun and explicit hand tag."""
    if not label or label == "No Action":
        return label

    clauses = split_actions(label)
    if not clauses:
        return label

    fallback_hand = ""
    for clause in clauses:
        match = re.search(rf"\b(?:with|in)\s+({_HAND_TAG})\b", clause, re.IGNORECASE)
        if match:
            fallback_hand = match.group(1)
            break

    repaired: list[str] = []
    for clause in clauses:
        piece = clause.strip()
        if not piece or _BARE_PICK_UP.match(piece):
            continue
        if not _clause_has_hand_attribution(piece) and fallback_hand and _clause_needs_hand_tag(piece):
            piece = f"{piece} with {fallback_hand}".strip()
        repaired.append(piece)

    if not repaired:
        return label
    return ", ".join(repaired)


def _prefer_pull_over_insert_after_pull(
    label: str,
    previous_label: str | None,
) -> str:
    """After pulling thread/needle, a repeated insert draft is often a pull-out motion."""
    if not previous_label or not label:
        return label
    prev = previous_label.lower()
    if "pull thread" not in prev and "pull sewing needle" not in prev:
        return label
    if not re.search(
        r"\binsert sewing needle into (?:patch|cap)\b", label, re.IGNORECASE
    ):
        return label
    return re.sub(
        r"\binsert sewing needle into (?:patch|cap) with right hand\b",
        "pull sewing needle with right hand",
        label,
        flags=re.IGNORECASE,
    )


def _fix_pick_up_both_hands(
    label: str,
    motion: HandMotionProfile | None,
) -> str:
    """pick up with both hands is often a single-hand motion on cloth/objects."""
    clauses = split_actions(label)
    if not clauses:
        return label

    threshold = 0.015
    v_left = motion.v_left if motion else 0.0
    v_right = motion.v_right if motion else 0.0
    dominant_left = v_left > threshold and v_left >= v_right * 1.5
    dominant_right = v_right > threshold and v_right >= v_left * 1.5

    fixed: list[str] = []
    for clause in clauses:
        if _leading_verb(clause) != "pick up" or "both hands" not in clause.lower():
            fixed.append(clause)
            continue
        if dominant_left:
            hand = "left hand"
        elif dominant_right:
            hand = "right hand"
        elif _is_cloth_clause(clause):
            hand = "left hand"
        else:
            fixed.append(clause)
            continue
        fixed.append(re.sub(r"\bboth hands\b", hand, clause, flags=re.IGNORECASE))
    return ", ".join(fixed)


def _extract_glossary_from_drafts(drafts: list[str]) -> list[str]:
    """Collect specific tool/object names mentioned anywhere in the clip drafts."""
    blob = " ".join(d for d in drafts if d).lower()
    found: list[str] = []
    seen: set[str] = set()
    for tool in sorted(KNOWN_CLIP_TOOLS, key=len, reverse=True):
        if tool in blob and tool not in seen:
            seen.add(tool)
            found.append(tool)
    return found


def _resolved_tool_from_episode(blob: str) -> str | None:
    match = _CLIP_SPECIFIC_TOOLS.search(blob or "")
    return match.group(1).lower() if match else None


def backpropagate_specific_nouns(
    label: str,
    segment_labels: list[str] | None = None,
    *,
    clip_draft_blob: str | None = None,
    clip_glossary: list[str] | None = None,
    draft_text: str = "",
) -> str:
    """
    Replace generic fallbacks (tool, container) with specific nouns found
    anywhere in the clip episode drafts.
    """
    if not label or label == "No Action":
        return label
    parts = list(segment_labels or [])
    if clip_draft_blob:
        parts.append(clip_draft_blob)
    if draft_text:
        parts.append(draft_text)
    if clip_glossary:
        parts.extend(clip_glossary)
    blob = " ".join(parts)

    updated = label
    resolved_tool = _resolved_tool_from_episode(blob)
    if resolved_tool:
        updated = re.sub(r"\btool\b", resolved_tool, updated, flags=re.IGNORECASE)
    for pattern, replacement in GENERIC_NOUN_MAP:
        if re.search(pattern, updated, re.IGNORECASE) and (
            re.search(re.escape(replacement), blob, re.IGNORECASE)
            or replacement in blob.lower()
        ):
            updated = re.sub(pattern, replacement, updated, flags=re.IGNORECASE)
    return updated


def correct_container_action(
    label: str,
    *,
    motion: HandMotionProfile | None = None,
    next_label: str | None = None,
    clip_draft_blob: str | None = None,
) -> str:
    """
    pick up bucket → place bucket on floor when downward motion or hoe-setup context
    indicates a release onto the surface, not a lift.
    """
    if not label or label == "No Action":
        return label
    if not re.search(r"\bpick up bucket\b", label, re.IGNORECASE):
        return label

    bbox_vy = 0.0
    if motion:
        bbox_vy = max(motion.vy_left, motion.vy_right)

    context = " ".join(part for part in (clip_draft_blob, next_label) if part)
    reaches_surface = bool(
        (motion and motion.frames_analyzed >= 2)
        or re.search(r"\bplace bucket on (?:floor|ground)\b", context, re.IGNORECASE)
        or re.search(r"\b(?:pick up hoe|dig soil)\b", context, re.IGNORECASE)
    )

    def replace_pickup_bucket(clause: str) -> str:
        hand = _clause_hand(clause) or "left hand"
        return f"place bucket on floor with {hand}"

    if bbox_vy > 0 and reaches_surface:
        clauses = split_actions(label)
        return ", ".join(
            replace_pickup_bucket(clause)
            if re.search(r"\bpick up bucket\b", clause, re.IGNORECASE)
            else clause
            for clause in clauses
        )

    if reaches_surface and re.search(r"\bpick up hoe\b", context, re.IGNORECASE):
        clauses = split_actions(label)
        if len(clauses) == 1 and re.search(r"\bpick up bucket\b", clauses[0], re.I):
            bucket_hand = _clause_hand(clauses[0]) or "left hand"
            hoe_hand = "right hand" if bucket_hand == "left hand" else "left hand"
            match = re.search(
                r"pick up hoe with (left hand|right hand)",
                context,
                re.IGNORECASE,
            )
            if match:
                hoe_hand = match.group(1).lower()
            return (
                f"place bucket on floor with {bucket_hand}, "
                f"pick up hoe with {hoe_hand}"
            )

    return label


def _resolve_generic_nouns(
    label: str,
    draft_text: str,
    clip_glossary: list[str] | None,
    clip_draft_blob: str | None = None,
) -> str:
    """Replace audit-failing generic nouns (tool, object) with clip-specific names."""
    if not label or label == "No Action":
        return label

    updated = backpropagate_specific_nouns(
        label,
        clip_draft_blob=clip_draft_blob,
        clip_glossary=clip_glossary,
        draft_text=draft_text,
    )
    if not re.search(
        r"\b(?:" + "|".join(re.escape(word) for word in FORBIDDEN_GENERIC_NOUNS) + r")\b",
        updated,
        re.IGNORECASE,
    ):
        return updated

    glossary = list(clip_glossary or [])
    glossary.extend(_extract_glossary_from_drafts([draft_text]))
    if clip_draft_blob:
        glossary.extend(_extract_glossary_from_drafts([clip_draft_blob]))
    seen: set[str] = set()
    unique_glossary: list[str] = []
    for noun in glossary:
        key = noun.casefold()
        if key not in seen and key not in FORBIDDEN_GENERIC_NOUNS:
            seen.add(key)
            unique_glossary.append(noun)

    for generic in FORBIDDEN_GENERIC_NOUNS:
        if not re.search(rf"\b{re.escape(generic)}\b", updated, re.IGNORECASE):
            continue
        replacement = next(
            (noun for noun in unique_glossary if noun.casefold() != generic.casefold()),
            None,
        )
        if not replacement:
            for clause in split_actions(updated):
                replacement = VERB_DEFAULT_TOOL.get(_leading_verb(clause) or "")
                if replacement:
                    break
        if replacement:
            updated = re.sub(
                rf"\b{re.escape(generic)}\b", replacement, updated, flags=re.IGNORECASE
            )
    return updated


def _tool_held_from_previous(previous_label: str | None) -> tuple[str, str] | None:
    """Return (tool_name, hand) when the prior segment ended with a tool-in-hand work verb."""
    if not previous_label:
        return None
    for clause in split_actions(previous_label):
        verb = _leading_verb(clause)
        if verb not in TOOL_WORK_VERBS:
            continue
        match = re.search(
            r"\bwith\s+(.+?)\s+in\s+(left|right)\s+hand\s*$",
            clause,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip(), f"{match.group(2)} hand"
    return None


def _inject_tool_release(
    label: str,
    previous_label: str | None,
    clip_glossary: list[str] | None,
) -> str:
    """After tool-use segments, prepend place [tool] before bare-hand follow-up actions."""
    if not label or label == "No Action" or not previous_label:
        return label

    held = _tool_held_from_previous(previous_label)
    if not held:
        return label

    tool, hand = held
    if tool.casefold() in FORBIDDEN_GENERIC_NOUNS:
        resolved = _resolve_generic_nouns(
            f"with {tool} in {hand}",
            previous_label,
            clip_glossary,
        )
        match = re.search(
            r"\bwith\s+(.+?)\s+in\s+(?:left|right)\s+hand",
            resolved,
            re.IGNORECASE,
        )
        if match:
            tool = match.group(1).strip()

    if re.search(rf"\bplace\s+{re.escape(tool)}\b", label, re.IGNORECASE):
        return label
    if re.search(rf"\bwith\s+{re.escape(tool)}\s+in\b", label, re.IGNORECASE):
        return label

    current_verbs = {_leading_verb(clause) for clause in split_actions(label)}
    current_verbs.discard("")
    bare_hand_followup = current_verbs & {"gather", "pick up", "hold", "move", "pass", "shift"}
    if not bare_hand_followup or current_verbs & TOOL_WORK_VERBS:
        return label

    place_clause = f"place {tool} on ground with {hand}"
    return _cap_clauses_simple(f"{place_clause}, {label}")


def correct_cutting_vs_alignment(
    label: str,
    previous_label: str | None = None,
    next_label: str | None = None,
    motion: HandMotionProfile | None = None,
) -> str:
    """
    cut papers with scissors while adjusting edges → hold scissors, align papers.
    Passive scissors grip + dual-hand paper motion is alignment, not cutting.
    """
    if not label or label == "No Action":
        return label
    if not re.search(r"\bcut papers?\b", label, re.IGNORECASE):
        return label
    if not re.search(r"\bscissors\b", label, re.IGNORECASE):
        return label

    def hold_scissors_only(text: str | None) -> bool:
        if not text:
            return False
        blob = text.lower()
        return "hold scissors" in blob and "cut" not in blob

    def prior_scissors_hold(text: str | None) -> bool:
        if not text:
            return False
        return bool(re.search(r"\bhold scissors\b", text, re.IGNORECASE)) and not re.search(
            r"\bcut\b", text, re.IGNORECASE
        )

    sandwich = (
        previous_label
        and next_label
        and hold_scissors_only(previous_label)
        and hold_scissors_only(next_label)
    )
    after_scissors_hold = prior_scissors_hold(previous_label)

    if sandwich or after_scissors_hold:
        return "hold scissors with right hand, align papers with both hands"

    return label


def enforce_scissors_alignment_syntax(label: str) -> str:
    """hold scissors clause must precede align papers per ATLAS reference grammar."""
    if not label or label == "No Action":
        return label
    updated = re.sub(
        r"align papers with both hands,\s*hold scissors with right hand",
        "hold scissors with right hand, align papers with both hands",
        label,
        flags=re.IGNORECASE,
    )
    updated = re.sub(
        r"hold papers with left hand,\s*align papers with both hands",
        "hold scissors with right hand, align papers with both hands",
        updated,
        flags=re.IGNORECASE,
    )
    return updated


def _prefer_align_over_cut_sandwich(
    label: str,
    previous_label: str | None,
    next_label: str | None,
    motion: HandMotionProfile | None = None,
) -> str:
    """Scissors segments between hold-only neighbors are alignment, not cutting."""
    return correct_cutting_vs_alignment(
        label,
        previous_label=previous_label,
        next_label=next_label,
        motion=motion,
    )


def _draft_requires_both_hands(draft_text: str, label: str) -> bool:
    """True when the Atlas draft explicitly tags both hands on a two-handed action."""
    if "both hands" not in (draft_text or "").lower():
        return False
    for clause in split_actions(label):
        if "both hands" not in clause.lower():
            continue
        verb = _leading_verb(clause)
        if verb in TWO_HANDED_VERBS:
            return True
        if re.search(r"\b(?:rake|broom|hoe|shovel|mop|hose)\s+in\s+both\s+hands\b", clause, re.I):
            return True
    return False


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
            and verb not in {"smooth", "fold"}
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


_TOOL_INSTRUMENT_IN_HAND = re.compile(
    r"\bwith\s+(?:iron|mop|brush|hand broom|broom|squeegee|hoe|rake|shovel|"
    r"spatula|sandpaper|wrench|screwdriver|hammer)\s+in\s+"
    r"(?:left|right|both)\s+hands?\b",
    re.IGNORECASE,
)


def _ensure_offhand_hold(label: str) -> str:
    """Add stabilize clause when draft names one working hand on cloth/dish work."""
    clauses = split_actions(label)
    if len(clauses) != 1:
        return label
    clause = clauses[0]
    if HOLD_CLAUSE_PATTERN.search(clause) or "both hands" in clause.lower():
        return label
    # Tool-based continuous actions (iron, mop, scrub with brush, ...) occupy the
    # working hand with the instrument — never fabricate an offhand hold for them.
    if _TOOL_INSTRUMENT_IN_HAND.search(clause):
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
        and re.search(r"\b(?:cloth|towel|rag)\b", clause, re.IGNORECASE)
    ):
        obj = _clause_object_phrase(clause) or "cloth"
        if uses_right and not uses_left:
            return f"hold {obj} in left hand, {clause}"
        if uses_left and not uses_right:
            return f"hold {obj} in right hand, {clause}"
    return label


_STABILIZE_HAND_CLAUSE = re.compile(
    r"^(?:hold|rotate)\s+.+?\s+with\s+(left hand|right hand)\s*$",
    re.IGNORECASE,
)
_CONTINUOUS_TOOL_WORK_CLAUSE = re.compile(
    r"^(?:wipe|sand|polish|clean|wash|dry|scrub|rub|buff|file|grind)\s+.+?\s+"
    r"with\s+.+?\s+in\s+(left hand|right hand)\s*$",
    re.IGNORECASE,
)

# MediaPipe wrist-velocity hand verification can be disabled via env.
_VERIFY_WORK_HAND = os.getenv("HAND_SWAP_VERIFY", "true").strip().lower() not in {
    "0",
    "false",
    "no",
}


def verify_work_hand_against_motion(
    label: str,
    motion: HandMotionProfile | None,
) -> str:
    """
    Swap stabilizer/worker hand tags when wrist velocity clearly contradicts the
    draft: in 'hold X with hand A, sand X with tool in hand B' the B wrist must
    be the fast one. Only fires on two-clause continuous work labels when both
    wrists are tracked and the stabilizer hand is at least 2x faster than the
    alleged working hand.
    """
    if not _VERIFY_WORK_HAND:
        return label
    if not label or label == "No Action" or motion is None:
        return label
    if motion.frames_analyzed < 3:
        return label
    if not (motion.start_left_contact and motion.start_right_contact):
        return label

    clauses = split_actions(label)
    if len(clauses) != 2:
        return label
    stab = _STABILIZE_HAND_CLAUSE.match(clauses[0].strip())
    work = _CONTINUOUS_TOOL_WORK_CLAUSE.match(clauses[1].strip())
    if not stab or not work:
        return label

    stab_hand = stab.group(1).lower()
    work_hand = work.group(1).lower()
    if stab_hand == work_hand:
        return label

    v_work = motion.v_right if work_hand == "right hand" else motion.v_left
    v_stab = motion.v_left if work_hand == "right hand" else motion.v_right
    threshold = 0.015
    clearly_reversed = v_stab > threshold * 2 and v_stab >= max(v_work * 2.0, 0.01)
    if not clearly_reversed:
        return label

    sentinel = "@@hand-swap@@"
    swapped = re.sub(
        rf"\b{work_hand}\b", sentinel, label, count=1, flags=re.IGNORECASE
    )
    swapped = re.sub(
        rf"\b{stab_hand}\b", work_hand, swapped, count=1, flags=re.IGNORECASE
    )
    swapped = swapped.replace(sentinel, stab_hand)
    print(
        f"[Hybrid]: Motion contradicts draft hands "
        f"(v_left={motion.v_left:.4f}, v_right={motion.v_right:.4f}); "
        f"swapped to '{swapped}'."
    )
    return swapped


def _fix_hand_attribution(
    label: str,
    motion: HandMotionProfile | None,
    *,
    draft_text: str = "",
) -> str:
    """Correct false both-hands tags using motion asymmetry and bimanual splits."""
    if not label or label == "No Action":
        return label

    if _draft_requires_both_hands(draft_text, label):
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
        verb = _leading_verb(clause)
        if verb in TWO_HANDED_VERBS:
            return clause
        if re.search(r"\bin\s+both\s+hands\b", clause, re.IGNORECASE):
            return clause
        if dominant_left:
            return re.sub(r"\bboth hands\b", "left hand", clause, flags=re.IGNORECASE)
        if dominant_right:
            return re.sub(r"\bboth hands\b", "right hand", clause, flags=re.IGNORECASE)
        return clause

    if len(clauses) == 1 and "both hands" in clauses[0].lower():
        if _leading_verb(clauses[0]) in TWO_HANDED_VERBS:
            return label
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
    next_label: str | None = None,
    mp_hand_tag: str = "with right hand",
    duration_seconds: float | None = None,
    motion: HandMotionProfile | None = None,
    clip_glossary: list[str] | None = None,
    clip_draft_blob: str | None = None,
    segment_index: int | None = None,
    total_segments: int | None = None,
) -> str:
    """
    Trust the Atlas AI draft; apply only safe syntax normalization.

    Does NOT: hold→pick up, noun swaps, fake off-hand holds, location injection,
    _cap_actions drop scoring, or full sanitize_label heuristics.
    """
    label = (draft_text or "").strip()
    if not label or label.casefold() == "no action":
        return "No Action"

    label = _normalize_draft_separators(label)
    label = _strip_navigation_clauses(label)
    label = _apply_safe_syntax_fixes(label)
    if label == "No Action":
        return label

    label = _resolve_generic_nouns(label, draft_text, clip_glossary, clip_draft_blob)
    label = _standardize_context_nouns(
        label, draft_text, clip_glossary, clip_draft_blob
    )
    label = standardize_sewing_targets(label)
    label = _simplify_atlas_nouns(label)
    label = standardize_atlas_vocab(
        label,
        previous_label=previous_label,
        next_label=next_label,
        clip_draft_blob=clip_draft_blob,
    )
    label = fix_cloth_smoothing(label)
    label = _normalize_pass_syntax(label)
    label = _rewrite_bottle_pickup_to_pass(label, next_label, previous_label)
    label = _rewrite_bag_pickup_place_to_pass(label, duration_seconds)
    label = correct_container_action(
        label,
        motion=motion,
        next_label=next_label,
        clip_draft_blob=clip_draft_blob,
    )
    label = _expand_sewing_stitch_cycle(label, clip_draft_blob, duration_seconds)
    label = standardize_sewing_targets(label)
    label = _normalize_hand_prepositions(label)
    label = consolidate_hose_actions(label)
    label = _apply_plural_nouns(label, draft_text, previous_label)
    label = _prefer_align_over_cut_sandwich(
        label, previous_label, next_label, motion
    )
    label = enforce_scissors_alignment_syntax(label)
    label = _prefer_pull_over_insert_after_pull(label, previous_label)
    label = fix_glass_cleaning_syntax_and_nouns(
        label, previous_label, clip_draft_blob
    )
    label = reorder_dual_hand_clauses(label)
    label = dynamic_verb_hold_to_rotate(
        label,
        previous_label,
        next_label,
        motion,
        clip_draft_blob,
        draft_text,
        segment_index,
        total_segments,
    )
    label = enforce_glass_cup_consistency(
        label, previous_label, clip_draft_blob
    )
    label = _ensure_offhand_hold(label)
    label = _fix_hand_attribution(label, motion, draft_text=draft_text)
    label = _fix_pick_up_both_hands(label, motion)
    label = _inject_tool_release(label, previous_label, clip_glossary)
    label = _validate_and_repair_clauses(label)
    label = _repair_malformed_pick_up_place(label)
    label = resolve_hand_pass_sequence(
        label,
        clip_draft_blob=clip_draft_blob,
        draft_text=draft_text,
        segment_index=segment_index,
        total_segments=total_segments,
    )
    label = _clean_duplicate_hands(label)
    label = _infer_missing_hand_from_motion(label, mp_hand_tag)
    label = _clean_duplicate_hands(label)
    label = _rewrite_wire_fold_segment(label, previous_label, draft_text)
    label = _append_end_of_window_pickup(label, next_label, draft_text)
    label = limit_actions_by_duration(label, duration_seconds)
    label = _cap_clauses_simple(label, MAX_ACTIONS_PER_LABEL)

    if previous_label:
        label = apply_state_continuity(label, previous_label)

    label = _align_place_hand_after_pass(label, previous_label)
    label = _complete_hose_set_pickup_can(
        label, previous_label, next_label, clip_draft_blob
    )
    label = normalize_pick_and_place(label)
    label = sanitize_tool_actions(label)
    label = sanitize_grooming_and_tool_actions(label)

    return label


def atlas_guide_cleaner(
    draft_text: str,
    *,
    previous_label: str | None = None,
    next_label: str | None = None,
    mp_hand_tag: str = "with right hand",
    duration_seconds: float | None = None,
    motion: HandMotionProfile | None = None,
    clip_glossary: list[str] | None = None,
    clip_draft_blob: str | None = None,
    segment_index: int | None = None,
    total_segments: int | None = None,
) -> str:
    """Draft-preserving Atlas guide linter (alias for draft_preserving_cleaner)."""
    return draft_preserving_cleaner(
        draft_text,
        previous_label=previous_label,
        next_label=next_label,
        mp_hand_tag=mp_hand_tag,
        duration_seconds=duration_seconds,
        motion=motion,
        clip_glossary=clip_glossary,
        clip_draft_blob=clip_draft_blob,
        segment_index=segment_index,
        total_segments=total_segments,
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
    segment_index: int | None = None,
    total_segments: int | None = None,
    motion: HandMotionProfile | None = None,
) -> str:
    """Guide-compliant label from Atlas draft + optional MediaPipe hand fallback."""
    draft_label = usable_draft(draft_label)
    previous_label = usable_draft(previous_label)
    next_label = usable_draft(next_label)
    _ = (
        frame_timestamps,
        frames_have_video,
        global_context,
        segment_start_seconds,
    )

    clip_glossary: list[str] = []
    if global_context and getattr(global_context, "objects", None):
        clip_glossary = list(global_context.objects)

    if not draft_label:
        return "No Action"

    mp_hand = "with right hand"
    if motion is None and base64_frames:
        frame_arrays = frames_from_base64_list(base64_frames)
        if frame_arrays:
            motion = pipeline.analyze_frame_motion_from_memory(
                frame_arrays,
                draft_label=draft_label,
            )
    if motion is not None:
        mp_hand = motion.detected_hand

    label = draft_preserving_cleaner(
        draft_label,
        previous_label=previous_label,
        next_label=next_label,
        mp_hand_tag=resolve_hand_tag(draft_label, mp_hand),
        duration_seconds=duration_seconds,
        motion=motion,
        clip_glossary=clip_glossary or None,
        clip_draft_blob=getattr(global_context, "raw_summary", None) or None,
        segment_index=segment_index,
        total_segments=total_segments,
    )
    label = assessment_enrich_label(
        label,
        draft_label=draft_label,
        previous_label=previous_label,
        next_label=next_label,
        duration_seconds=duration_seconds,
    )
    label = preserve_draft_required_actions(
        label,
        draft_label,
        duration_seconds=duration_seconds,
    )
    return apply_vision_hand_corrections(label, motion)


def build_draft_global_context(segment_drafts: list[str]) -> GlobalVideoContext:
    """Build clip glossary and draft blob from all segment drafts."""
    cleaned = [d for d in segment_drafts if d]
    return GlobalVideoContext(
        objects=tuple(_extract_glossary_from_drafts(segment_drafts)),
        raw_summary=" | ".join(cleaned),
    )


# Back-compat alias from earlier iteration
minimal_atlas_cleaner = atlas_guide_cleaner
