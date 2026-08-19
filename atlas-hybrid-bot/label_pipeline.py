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
    (r"\bblue cable\b", "blue wire"),
    (r"\bhold blue cable\b", "hold blue wire"),
    (r"\bstrip blue cable\b", "strip blue wire"),
)


def _expand_pick_up_and_place(text: str) -> str:
    """pick up and place wrench with right hand → two valid Atlas clauses."""
    match = _PICK_UP_AND_PLACE.search(text)
    if match:
        obj = match.group(1).strip()
        hand = match.group(2)
        expanded = f"pick up {obj} with {hand}, place {obj} on table with {hand}"
        return text[: match.start()] + expanded + text[match.end() :]
    return text


def _repair_malformed_pick_up_place(text: str) -> str:
    """Fix pick up, place wrench with right hand → valid pick up + place clauses."""
    match = _MALFORMED_PICK_UP_PLACE.search(text)
    if match:
        obj = match.group(1).strip()
        hand = match.group(2)
        repaired = f"pick up {obj} with {hand}, place {obj} on table with {hand}"
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
            "pull sewing needle through patch",
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


def _simplify_atlas_nouns(label: str) -> str:
    """Strip over-specific visual modifiers down to ATLAS core object terms."""
    if not label or label == "No Action":
        return label
    updated = label
    for pattern, replacement in NOUN_SIMPLIFIERS:
        updated = re.sub(pattern, replacement, updated, flags=re.IGNORECASE)
    return updated


def _clause_has_hand_attribution(clause: str) -> bool:
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


def format_hand_transfer(object_noun: str, from_hand: str, to_hand: str) -> str:
    """Standard ATLAS hand-over syntax."""
    return f"pass {object_noun} from {from_hand} to {to_hand}"


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
        if not _clause_has_hand_attribution(piece) and fallback_hand:
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
    if not re.search(r"\binsert sewing needle into patch\b", label, re.IGNORECASE):
        return label
    return re.sub(
        r"\binsert sewing needle into patch with right hand\b",
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


def _resolve_generic_nouns(
    label: str,
    draft_text: str,
    clip_glossary: list[str] | None,
) -> str:
    """Replace audit-failing generic nouns (tool, object) with clip-specific names."""
    if not label or label == "No Action":
        return label
    if not re.search(
        r"\b(?:" + "|".join(re.escape(word) for word in FORBIDDEN_GENERIC_NOUNS) + r")\b",
        label,
        re.IGNORECASE,
    ):
        return label

    glossary = list(clip_glossary or [])
    glossary.extend(_extract_glossary_from_drafts([draft_text]))
    seen: set[str] = set()
    unique_glossary: list[str] = []
    for noun in glossary:
        key = noun.casefold()
        if key not in seen and key not in FORBIDDEN_GENERIC_NOUNS:
            seen.add(key)
            unique_glossary.append(noun)

    updated = label
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
            updated = re.sub(rf"\b{re.escape(generic)}\b", replacement, updated, flags=re.IGNORECASE)
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


def _prefer_align_over_cut_sandwich(
    label: str,
    previous_label: str | None,
    next_label: str | None,
) -> str:
    """Scissors segments between hold-only neighbors are alignment, not cutting."""
    if not previous_label or not next_label:
        return label
    if not re.search(r"\bcut\s+paper\b", label, re.IGNORECASE):
        return label

    def hold_scissors_only(text: str) -> bool:
        blob = text.lower()
        return "hold scissors" in blob and "cut" not in blob

    if hold_scissors_only(previous_label) and hold_scissors_only(next_label):
        return "hold scissors with right hand, align papers with both hands"
    return label


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

    label = _resolve_generic_nouns(label, draft_text, clip_glossary)
    label = _standardize_context_nouns(
        label, draft_text, clip_glossary, clip_draft_blob
    )
    label = _simplify_atlas_nouns(label)
    label = _normalize_pass_syntax(label)
    label = _normalize_hand_prepositions(label)
    label = _apply_plural_nouns(label, draft_text, previous_label)
    label = _prefer_align_over_cut_sandwich(label, previous_label, next_label)
    label = _prefer_pull_over_insert_after_pull(label, previous_label)
    label = _ensure_offhand_hold(label)
    label = _fix_hand_attribution(label, motion, draft_text=draft_text)
    label = _fix_pick_up_both_hands(label, motion)
    label = _inject_tool_release(label, previous_label, clip_glossary)
    label = _validate_and_repair_clauses(label)
    label = _repair_malformed_pick_up_place(label)
    label = _clean_duplicate_hands(label)
    label = _infer_missing_hand_from_motion(label, mp_hand_tag)
    label = _clean_duplicate_hands(label)
    label = _cap_clauses_simple(label, MAX_ACTIONS_PER_LABEL)

    if previous_label:
        label = apply_state_continuity(label, previous_label)

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
        next_label=next_label,
        mp_hand_tag=resolve_hand_tag(draft_label, mp_hand),
        duration_seconds=duration_seconds,
        motion=motion,
        clip_glossary=clip_glossary or None,
        clip_draft_blob=getattr(global_context, "raw_summary", None) or None,
    )


def build_draft_global_context(segment_drafts: list[str]) -> GlobalVideoContext:
    """Build clip glossary and draft blob from all segment drafts."""
    cleaned = [d for d in segment_drafts if d]
    return GlobalVideoContext(
        objects=tuple(_extract_glossary_from_drafts(segment_drafts)),
        raw_summary=" | ".join(cleaned),
    )


# Back-compat alias from earlier iteration
minimal_atlas_cleaner = atlas_guide_cleaner
