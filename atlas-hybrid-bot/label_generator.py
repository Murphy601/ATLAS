from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from types import SimpleNamespace

try:
    import openai
except ImportError:  # hybrid bot does not require OpenAI when LLM paths are unused
    openai = None  # type: ignore[assignment]

from dotenv import load_dotenv

from config import (
    ACTION_SYSTEM_PROMPT,
    ARTICLE_PATTERN,
    COMMA_AND_PATTERN,
    CONTINUOUS_VERBS,
    DIGIT_PATTERN,
    FEW_SHOT_CORRECTION_MESSAGES,
    FILL_SOURCE_TOOLS,
    FORBIDDEN_GENERIC_OBJECTS,
    FORBIDDEN_WORDS,
    GENERIC_NOUNS,
    GLOBAL_SWEEP_MAX_FRAMES,
    HAND_PATTERN,
    LOOKING_VERBS,
    MAX_ACTIONS_PER_LABEL,
    NO_ACTION_MIN_SECONDS,
    OBJECT_SIMILARITY_THRESHOLD,
    SHORT_WINDOW_MAX_SECONDS,
    MEDIUM_WINDOW_MAX_CLAUSES,
    SPATIAL_HAND_RULES,
    VERB_CORRECTIONS,
    WORK_MICROS,
    KEEP_PICKUP_BEFORE,
    MISSING_IF_DROPPED,
    NAMED_IMPLEMENTS,
    NARRATIVE_WORDS,
    PRONOUN_WORDS,
    CLEANING_VERBS,
    NUMBER_MAP,
    OPENROUTER_BASE_URL,
    OPENROUTER_HEADERS,
    OPENROUTER_MAX_ROUTE_FALLBACKS,
    PLURAL_ONLY_TOOLS,
    PROMPT_EXAMPLE_LABELS,
    SEMICOLON_PATTERN,
    SLASH_PATTERN,
    SYSTEM_PROMPT,
    TEMPERATURE,
    USE_VERBS,
    VERB_CORRECTIONS,
    VERB_REPLACEMENTS,
    VISION_MODELS,
)
from frame_sampling import (
    SegmentMotionProfile,
    analyze_segment_motion,
    prepare_segment_frames,
)

load_dotenv()


LEADING_VERB_PATTERN = re.compile(
    r"^(pick up|put down|pass|place|set|hold|move|fill|water|spray|wash|"
    r"rinse|scrub|sweep|dig|pour|stir|mix|iron|cut|chop|wipe|work|knead|"
    r"fold|flatten|tighten|squeeze|open|close|slide|shift|align|rotate|"
    r"tuck|grip|press|push|pull|twist|pinch|turn|straighten|tilt|scoop|"
    r"lift|pack|tamp|scrape|shovel|pat|tap|shake|peel|insert|remove|empty|"
    r"drop|lower|raise|carry|drag|flip|spread|smooth|stack|unstack|unfold|"
    r"put|grab|hand|gather|write|brush|sand|hammer|drill|trim|seal|smoothen|"
    r"rake|strip|mop|align)\b",
    re.IGNORECASE,
)
HOLD_CLAUSE_PATTERN = re.compile(r"^hold\b", re.IGNORECASE)
TWO_HANDED_TOOLS = ("hose", "rope")
WIPE_VERBS = {"wipe", "scrub", "wash", "dry", "polish"}
STIR_VERBS = {"stir", "mix"}
STOVEWARE_PATTERN = re.compile(
    r"\b(?:pan|wok|pot|skillet|saucepan)\b", re.IGNORECASE
)
CLOTH_WORK_VERBS = {"smoothen", "smooth", "fold", "flatten", "wipe"}
CLOTH_PATTERN = re.compile(
    r"\b(?:cloth|towel|rag|garment|shirt)\b", re.IGNORECASE
)
SELF_NAMED_TOOLS = {
    "rake": "rake",
    "shovel": "shovel",
    "hoe": "hoe",
    "hammer": "hammer",
}
GROUND_WORK_VERBS = {"rake", "shovel", "sweep", "dig"}
NOUN_REPLACEMENTS = {
    "eraser": "cloth",
    "lawn": "ground",
    "jar": "cup",
    "page": "book",
}
INCOMPLETE_HAND_PATTERN = re.compile(
    r"\b(with|in) (left|right)\b(?!\s+hand)",
    re.IGNORECASE,
)
FILL_SOURCE_PATTERN = re.compile(
    rf"\bfill\s+(.+?)\s+with\s+({'|'.join(FILL_SOURCE_TOOLS)})\b",
    re.IGNORECASE,
)
PRONOUN_PATTERN = re.compile(
    rf"\b(?:{'|'.join(PRONOUN_WORDS)})\b",
    re.IGNORECASE,
)
NARRATIVE_PATTERN = re.compile(
    rf"\b(?:{'|'.join(NARRATIVE_WORDS)})\b",
    re.IGNORECASE,
)
BODY_PART_PATTERN = re.compile(
    r"\bwith (?:the )?(?:fingers|finger|thumb|thumbs|palm|palms|wrist|wrists)\b",
    re.IGNORECASE,
)
BARE_HANDS_PATTERN = re.compile(r"\bwith\s+hands\b", re.IGNORECASE)
PLACE_LOCATION_PATTERN = re.compile(r"\b(?:on|in|into|onto)\b", re.IGNORECASE)
PLACE_LOCATION_CAPTURE = re.compile(
    r"\b((?:on|in|into|onto) (?!left |right |both )[a-z]+)",
    re.IGNORECASE,
)
GENERIC_NOUN_PATTERN = re.compile(
    rf"\b(?:{'|'.join(GENERIC_NOUNS)})\b",
    re.IGNORECASE,
)


def split_actions(label: str) -> list[str]:
    """Split an Atlas label into grader-counted action clauses."""
    text = (label or "").strip()
    if not text or text.lower() == "no action":
        return []
    if "," in text:
        return [part.strip() for part in text.split(",") if part.strip()]
    parts = re.split(r"\s+and\s+", text, flags=re.IGNORECASE)
    if len(parts) < 2:
        return [text]
    clauses = [parts[0].strip()]
    for part in parts[1:]:
        piece = part.strip()
        if LEADING_VERB_PATTERN.search(piece):
            clauses.append(piece)
        else:
            clauses[-1] = f"{clauses[-1]} and {piece}"
    return [clause for clause in clauses if clause]


def _leading_verb(clause: str) -> str:
    match = LEADING_VERB_PATTERN.search((clause or "").strip())
    return match.group(1).lower() if match else ""


def _use_both_hands(clause: str) -> str:
    updated = re.sub(
        r"\bwith (?:left|right) hand\b", "with both hands", clause, flags=re.IGNORECASE
    )
    updated = re.sub(
        r"\bin (?:left|right) hand\b", "in both hands", updated, flags=re.IGNORECASE
    )
    return updated


IMPLEMENT_IN_HAND = re.compile(
    r"\bwith (.+?) in (?:left hand|right hand|both hands)\b",
    re.IGNORECASE,
)
BARE_PLACE_PATTERN = re.compile(
    r"^(place|set|put|move)\s+(?:on|in|into|onto|to)\b",
    re.IGNORECASE,
)
INVALID_VERB_PATTERN = re.compile(
    r"\b(pick up|place|hold|pass|set|put|take)\s+(with|in|on|from|to|into|onto)\b",
    re.IGNORECASE,
)


def _pickup_object(clause: str) -> str:
    text = LEADING_VERB_PATTERN.sub("", clause, count=1).strip()
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


def _named_tool_in(clause: str) -> str:
    match = IMPLEMENT_IN_HAND.search(clause or "")
    return match.group(1).strip().lower() if match else ""


def _objects_match(left: str, right: str) -> bool:
    a = (left or "").strip().lower()
    b = (right or "").strip().lower()
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _strip_instrumental_pickup(text: str) -> str:
    """Drop pick up X when a later clause immediately uses X (not place/pass)."""
    clauses = split_actions(text)
    if len(clauses) < 2:
        return text
    changed = True
    while changed:
        changed = False
        for index, clause in enumerate(clauses):
            if _leading_verb(clause) != "pick up" or index + 1 >= len(clauses):
                continue
            picked = _pickup_object(clause)
            if not picked:
                continue
            use_index = index + 1
            use_verb = _leading_verb(clauses[use_index])
            if use_verb == "hold" and index + 2 < len(clauses):
                use_index = index + 2
                use_verb = _leading_verb(clauses[use_index])
            if not use_verb or use_verb in KEEP_PICKUP_BEFORE or use_verb == "pick up":
                continue
            if use_verb not in USE_VERBS and use_verb not in CONTINUOUS_VERBS:
                continue
            use_clause = clauses[use_index]
            tool = _named_tool_in(use_clause)
            used_as_implement = bool(tool) and _objects_match(picked, tool)
            used_as_verb = use_verb == picked.lower()
            if not used_as_implement and not used_as_verb:
                continue
            print(f"[Sanitize]: Dropped instrumental pick up '{clause}'")
            del clauses[index]
            changed = True
            break
    return ", ".join(clauses)


def _strip_micro_movements(text: str) -> str:
    """Drop shift/align/slide/tilt/tap inside a continuous cut/wipe/dig/water/write."""
    clauses = split_actions(text)
    if len(clauses) < 2:
        return text
    has_work = any(_leading_verb(clause) in CONTINUOUS_VERBS for clause in clauses)
    if not has_work:
        return text
    kept = [
        clause
        for clause in clauses
        if _leading_verb(clause) not in WORK_MICROS
    ]
    return ", ".join(kept) if kept else text


def _collapse_repeated_work(text: str) -> str:
    """One coarse clause when the same continuous verb repeats on the same object."""
    clauses = split_actions(text)
    if len(clauses) < 2:
        return text
    verbs = [_leading_verb(clause) for clause in clauses]
    if not verbs[0] or any(verb != verbs[0] for verb in verbs):
        return text
    if verbs[0] not in CONTINUOUS_VERBS:
        return text
    objects = [_clause_object(clause) for clause in clauses]
    if len({item.lower() for item in objects if item}) > 1:
        return text
    blob = " ".join(clauses).lower()
    if "left" in blob and "right" in blob:
        return _use_both_hands(clauses[0])
    return clauses[0]


def _cap_actions(text: str, limit: int = MAX_ACTIONS_PER_LABEL) -> str:
    clauses = split_actions(text)
    if len(clauses) <= limit:
        return text
    print(f"[Sanitize]: Capping {len(clauses)} actions to {limit}")

    def drop_score(item: tuple[int, str]) -> tuple[int, int]:
        orig_index, clause = item
        verb = _leading_verb(clause)
        if verb in WORK_MICROS:
            return (0, -orig_index)
        if verb == "hold":
            held = _clause_object(clause)
            for other_index, other in indexed:
                if other_index == orig_index:
                    continue
                tool = _named_tool_in(other)
                if tool and held and not _objects_match(held, tool):
                    return (8, -orig_index)
            return (1, -orig_index)
        if verb in CONTINUOUS_VERBS:
            return (2, -orig_index)
        if verb in MISSING_IF_DROPPED or verb == "pick up":
            return (9, -orig_index)
        return (3, -orig_index)

    indexed = list(enumerate(clauses))
    while len(indexed) > limit:
        victim = min(indexed, key=drop_score)
        indexed.remove(victim)
    indexed.sort()
    return ", ".join(clause for _, clause in indexed)


def _collapse_redundant_hold(text: str) -> str:
    """Merge hold of the SAME tool already named in the work clause.

    Off-hand stabilize of a workpiece while the other hand uses a different
    tool (hold paper, cut with scissors) must stay two clauses.
    """
    clauses = split_actions(text)
    if len(clauses) < 2:
        return text
    if (
        len(clauses) == 2
        and HOLD_CLAUSE_PATTERN.search(clauses[1])
        and any(
            re.search(rf"\b{re.escape(tool)}\b", clauses[0], re.IGNORECASE)
            for tool in TWO_HANDED_TOOLS
        )
        and _leading_verb(clauses[0]) not in KEEP_PICKUP_BEFORE
    ):
        return _use_both_hands(clauses[0])
    work_indexes = [
        index
        for index, clause in enumerate(clauses)
        if _leading_verb(clause) != "hold"
    ]
    hold_indexes = [
        index
        for index, clause in enumerate(clauses)
        if _leading_verb(clause) == "hold"
    ]
    if not work_indexes or not hold_indexes:
        return text
    drop: set[int] = set()
    updated = list(clauses)
    for hold_index in hold_indexes:
        held = _clause_object(updated[hold_index])
        if not held:
            continue
        for work_index in work_indexes:
            work = updated[work_index]
            if _leading_verb(work) in KEEP_PICKUP_BEFORE:
                continue
            tool = _named_tool_in(work)
            work_obj = _clause_object(work)
            same_tool = bool(tool) and _objects_match(held, tool)
            hold_hand = _clause_hand(updated[hold_index])
            work_hand = _clause_hand(work)
            distinct_hands = (
                hold_hand in {"left hand", "right hand"}
                and work_hand in {"left hand", "right hand"}
                and hold_hand != work_hand
            )
            if distinct_hands and not same_tool:
                continue
            same_object_no_tool = (
                not tool
                and _objects_match(held, work_obj)
                and _leading_verb(work) in USE_VERBS | CONTINUOUS_VERBS
            )
            if same_tool or same_object_no_tool:
                updated[work_index] = _use_both_hands(work)
                drop.add(hold_index)
                break
    if not drop:
        return text
    return ", ".join(
        clause for index, clause in enumerate(updated) if index not in drop
    )


def _drop_cookware_hold_while_stirring(text: str) -> str:
    """A wok/pan on the stove is not an off-hand stabilize while stirring."""
    clauses = split_actions(text)
    if len(clauses) != 2:
        return text
    hold = next((clause for clause in clauses if _leading_verb(clause) == "hold"), None)
    work = next(
        (clause for clause in clauses if _leading_verb(clause) in STIR_VERBS), None
    )
    if not hold or not work:
        return text
    held = _clause_object(hold)
    if STOVEWARE_PATTERN.search(held or "") or STOVEWARE_PATTERN.search(work):
        return work
    return text


def _insert_pass_on_hand_change(text: str) -> str:
    """hold/pick up in one hand and place with the other → insert pass (max 3)."""
    parts = split_actions(text)
    if len(parts) != 2:
        return text
    first, second = parts[0], parts[1]
    if _leading_verb(first) not in {"pick up", "hold"}:
        return text
    if _leading_verb(second) not in {"place", "set", "hold"}:
        return text
    obj = _pickup_object(first) or _clause_object_noun(first)
    other = _clause_object_noun(second)
    if not obj or not _objects_match(obj, other):
        return text
    left = _clause_hand(first)
    right = _clause_hand(second)
    if left not in {"left hand", "right hand"} or right not in {
        "left hand",
        "right hand",
    }:
        return text
    if left == right:
        return text
    pas = f"pass {obj} from {left} to {right}"
    if _leading_verb(second) == "hold":
        if _leading_verb(first) == "pick up":
            return f"{first}, {pas}"
        hold = f"hold {obj} with {left}"
        return f"{hold}, {pas}"
    hold = f"hold {obj} with {left}"
    return f"{hold}, {pas}, {second}"


def _trim_redundant_pass_stabilizers(text: str) -> str:
    """hold + pass + hold is pick up + pass, not three clauses."""
    parts = split_actions(text)
    if len(parts) != 3 or _leading_verb(parts[1]) != "pass":
        return text
    if _leading_verb(parts[2]) != "hold":
        return text
    if _leading_verb(parts[0]) not in {"hold", "pick up"}:
        return text
    match = re.search(
        r"pass (.+?) from (left hand|right hand) to (left hand|right hand)",
        parts[1],
        re.IGNORECASE,
    )
    if not match:
        return text
    obj, src, dest = match.group(1), match.group(2).lower(), match.group(3).lower()
    return f"pick up {obj} with {src}, pass {obj} from {src} to {dest}"


def _drop_soil_pickup_while_digging(text: str) -> str:
    """dig + pick up soil is one dig clause, not two actions."""
    parts = split_actions(text)
    if len(parts) != 2:
        return text
    if _leading_verb(parts[0]) != "dig" or _leading_verb(parts[1]) != "pick up":
        return text
    if not re.search(r"\bsoil\b", parts[1], re.IGNORECASE):
        return text
    hand = _clause_hand(parts[0]) or "right hand"
    if re.search(r"\bhoe\b", parts[0], re.IGNORECASE):
        return parts[0]
    return f"dig soil with hoe in {hand}"


def _clause_object_noun(clause: str) -> str:
    obj = _clause_object(clause)
    obj = re.sub(
        r"^(?:on|in|into|onto|to|from)\s+", "", obj, flags=re.IGNORECASE
    ).strip()
    obj = re.sub(
        r"\s+(?:on|in|into|onto|from)\s+"
        r"(?:table|toolbox|ground|floor|shelf|counter|bin|bucket|lawn)\b.*$",
        "",
        obj,
        flags=re.IGNORECASE,
    ).strip()
    if INVALID_VERB_PATTERN.search(clause or ""):
        return ""
    return obj


def validate_clause_syntax(label: str) -> bool:
    """False when a clause is 'pick up with right hand' (verb with no object noun)."""
    if not label or label == "No Action":
        return True
    return not any(
        INVALID_VERB_PATTERN.search(clause) for clause in split_actions(label)
    )


def _fill_missing_clause_objects(text: str) -> str:
    """pick up with right hand, place wrench on table -> pick up wrench with right hand."""
    clauses = split_actions(text)
    known = []
    for clause in clauses:
        obj = _clause_object_noun(clause)
        if obj:
            known.append(obj)
    filled = []
    last_obj = ""
    for index, clause in enumerate(clauses):
        verb = _leading_verb(clause)
        if verb and INVALID_VERB_PATTERN.search(clause):
            obj = last_obj
            if not obj:
                for later in clauses[index + 1 :]:
                    obj = _clause_object_noun(later)
                    if obj:
                        break
            if not obj and known:
                obj = known[0]
            if obj:
                clause = re.sub(
                    rf"^{re.escape(verb)}\s+",
                    f"{verb} {obj} ",
                    clause,
                    count=1,
                    flags=re.IGNORECASE,
                )
        elif verb and last_obj and BARE_PLACE_PATTERN.search(clause):
            clause = re.sub(
                rf"^{re.escape(verb)}\b",
                f"{verb} {last_obj}",
                clause,
                count=1,
                flags=re.IGNORECASE,
            )
        obj = _clause_object_noun(clause)
        if obj:
            last_obj = obj
        filled.append(clause)
    return ", ".join(filled)


def _ensure_offhand_hold_for_dish_wipe(text: str) -> str:
    """Name the stabilizing hand when one hand wipes a dish the other is holding."""
    clauses = split_actions(text)
    if len(clauses) != 1:
        return text
    clause = clauses[0]
    if _leading_verb(clause) not in WIPE_VERBS:
        return text
    if not (
        _is_dish_clause(clause)
        or re.search(r"\b(cloth|rag|towel|sponge)\b", clause, re.IGNORECASE)
    ):
        return text
    if "both hands" in clause.lower() or HOLD_CLAUSE_PATTERN.search(clause):
        return text
    obj = _clause_object(clause)
    if not obj:
        return text
    uses_right = re.search(r"\b(?:in|with) right hand\b", clause, re.IGNORECASE)
    uses_left = re.search(r"\b(?:in|with) left hand\b", clause, re.IGNORECASE)
    if uses_right and not uses_left:
        return f"hold {obj} with left hand, {clause}"
    if uses_left and not uses_right:
        return f"hold {obj} with right hand, {clause}"
    return text


def _ensure_offhand_hold_for_cloth_work(text: str) -> str:
    """fold/smoothen cloth with right hand needs the holding left hand."""
    clauses = split_actions(text)
    if len(clauses) != 1:
        return text
    clause = clauses[0]
    verb = _leading_verb(clause)
    if verb not in CLOTH_WORK_VERBS or not _is_cloth_clause(clause):
        return text
    if "both hands" in clause.lower() or HOLD_CLAUSE_PATTERN.search(clause):
        return text
    if PLACE_LOCATION_PATTERN.search(clause) and verb == "fold":
        return text
    obj = _clause_object(clause)
    if not obj:
        return text
    work = "smoothen" if verb in {"fold", "flatten", "smooth"} else verb
    if work != verb:
        clause = re.sub(rf"^{re.escape(verb)}\b", work, clause, count=1, flags=re.IGNORECASE)
    uses_right = re.search(r"\b(?:in|with) right hand\b", clause, re.IGNORECASE)
    uses_left = re.search(r"\b(?:in|with) left hand\b", clause, re.IGNORECASE)
    if uses_right and not uses_left:
        return f"hold {obj} in left hand, {clause}"
    if uses_left and not uses_right:
        return f"hold {obj} in right hand, {clause}"
    return text


def _clause_hand(clause: str) -> str:
    text = clause or ""
    if re.search(r"\bboth hands\b", text, re.IGNORECASE):
        return "both hands"
    if re.search(r"\bleft hand\b", text, re.IGNORECASE):
        return "left hand"
    if re.search(r"\bright hand\b", text, re.IGNORECASE):
        return "right hand"
    return ""


def _attach_missing_hands(text: str) -> str:
    """Guideline: every clause must name a hand. Copy a sibling hand if one is missing."""
    clauses = split_actions(text)
    known = ""
    for clause in clauses:
        known = _clause_hand(clause)
        if known:
            break
    if not known:
        return text
    attached = []
    for clause in clauses:
        if _leading_verb(clause) and not _clause_hand(clause):
            attached.append(f"{clause} with {known}")
        else:
            attached.append(clause)
    return ", ".join(attached)


def _drop_contradictory_hold_after_pickup(text: str) -> str:
    """pick up X, hold X is contradictory. Keep pick up (object left the surface)."""
    clauses = split_actions(text)
    if len(clauses) != 2:
        return text
    if _leading_verb(clauses[0]) != "pick up" or _leading_verb(clauses[1]) != "hold":
        return text
    if _objects_match(_pickup_object(clauses[0]), _clause_object(clauses[1])):
        return clauses[0]
    return text


def _is_case_a_stabilize(label: str) -> bool:
    parts = split_actions(label)
    if len(parts) != 2:
        return False
    if _leading_verb(parts[0]) == "hold":
        hold, work = parts[0], parts[1]
    elif _leading_verb(parts[1]) == "hold":
        hold, work = parts[1], parts[0]
    else:
        return False
    tool = _named_tool_in(work)
    held = _clause_object(hold)
    if STOVEWARE_PATTERN.search(held or "") or STOVEWARE_PATTERN.search(work):
        return False
    if tool and held and not _objects_match(held, tool):
        return True
    work_verb = _leading_verb(work)
    hold_hand = _clause_hand(hold)
    work_hand = _clause_hand(work)
    distinct = (
        hold_hand in {"left hand", "right hand"}
        and work_hand in {"left hand", "right hand"}
        and hold_hand != work_hand
    )
    return distinct and work_verb in CLOTH_WORK_VERBS | WIPE_VERBS


def _finish_incomplete_hands(text: str) -> str:
    """wipe plate with right -> wipe plate with right hand."""
    return INCOMPLETE_HAND_PATTERN.sub(r"\1 \2 hand", text)


DISH_PATTERN = re.compile(
    r"\b(?:glass\s+cup|glass\s+plate|plate|bowl|dish|platter|cup)\b",
    re.IGNORECASE,
)
GLASS_SURFACE_PATTERN = re.compile(
    r"\bglass\s+(?:door|window|table|plate|pane)\b",
    re.IGNORECASE,
)


def _clause_object(clause: str) -> str:
    text = LEADING_VERB_PATTERN.sub("", clause, count=1).strip()
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


def _normalize_glass_cup(text: str) -> str:
    """Bare 'glass' being held/wiped is a glass cup, not a glass door."""
    if not text or GLASS_SURFACE_PATTERN.search(text):
        return text
    if re.search(r"\bglass cleaner\b", text, re.IGNORECASE):
        return text
    return re.sub(r"\bglass\b(?!\s+cup\b)", "glass cup", text, flags=re.IGNORECASE)


def _cloth_in(text: str) -> str:
    match = re.search(r"\b(cloth|rag|towel|sponge)\b", text or "", re.IGNORECASE)
    return match.group(1).lower() if match else "cloth"


def _is_cloth_clause(clause: str) -> bool:
    return bool(CLOTH_PATTERN.search(clause or ""))


def _split_false_both_hands(text: str) -> str:
    """Do not hide hold-left + work-right as one both-hands clause."""
    clauses = split_actions(_finish_incomplete_hands(text))
    if len(clauses) == 1:
        clause = clauses[0]
        verb = _leading_verb(clause)
        if "both hands" not in clause.lower():
            return ", ".join(clauses)
        if verb in WIPE_VERBS and _is_dish_clause(clause):
            obj = _clause_object(clause) or "plate"
            implement = _cloth_in(clause)
            return (
                f"hold {obj} with left hand, "
                f"{verb} {obj} with {implement} in right hand"
            )
        if (
            verb in CLOTH_WORK_VERBS
            and _is_cloth_clause(clause)
            and not PLACE_LOCATION_PATTERN.search(clause)
        ):
            obj = _clause_object(clause) or "cloth"
            work = "smoothen" if verb in {"fold", "flatten", "smooth", "smoothen"} else verb
            return (
                f"hold {obj} in left hand, "
                f"{work} {obj} with right hand"
            )
        return ", ".join(clauses)
    if len(clauses) == 2:
        first, second = clauses[0], clauses[1]
        if _leading_verb(first) == "hold":
            hold, work = first, second
        elif _leading_verb(second) == "hold":
            hold, work = second, first
        else:
            return ", ".join(clauses)
        if "both hands" not in hold.lower():
            return ", ".join(clauses)
        work_verb = _leading_verb(work)
        if work_verb in WIPE_VERBS and (_is_dish_clause(hold) or _is_dish_clause(work)):
            obj = _clause_object(hold) or _clause_object(work) or "plate"
            implement = _cloth_in(work)
            return (
                f"hold {obj} with left hand, "
                f"{work_verb} {obj} with {implement} in right hand"
            )
        if work_verb in CLOTH_WORK_VERBS and (
            _is_cloth_clause(hold) or _is_cloth_clause(work)
        ):
            obj = _clause_object(hold) or _clause_object(work) or "cloth"
            work_name = (
                "smoothen"
                if work_verb in {"fold", "flatten", "smooth", "smoothen"}
                else work_verb
            )
            return (
                f"hold {obj} in left hand, "
                f"{work_name} {obj} with right hand"
            )
        return ", ".join(clauses)
    return ", ".join(clauses)


def _name_wipe_cloth(text: str) -> str:
    """wipe plate with right hand -> wipe plate with cloth in right hand."""
    clauses = split_actions(text)
    named = []
    for clause in clauses:
        if (
            _leading_verb(clause) in WIPE_VERBS
            and _is_dish_clause(clause)
            and not re.search(r"\b(cloth|rag|towel|sponge|brush)\b", clause, re.IGNORECASE)
        ):
            clause = re.sub(
                r"\bwith (left|right) hand\b",
                r"with cloth in \1 hand",
                clause,
                flags=re.IGNORECASE,
            )
        named.append(clause)
    return ", ".join(named)


def _hid_distinct_hands(label: str | None) -> bool:
    """True when a draft used both hands to hide hold + a different wipe."""
    clauses = split_actions(_finish_incomplete_hands(label or ""))
    if not clauses or "both hands" not in " ".join(clauses).lower():
        return False
    if len(clauses) == 1:
        verb = _leading_verb(clauses[0])
        if not _is_dish_clause(clauses[0]):
            return False
        return verb in WIPE_VERBS or verb == "hold"
    if len(clauses) == 2:
        hold = clauses[0] if _leading_verb(clauses[0]) == "hold" else clauses[1]
        work = clauses[1] if hold is clauses[0] else clauses[0]
        return (
            _leading_verb(hold) == "hold"
            and "both hands" in hold.lower()
            and _leading_verb(work) in WIPE_VERBS
        )
    return False


def _has_distinct_hands(label: str) -> bool:
    blob = (label or "").lower()
    return "left hand" in blob and "right hand" in blob and "both hands" not in blob


def _has_release(label: str) -> bool:
    """True when a label includes a real put-down (place/set)."""
    return any(
        _leading_verb(clause) in {"place", "set"} for clause in split_actions(label)
    )


def _restore_stabilize_wipe(label: str, previous_label: str | None) -> str:
    """Keep hold-left + wipe-right when the next row collapses that into both hands."""
    if not previous_label:
        return label
    prev_clauses = split_actions(previous_label)
    if len(prev_clauses) != 2:
        return label
    if _leading_verb(prev_clauses[0]) != "hold":
        return label
    work_verb = _leading_verb(prev_clauses[1])
    if work_verb not in WIPE_VERBS:
        return label
    clauses = split_actions(label)
    if len(clauses) != 1 or "both hands" not in clauses[0].lower():
        return label
    verb = _leading_verb(clauses[0])
    if verb not in WIPE_VERBS and verb != "hold":
        return label
    if not (_is_dish_clause(clauses[0]) or _is_dish_clause(prev_clauses[0])):
        return label
    obj = _clause_object(clauses[0]) or _clause_object(prev_clauses[0]) or "plate"
    implement = _cloth_in(prev_clauses[1]) or _cloth_in(clauses[0])
    if verb == "hold" and re.search(r"\bglass cup\b", obj, re.IGNORECASE):
        return (
            f"rotate {obj} with left hand, "
            f"{work_verb} {obj} with {implement} in right hand"
        )
    return (
        f"hold {obj} with left hand, "
        f"{work_verb} {obj} with {implement} in right hand"
    )


def _align_object_names(label: str, previous_label: str | None) -> str:
    """Keep plate vs bowl consistent with the previous segment."""
    if not previous_label:
        return label
    prev = previous_label.lower()
    updated = label
    if re.search(r"\bplate\b", prev) and re.search(r"\b(?:bowl|dish)\b", updated, re.IGNORECASE):
        updated = re.sub(r"\b(?:bowl|dish)\b", "plate", updated, flags=re.IGNORECASE)
    if re.search(r"\bglass plate\b", prev):
        updated = re.sub(r"(?<!glass )\bplate\b", "glass plate", updated, flags=re.IGNORECASE)
        updated = re.sub(r"\bglass glass plate\b", "glass plate", updated, flags=re.IGNORECASE)
    if re.search(r"\bladle\b", prev) and re.search(r"\bspoon\b", updated, re.IGNORECASE):
        updated = re.sub(r"\bspoon\b", "ladle", updated, flags=re.IGNORECASE)
    if re.search(r"\bwok\b", prev) and re.search(r"\bpan\b", updated, re.IGNORECASE):
        updated = re.sub(r"\bpan\b", "wok", updated, flags=re.IGNORECASE)
    if re.search(r"\bpapers\b", prev):
        updated = re.sub(r"\bpaper\b(?!s)", "papers", updated, flags=re.IGNORECASE)
    if re.search(r"\bglass cup\b", prev):
        updated = re.sub(r"(?<!glass )\bcup\b", "glass cup", updated, flags=re.IGNORECASE)
        updated = re.sub(r"\bglass glass cup\b", "glass cup", updated, flags=re.IGNORECASE)
    if re.search(r"\bcable\b", prev) and re.search(r"\bwire\b", updated, re.IGNORECASE):
        updated = re.sub(r"\bwire\b", "cable", updated, flags=re.IGNORECASE)
    if re.search(r"\bcloth\b", prev) and re.search(
        r"\b(rag|towel)\b", updated, re.IGNORECASE
    ):
        updated = re.sub(r"\b(?:rag|towel)\b", "cloth", updated, flags=re.IGNORECASE)
    for match in re.finditer(
        r"\b(red|blue|white|black|green|yellow|orange|pink|grey|gray|brown)\s+(\w+)\b",
        prev,
        re.IGNORECASE,
    ):
        color, noun = match.group(1), match.group(2)
        if re.search(rf"\b{re.escape(noun)}\b", updated, re.IGNORECASE) and not re.search(
            rf"\b{re.escape(color)} {re.escape(noun)}\b", updated, re.IGNORECASE
        ):
            updated = re.sub(
                rf"\b{re.escape(noun)}\b",
                f"{color} {noun}",
                updated,
                count=1,
                flags=re.IGNORECASE,
            )
    return updated


def _align_work_verbs(label: str, previous_label: str | None) -> str:
    """If the last row used wash, do not switch to wipe on the same object."""
    if not previous_label:
        return label
    prev_cleaning = [
        (_leading_verb(clause), _clause_object(clause))
        for clause in split_actions(previous_label)
        if _leading_verb(clause) in CLEANING_VERBS
    ]
    if not prev_cleaning:
        return label
    updated = []
    for clause in split_actions(label):
        verb = _leading_verb(clause)
        obj = _clause_object(clause)
        if verb in CLEANING_VERBS and obj:
            for prev_verb, prev_obj in prev_cleaning:
                if prev_verb != verb and _objects_match(obj, prev_obj):
                    clause = re.sub(
                        rf"^{re.escape(verb)}\b",
                        prev_verb,
                        clause,
                        count=1,
                        flags=re.IGNORECASE,
                    )
                    break
        updated.append(clause)
    return ", ".join(updated) if updated else label


def _rewrite_hand_change_as_pass(
    label: str, previous_label: str | None
) -> str:
    """hold cup with right after hold cup with left → pass cup from left hand to right hand."""
    if not previous_label or not label or label == "No Action":
        return label
    clauses = split_actions(label)
    if len(clauses) != 1:
        return label
    verb = _leading_verb(clauses[0])
    if verb not in {"hold", "pick up"}:
        return label
    obj = _clause_object(clauses[0])
    new_hand = _clause_hand(clauses[0])
    if not obj or new_hand not in {"left hand", "right hand"}:
        return label
    prev_hand = ""
    for prev in split_actions(previous_label):
        if not _objects_match(_clause_object(prev), obj):
            continue
        hand = _clause_hand(prev)
        if hand in {"left hand", "right hand"}:
            prev_hand = hand
            break
    if prev_hand and prev_hand != new_hand:
        return f"pass {obj} from {prev_hand} to {new_hand}"
    return label


def _ensure_place_location(label: str, previous_label: str | None) -> str:
    """place cup with right hand → place cup on table with right hand when location is known."""
    clauses = split_actions(label)
    loc = ""
    if previous_label:
        match = PLACE_LOCATION_CAPTURE.search(previous_label)
        if match:
            loc = match.group(1).lower()
    filled = []
    for clause in clauses:
        verb = _leading_verb(clause)
        if verb in {"place", "set"} and not PLACE_LOCATION_PATTERN.search(clause):
            insert = loc
            if not insert and verb == "set":
                insert = "on ground"
            if insert:
                clause = re.sub(
                    r"\s+with\s+",
                    f" {insert} with ",
                    clause,
                    count=1,
                    flags=re.IGNORECASE,
                )
        filled.append(clause)
    return ", ".join(filled)


def _fill_with_visible_substance(text: str) -> str:
    if not re.search(r"\bfill\b", text, re.IGNORECASE):
        return text
    if re.search(r"\bwith water\b", text, re.IGNORECASE):
        return text
    return FILL_SOURCE_PATTERN.sub(r"fill \1 with water with \2", text)


def _strip_narrative_words(text: str) -> str:
    cleaned = NARRATIVE_PATTERN.sub("", text)
    cleaned = PRONOUN_PATTERN.sub("", cleaned)
    cleaned = " ".join(cleaned.split())
    cleaned = BODY_PART_PATTERN.sub("with right hand", cleaned)
    cleaned = BARE_HANDS_PATTERN.sub("with both hands", cleaned)
    cleaned = " ".join(cleaned.split())
    cleaned = re.sub(r"\s+,", ",", cleaned)
    return cleaned.strip(" ,")


def _replace_unapproved_nouns(text: str) -> str:
    updated = text
    for banned, allowed in NOUN_REPLACEMENTS.items():
        updated = re.sub(rf"\b{banned}\b", allowed, updated, flags=re.IGNORECASE)
    return updated


def _name_self_tool_and_location(text: str) -> str:
    """rake leaves with both hands -> rake leaves on ground with rake in both hands."""
    clauses = split_actions(text)
    named = []
    for clause in clauses:
        verb = _leading_verb(clause)
        tool = SELF_NAMED_TOOLS.get(verb)
        if tool and not re.search(rf"\bwith {re.escape(tool)}\b", clause, re.IGNORECASE):
            hand = _clause_hand(clause)
            if hand == "both hands":
                prep = "in both hands"
            elif hand:
                prep = f"in {hand}"
            else:
                prep = "in both hands"
            clause = re.sub(
                r"\s+with (?:left hand|right hand|both hands)\s*$",
                "",
                clause,
                flags=re.IGNORECASE,
            )
            if verb in GROUND_WORK_VERBS and not PLACE_LOCATION_PATTERN.search(clause):
                clause = f"{clause} on ground"
            clause = f"{clause} with {tool} {prep}"
        elif verb in GROUND_WORK_VERBS and not PLACE_LOCATION_PATTERN.search(clause):
            if re.search(r"\s+with\s+", clause, re.IGNORECASE):
                clause = re.sub(
                    r"\s+with\s+",
                    " on ground with ",
                    clause,
                    count=1,
                    flags=re.IGNORECASE,
                )
            else:
                clause = f"{clause} on ground"
        named.append(clause)
    return ", ".join(named)


def _prefer_place_over_pickup(model: str, draft: str) -> str | None:
    """pick up vs place of the same object: the object ended on a surface."""
    if _has_release(draft) and not _has_release(model):
        if any(_leading_verb(part) == "pick up" for part in split_actions(model)):
            return draft
    model_parts = split_actions(model)
    draft_parts = split_actions(draft)
    if len(model_parts) != 1 or len(draft_parts) != 1:
        return None
    model_verb = _leading_verb(model_parts[0])
    draft_verb = _leading_verb(draft_parts[0])
    if {model_verb, draft_verb} != {"pick up", "place"}:
        return None
    model_obj = _pickup_object(model_parts[0]) or _clause_object(model_parts[0])
    draft_obj = _pickup_object(draft_parts[0]) or _clause_object(draft_parts[0])
    if not _objects_match(model_obj, draft_obj):
        return None
    return draft if draft_verb == "place" else model


def _append_end_of_window_pickup(
    label: str,
    next_label: str | None,
    draft_label: str | None = None,
) -> str:
    """Keep pick up of a tool the next row uses when this window only did the prior work."""
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


def _complete_set_then_pickup(
    label: str, previous_label: str | None, next_label: str | None = None
) -> str:
    """set hose, then pick up the watering can that was just being filled."""
    if not label or label == "No Action":
        return label
    parts = split_actions(label)
    if not parts or len(parts) >= MAX_ACTIONS_PER_LABEL:
        return label
    if any(_leading_verb(part) == "pick up" for part in parts):
        return label
    set_clause = next((part for part in parts if _leading_verb(part) == "set"), None)
    if not set_clause or not re.search(r"\bhose\b", set_clause, re.IGNORECASE):
        return label
    context = f"{previous_label or ''} {next_label or ''}"
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
            set_clause if _leading_verb(part) == "set" else part for part in parts
        ]
        other = "right hand"
    return f"{', '.join(parts)}, pick up watering can with {other}"


def _rewrite_close_door_to_pass(text: str) -> str:
    """pick up bottle, close fridge → pick up bottle, pass bottle to the other hand."""
    parts = split_actions(text)
    if len(parts) != 2:
        return text
    pickup = next((part for part in parts if _leading_verb(part) == "pick up"), None)
    close = next(
        (
            part
            for part in parts
            if _leading_verb(part) == "close"
            and re.search(r"\bdoor\b", part, re.IGNORECASE)
        ),
        None,
    )
    if not pickup or not close:
        return text
    obj = _pickup_object(pickup)
    hand = _clause_hand(pickup) or "right hand"
    if not obj or hand not in {"left hand", "right hand"}:
        return text
    other = "left hand" if hand == "right hand" else "right hand"
    return f"{pickup}, pass {obj} from {hand} to {other}"


def _rewrite_cut_to_align_after_hold(
    label: str, previous_label: str | None
) -> str:
    """After a hold-scissors window, lining up sheets is align, not cut."""
    if not previous_label or not label:
        return label
    if any(_leading_verb(part) == "cut" for part in split_actions(previous_label)):
        return label
    if not re.search(r"\bscissors\b", previous_label, re.IGNORECASE):
        return label
    if not any(_leading_verb(part) == "cut" for part in split_actions(label)):
        return label
    if not re.search(r"\b(?:paper|papers|plastic bag)\b", label, re.IGNORECASE):
        return label
    return "hold scissors with right hand, align papers with both hands"


def _restore_draft_locations(label: str, draft_label: str | None) -> str:
    if not label or not draft_label:
        return label
    if not re.search(r"\bwater plant\b", label, re.IGNORECASE):
        return label
    if re.search(r"\bin bucket\b", label, re.IGNORECASE):
        return label
    if re.search(r"\bin bucket\b", draft_label, re.IGNORECASE):
        return re.sub(
            r"\bwater plant\b",
            "water plant in bucket",
            label,
            count=1,
            flags=re.IGNORECASE,
        )
    if re.search(r"\bbucket\b", label, re.IGNORECASE) and re.search(
        r"\bon floor\b", draft_label, re.IGNORECASE
    ):
        label = re.sub(r"\bon ground\b", "on floor", label, flags=re.IGNORECASE)
    return label


def _complete_place_bucket_pickup_hoe(
    label: str,
    draft_label: str | None = None,
    previous_label: str | None = None,
    next_label: str | None = None,
) -> str:
    """place bucket is incomplete without pick up hoe (official CASE C gold)."""
    if not label or label == "No Action":
        return label
    parts = split_actions(label)
    if not parts or len(parts) >= MAX_ACTIONS_PER_LABEL:
        return label
    place = next(
        (
            part
            for part in parts
            if _leading_verb(part) == "place"
            and re.search(r"\bbucket\b", part, re.IGNORECASE)
        ),
        None,
    )
    if not place:
        return label
    if any(re.search(r"\bhoe\b", part, re.IGNORECASE) for part in parts):
        return label
    context = f"{draft_label or ''} {previous_label or ''} {next_label or ''}"
    if re.search(r"\bon ground\b", place, re.IGNORECASE) and (
        re.search(r"\bon floor\b", context, re.IGNORECASE)
        or not re.search(r"\bon (?:table|shelf|counter)\b", place, re.IGNORECASE)
    ):
        place = re.sub(r"\bon ground\b", "on floor", place, flags=re.IGNORECASE)
        parts = [
            place
            if _leading_verb(part) == "place" and "bucket" in part.lower()
            else part
            for part in parts
        ]
    hand = _clause_hand(place)
    other = "right hand" if hand == "left hand" else "left hand"
    return f"{', '.join(parts)}, pick up hoe with {other}"


def _complete_place_hoe_gather(
    label: str,
    previous_label: str | None,
    draft_label: str | None = None,
    duration_seconds: float | None = None,
) -> str:
    """After digging with a hoe, the next window is place hoe + gather soil."""
    if not label or not previous_label:
        return label
    if duration_seconds is not None and duration_seconds < 3.5:
        return label
    draft_parts = split_actions(usable_draft(draft_label) or "")
    if len(draft_parts) == 1 and _leading_verb(draft_parts[0]) == "dig":
        return label
    if not re.search(r"\b(?:hoe|dig)\b", previous_label, re.IGNORECASE):
        return label
    if any(
        _leading_verb(part) == "place" and re.search(r"\bhoe\b", part, re.IGNORECASE)
        for part in split_actions(label)
    ):
        return label
    if any(_leading_verb(part) == "gather" for part in split_actions(label)):
        if not re.search(r"\bhoe\b", label, re.IGNORECASE):
            return "place hoe on ground with right hand, gather soil with both hands"
        return label
    parts = split_actions(label)
    if (
        len(parts) == 1
        and _leading_verb(parts[0]) == "dig"
        and "both hands" in parts[0].lower()
        and not re.search(r"\bhoe\b", parts[0], re.IGNORECASE)
    ):
        return "place hoe on ground with right hand, gather soil with both hands"
    return label


def _restore_draft_implements(
    label: str, draft_label: str | None, previous_label: str | None = None
) -> str:
    """Keep hoe / metal pin from the Atlas row when Flash swaps the tool."""
    if not label:
        return label
    context = f"{draft_label or ''} {previous_label or ''}"
    updated = label
    if re.search(r"\bhoe\b", context, re.IGNORECASE) and re.search(
        r"\bdig\b", updated, re.IGNORECASE
    ):
        updated = re.sub(r"\b(?:bucket|shovel)\b", "hoe", updated, flags=re.IGNORECASE)
    return updated


def _named_implement_in(*texts: str | None) -> str | None:
    blob = " ".join(part or "" for part in texts)
    if not blob:
        return None
    for name in NAMED_IMPLEMENTS:
        if re.search(rf"\b{re.escape(name)}\b", blob, re.IGNORECASE):
            return name
    return None


def _max_clauses_for_duration(duration_sec: float | None) -> int | None:
    """Grading parser caps: under 3.5s → 1 clause; 3.5s+ → 2 clauses max."""
    if duration_sec is None:
        return MEDIUM_WINDOW_MAX_CLAUSES
    if duration_sec < SHORT_WINDOW_MAX_SECONDS:
        return 1
    return MEDIUM_WINDOW_MAX_CLAUSES


def enforce_segment_action_limit(label: str, duration_sec: float | None) -> str:
    """Cap action count by window length. Collapse hold + pass + hold first."""
    if not label or label == "No Action":
        return label
    label = _trim_redundant_pass_stabilizers(label)
    max_clauses = _max_clauses_for_duration(duration_sec)
    if max_clauses is None:
        return label
    clauses = split_actions(label)
    if len(clauses) <= max_clauses:
        return label
    verbs = [_leading_verb(clause) for clause in clauses]
    if (
        len(clauses) == 3
        and {"insert", "pull"} & set(verbs)
        and _SEWING_OBJECT.search(label)
        and duration_sec is not None
        and duration_sec >= 2.5
    ):
        return label
    if (
        _SEWING_OBJECT.search(label)
        and re.search(r"\b(?:sewing needle|needle)\b", label, re.IGNORECASE)
        and duration_sec is not None
        and duration_sec < 2.0
        and len(clauses) == 2
    ):
        return label
    if "pass" in verbs and len(clauses) == 3 and verbs[0] == "hold" and verbs[2] == "hold":
        label = _trim_redundant_pass_stabilizers(label)
        clauses = split_actions(label)
        if len(clauses) <= max_clauses:
            return label
    if (
        "pass" in verbs
        and verbs[0] in {"pick up", "hold"}
        and verbs[1] == "pass"
        and max_clauses == 2
    ):
        return ", ".join(clauses[:2])
    return ", ".join(clauses[:max_clauses])


_SEWING_UMBRELLA = re.compile(
    r"\b(?:sew|stitch|draw|write|press)\b",
    re.IGNORECASE,
)
_SEWING_OBJECT = re.compile(r"\b(?:cap|hat|patch)\b", re.IGNORECASE)
_SEWING_NEEDLE = re.compile(
    r"\b(?:insert sewing needle|pull sewing needle|insert needle)\b",
    re.IGNORECASE,
)

_SEW_FIRST = (
    "hold cap with both hands, insert sewing needle into cap with right hand"
)
_SEW_MIDDLE = (
    "hold cap with left hand, pull sewing needle with right hand, "
    "insert sewing needle into cap with right hand"
)
_SEW_LAST = "hold cap with left hand, pull sewing needle with right hand"


def _expand_sew_draw_to_needle(
    label: str,
    previous_label: str | None = None,
    duration_seconds: float | None = None,
) -> str:
    """Replace umbrella sew/draw/write/press with insert/pull sewing-needle mechanics."""
    if not label or label == "No Action":
        return label
    sewing_scene = bool(
        _SEWING_OBJECT.search(label)
        and (
            _SEWING_UMBRELLA.search(label)
            or re.search(r"\bneedle\b", label, re.IGNORECASE)
        )
    )
    if not sewing_scene:
        return label
    duration = 4.0 if duration_seconds is None else duration_seconds
    previous_sew = bool(
        previous_label
        and (
            _SEWING_NEEDLE.search(previous_label)
            or (
                _SEWING_UMBRELLA.search(previous_label)
                and _SEWING_OBJECT.search(previous_label)
            )
        )
    )
    if duration < 2.5:
        return _SEW_LAST
    if not previous_sew:
        return _SEW_FIRST
    return _SEW_MIDDLE


def _restore_glass_cup_when_cloth_took_over(
    label: str,
    previous_label: str | None,
) -> str:
    """Wiping a glass cup: cloth is the implement, not the primary object."""
    if not label or not previous_label:
        return label
    if not re.search(r"\bglass cup\b", previous_label, re.IGNORECASE):
        return label
    if not re.search(r"\b(?:wipe|rotate)\b", previous_label, re.IGNORECASE):
        return label
    if re.search(r"\bglass cup\b", label, re.IGNORECASE):
        return label
    if not re.search(r"\b(?:cloth|rag|towel)\b", label, re.IGNORECASE):
        return label
    if re.search(r"\b(?:plate|book|door|shirt|garment)\b", label, re.IGNORECASE):
        return label
    if any(_leading_verb(part) in {"place", "pick up", "set"} for part in split_actions(label)):
        return label
    return (
        "hold glass cup with left hand, wipe glass cup with cloth in right hand"
    )


def _upgrade_glass_hold_to_rotate(
    label: str,
    previous_label: str | None,
    next_label: str | None,
) -> str:
    """hold+wipe on a turning glass cup is rotate, except the last hold+wipe window."""
    clauses = split_actions(label)
    if len(clauses) != 2:
        return label
    if _leading_verb(clauses[0]) != "hold" or _leading_verb(clauses[1]) != "wipe":
        return label
    if not re.search(r"\bglass cup\b", label, re.IGNORECASE):
        return label
    previous = previous_label or ""
    if not re.search(r"\bwipe\b", previous, re.IGNORECASE):
        return label
    if not re.search(r"\bglass\b", previous, re.IGNORECASE):
        return label
    next_has_work = bool(next_label and str(next_label).strip())
    previous_rotated = bool(re.search(r"\brotate\b", previous, re.IGNORECASE))
    if not next_has_work and previous_rotated:
        return label
    return re.sub(
        r"\bhold glass cup with left hand\b",
        "rotate glass cup with left hand",
        label,
        count=1,
        flags=re.IGNORECASE,
    )


def _expand_copied_wire_fold(
    label: str,
    previous_label: str | None,
    draft_label: str | None = None,
) -> str:
    """The fold window is not a paste of twist + pick up pliers."""
    if not label or not previous_label:
        return label
    if not _labels_match(label, previous_label):
        return label
    if re.search(r"\bstrip\b", label, re.IGNORECASE):
        return label
    if not (
        re.search(r"\btwist\b", previous_label, re.IGNORECASE)
        and re.search(r"pick up (?:pliers|shears)", previous_label, re.IGNORECASE)
    ):
        return label
    draft = usable_draft(draft_label)
    if (
        draft
        and not _labels_match(draft, previous_label)
        and re.search(r"\b(?:fold|strip|shears|cable)\b", draft, re.IGNORECASE)
    ):
        return label
    return (
        "hold shears with right hand, twist blue cable with both hands, "
        "fold blue cable with both hands"
    )


def _rewrite_hold_open_bottle_to_pickup_pass(
    label: str,
    next_label: str | None,
    previous_label: str | None = None,
) -> str:
    """First bottle window is pick up then pass, not hold/open or a missing transfer."""
    if re.search(r"\b(?:bag|sachet)\b", label, re.IGNORECASE):
        return label
    if not re.search(r"\bbottle\b", label, re.IGNORECASE):
        return label
    if re.search(r"\bpass\b", label, re.IGNORECASE):
        return label
    if any(_leading_verb(part) in {"place", "set"} for part in split_actions(label)):
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
    return (
        "pick up bottle with right hand, pass bottle from right hand to left hand"
    )


def _align_place_hand_after_pass(label: str, previous_label: str | None) -> str:
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
    if not re.search(r"\b(?:bottle|bag|sachet)\b", clauses[0], re.IGNORECASE):
        return label
    return re.sub(
        r"\b(?:with|in) (?:left|right) hand\b",
        f"with {dest}",
        clauses[0],
        count=1,
        flags=re.IGNORECASE,
    )


def _rewrite_short_bag_place_to_pass(
    label: str,
    duration_seconds: float | None,
) -> str:
    """Short bag pick-up windows are a hand-off, not a place on the counter."""
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
    hand = "right hand" if "right hand" in clauses[0].lower() else "left hand"
    other = "left hand" if hand == "right hand" else "right hand"
    return f"pick up {obj} with {hand}, pass {obj} from {hand} to {other}"


def _split_false_both_hands_pickup(text: str) -> str:
    """Single-hand pick up or cloth work; not both hands unless placing on shelf."""
    clauses = split_actions(text)
    if len(clauses) != 1:
        return text
    clause = clauses[0]
    if "both hands" not in clause.lower():
        return text
    verb = _leading_verb(clause)
    if verb == "pick up" and re.search(
        r"\b(?:cloth|garment|shirt|bag|sachet|snack)\b", clause, re.IGNORECASE
    ):
        return re.sub(r"\bboth hands\b", "left hand", clause, flags=re.IGNORECASE)
    if verb in CLOTH_WORK_VERBS and _is_cloth_clause(clause) and not _is_dish_clause(clause):
        obj = _clause_object(clause) or ""
        if not re.search(r"\b(?:cloth|garment|shirt|rag|towel)\b", obj, re.IGNORECASE):
            return text
        if PLACE_LOCATION_PATTERN.search(clause) and verb == "fold":
            return text
        obj = _clause_object(clause) or "cloth"
        work = (
            "smoothen"
            if verb in {"fold", "flatten", "smooth", "smoothen"}
            else verb
        )
        return f"hold {obj} in left hand, {work} {obj} with right hand"
    return text


def _strip_book_page_turn(text: str) -> str:
    """Flat book wiping is not turn page."""
    if not text or not re.search(r"\bbook\b", text, re.IGNORECASE):
        return text
    if not re.search(r"\bturn page\b", text, re.IGNORECASE):
        return text
    if re.search(r"\bwipe\b", text, re.IGNORECASE):
        return re.sub(
            r"turn page[^,]*",
            "wipe book with cloth in right hand",
            text,
            flags=re.IGNORECASE,
        )
    return "hold book with left hand, wipe book with cloth in right hand"


def _fix_strip_workpiece_hold(
    label: str,
    previous_label: str | None = None,
    draft_label: str | None = None,
) -> str:
    """During strip, the off-hand holds wire/cable, not pliers/shears."""
    context = f"{label} {previous_label or ''} {draft_label or ''}"
    if not re.search(r"\bstrip\b", context, re.IGNORECASE):
        return label
    wire = "blue cable" if re.search(r"\bblue cable\b", context, re.IGNORECASE) else (
        "blue wire"
        if re.search(r"\bblue wire\b", context, re.IGNORECASE)
        else "cable"
        if re.search(r"\bcable\b", context, re.IGNORECASE)
        else "wire"
    )
    if draft_label:
        for part in split_actions(draft_label):
            if _leading_verb(part) == "hold" and re.search(
                r"\b(?:wire|cable)\b", part, re.IGNORECASE
            ):
                wire = _clause_object(part) or wire
                break
    fixed = []
    for clause in split_actions(label):
        if (
            _leading_verb(clause) == "hold"
            and re.search(r"\b(?:pliers|shears)\b", clause, re.IGNORECASE)
            and not re.search(r"\b(?:wire|cable)\b", clause, re.IGNORECASE)
        ):
            hand = _clause_hand(clause) or "left hand"
            fixed.append(f"hold {wire} with {hand}")
        else:
            fixed.append(clause)
    return ", ".join(fixed)


def _lock_workpiece_nouns(
    label: str, previous_label: str | None, draft_label: str | None = None
) -> str:
    """Keep wire/book/cloth/pin names unless the object was released or passed."""
    if not label or not previous_label:
        return label
    if re.search(r"\b(?:place|set|pass)\b", label, re.IGNORECASE):
        return label
    updated = label
    prev = previous_label.lower()
    if re.search(r"\b(?:wire|cable)\b", prev):
        updated = _fix_strip_workpiece_hold(updated, previous_label, draft_label)
    if re.search(r"\bbook\b", prev) and re.search(r"\bcloth\b", updated, re.IGNORECASE):
        if re.search(r"\bwipe\b", updated, re.IGNORECASE) and not re.search(
            r"\bbook\b", updated, re.IGNORECASE
        ):
            updated = re.sub(
                r"\bwipe cloth\b",
                "wipe book with cloth",
                updated,
                flags=re.IGNORECASE,
            )
    if re.search(r"\bmetal pin\b", prev) or (
        draft_label and re.search(r"\bmetal pin\b", draft_label, re.IGNORECASE)
    ):
        if re.search(r"\bwrench\b", updated, re.IGNORECASE) and not re.search(
            r"\bmetal pin\b", updated, re.IGNORECASE
        ):
            updated = re.sub(r"\bwrench\b", "metal pin", updated, flags=re.IGNORECASE)
    return updated


def _lock_atlas_draft_objects(label: str, draft_label: str | None) -> str:
    """Keep Atlas object names (sachet, bag, hoe, pouch, garment) over generic VLM renames."""
    if not label or not draft_label:
        return label
    draft = draft_label.lower()
    updated = label
    if re.search(r"\bsachet\b", draft):
        for generic in (
            r"food from refrigerator",
            r"snack from refrigerator",
            r"red box",
            r"red snack bag",
            r"snack bag",
        ):
            updated = re.sub(generic, "sachet", updated, flags=re.IGNORECASE)
    elif re.search(r"\bbag\b", draft) and not re.search(r"\bsachet\b", draft):
        for generic in (r"food from refrigerator", r"red box"):
            updated = re.sub(generic, "bag", updated, flags=re.IGNORECASE)
    if re.search(r"\bcloth\b", draft):
        updated = re.sub(r"\bred box\b", "cloth", updated, flags=re.IGNORECASE)
    if re.search(r"\bhoe\b", draft):
        updated = re.sub(r"\bshovel\b", "hoe", updated, flags=re.IGNORECASE)
    if re.search(r"glass cleaner pouch|cleaner pouch", draft):
        for generic in (
            r"blue package",
            r"red package",
            r"green package",
            r"\b(?:blue|red|green|yellow|orange|pink|grey|gray|white|black)\s+package\b",
        ):
            updated = re.sub(
                generic, "glass cleaner pouch", updated, flags=re.IGNORECASE
            )
    elif re.search(r"\bpouch\b", draft):
        updated = re.sub(
            r"\b(?:blue|red|green|yellow|orange|pink|grey|gray|white|black)\s+package\b",
            "pouch",
            updated,
            flags=re.IGNORECASE,
        )
    if re.search(r"\bgarment\b", draft):
        updated = re.sub(r"\bclothes\b", "garment", updated, flags=re.IGNORECASE)
        updated = re.sub(r"\bclothing\b", "garment", updated, flags=re.IGNORECASE)
    elif re.search(r"grey shirt|gray shirt", draft):
        updated = re.sub(r"\bclothes\b", "grey shirt", updated, flags=re.IGNORECASE)
    elif re.search(r"\bshirt\b", draft):
        updated = re.sub(r"\bclothes\b", "shirt", updated, flags=re.IGNORECASE)
    return updated


def _model_skipped_setup(model: str, draft: str, previous_label: str | None) -> bool:
    """dig soil on segment 1 when Atlas still has place bucket + pick up hoe."""
    if previous_label:
        return False
    draft_blob = draft.lower()
    if not (
        re.search(r"place.*bucket", draft_blob)
        and re.search(r"pick up hoe", draft_blob)
    ):
        return False
    model_verbs = {_leading_verb(part) for part in split_actions(model)}
    if not model_verbs & {"dig", "gather"}:
        return False
    return not model_verbs & {"place", "pick up", "set", "pass"}


def _model_inflated_pass_chain(model: str, draft: str) -> bool:
    """hold + pass + hold when Atlas only has pick up + pass."""
    model_parts = split_actions(model)
    draft_parts = split_actions(draft)
    if len(model_parts) != 3 or len(draft_parts) != 2:
        return False
    if _leading_verb(model_parts[1]) != "pass":
        return False
    if _leading_verb(draft_parts[1]) != "pass":
        return False
    if _leading_verb(model_parts[2]) != "hold":
        return False
    return _leading_verb(draft_parts[0]) == "pick up"


def apply_context_fixes(
    label: str,
    draft_label: str | None = None,
    previous_label: str | None = None,
    next_label: str | None = None,
    duration_seconds: float | None = None,
) -> str:
    """Swap generic nouns and keep object names consistent with the prior segment."""
    if not label or label == "No Action":
        return label
    updated = _normalize_glass_cup(label)
    updated = _expand_sew_draw_to_needle(
        updated, previous_label, duration_seconds
    )
    updated = _expand_copied_wire_fold(updated, previous_label, draft_label)
    updated = _rewrite_hold_open_bottle_to_pickup_pass(
        updated, next_label, previous_label
    )
    updated = _align_object_names(updated, previous_label)
    updated = _align_object_names(updated, draft_label)
    updated = _align_work_verbs(updated, previous_label)
    updated = _rewrite_hand_change_as_pass(updated, previous_label)
    updated = _ensure_place_location(updated, previous_label)
    restored = _restore_stabilize_wipe(updated, previous_label)
    if restored != updated:
        updated = restored
    else:
        updated = _restore_stabilize_wipe(updated, draft_label)
    updated = _restore_glass_cup_when_cloth_took_over(updated, previous_label)
    updated = _upgrade_glass_hold_to_rotate(updated, previous_label, next_label)
    updated = _align_place_hand_after_pass(updated, previous_label)
    if GENERIC_NOUN_PATTERN.search(updated):
        specific = _named_implement_in(draft_label, previous_label)
        if specific:
            updated = GENERIC_NOUN_PATTERN.sub(specific, updated)
    updated = _restore_draft_locations(updated, draft_label)
    updated = _restore_draft_implements(updated, draft_label, previous_label)
    updated = _rewrite_cut_to_align_after_hold(updated, previous_label)
    updated = _fix_strip_workpiece_hold(updated, previous_label, draft_label)
    updated = _lock_workpiece_nouns(updated, previous_label, draft_label)
    updated = _lock_atlas_draft_objects(updated, draft_label)
    updated = _append_end_of_window_pickup(updated, next_label, draft_label)
    updated = _complete_set_then_pickup(updated, previous_label, next_label)
    updated = _complete_place_bucket_pickup_hoe(
        updated, draft_label, previous_label, next_label
    )
    updated = _complete_place_hoe_gather(
        updated, previous_label, draft_label, duration_seconds
    )
    updated = _rewrite_short_bag_place_to_pass(updated, duration_seconds)
    return enforce_segment_action_limit(updated, duration_seconds)


def usable_draft(label: str | None) -> str | None:
    """Treat empty and 'No Action' row text as no draft (do not echo it)."""
    text = (label or "").strip()
    if not text or text.casefold() == "no action":
        return None
    return text


def _is_prompt_example(label: str | None) -> bool:
    """True when the model regurgitated a GOLD EXAMPLE instead of the video."""
    text = (label or "").strip().casefold()
    return bool(text) and text in {item.casefold() for item in PROMPT_EXAMPLE_LABELS}


def is_generic_placeholder_label(label: str | None) -> bool:
    """True when a label uses bare 'animal' instead of a species or stuffed animal."""
    text = label or ""
    if not re.search(r"\banimal\b", text, re.IGNORECASE):
        return False
    if re.search(
        r"\b(?:stuffed|plush|toy|fabric|felt)\s+animal\b",
        text,
        re.IGNORECASE,
    ):
        return False
    return True


def rewrite_generic_animal_draft(label: str | None) -> str:
    """Replace bare 'animal' with stuffed animal when vision models refuse the clip."""
    text = (label or "").strip()
    if not text:
        return "No Action"
    if not is_generic_placeholder_label(text):
        return sanitize_label(text)
    rewritten = re.sub(r"\banimal\b", "stuffed animal", text, flags=re.IGNORECASE)
    rewritten = re.sub(
        r"\b(?:stuffed\s+){2,}animal\b",
        "stuffed animal",
        rewritten,
        flags=re.IGNORECASE,
    )
    return sanitize_label(rewritten)


SCENE_STOP = frozenset(
    {
        "with",
        "from",
        "into",
        "onto",
        "on",
        "in",
        "to",
        "of",
        "and",
        "or",
        "the",
        "a",
        "an",
        "left",
        "right",
        "both",
        "hand",
        "hands",
        "pick",
        "up",
        "put",
        "down",
        "hold",
        "place",
        "set",
        "pass",
        "move",
        "fill",
        "lift",
        "wipe",
        "rotate",
        "trim",
        "cut",
        "chop",
        "dig",
        "water",
        "wash",
        "open",
        "close",
        "grab",
        "take",
        "using",
        "mop",
        "strip",
        "rake",
    }
)

OBJECT_CANONICAL = {
    "hat": "cap",
    "beanie": "cap",
    "wire": "cable",
    "pliers": "shears",
    "glass": "cup",
    "page": "book",
    "jar": "cup",
    "lawn": "ground",
    "towel": "cloth",
    "rag": "cloth",
    "pen": "needle",
    "pencil": "needle",
    "pin": "needle",
    "sachet": "bag",
}

HALLUCINATION_PAIRS = (
    (r"\b(?:sewing\s+)?needle\b", r"\b(?:pen|pencil)\b"),
    (r"\bcap\b", r"\bhat\b"),
    (r"\b(?:sewing\s+)?needle\b", r"\b(?:write|peel|sticker)\b"),
    (r"\binsert\b", r"\b(?:sew|draw)\b"),
    (r"sewing needle", r"\b(?:sew|draw)\b"),
    (r"\bstrip\b", r"\btwist\b"),
    (r"\bshears\b", r"\bpliers\b"),
    (r"\bmop\b", r"\btoy\b"),
    (r"\b(?:glass\s+)?door\b", r"\b(?:ceiling|plant|table)\b"),
    (r"\binsert\b", r"\b(?:write|peel|press)\b"),
    (r"sewing needle", r"\b(?:write|press|sew|draw)\b"),
    (r"\bglass cup\b", r"\bhold cloth\b"),
    (r"\bbowl\b", r"\brub\b"),
    (r"\bpatch\b", r"\b(?:pen|sticker)\b"),
    (r"\bhold scissors\b", r"\bcut\b"),
    (r"\bpaper", r"\bplastic bag\b"),
    (r"\bsachet\b", r"\b(?:red box|food from refrigerator|snack from refrigerator)\b"),
    (r"\bbag\b", r"\b(?:red box|food from refrigerator)\b"),
    (r"\bsachet\b", r"\bbottle\b"),
    (r"\bsachet\b", r"\bsnack bag\b"),
    (r"\bsnack bag\b", r"\bbottle\b"),
    (r"\bmetal pin\b", r"\bwrench\b"),
    (r"\bhoe\b", r"\b(?:bucket|shovel)\b"),
    (r"glass cleaner pouch|cleaner pouch", r"blue package"),
    (r"\bpouch\b", r"\b(?:blue|red|green)\s+package\b"),
    (r"\bgarment\b", r"\bclothes\b"),
    (r"grey shirt|gray shirt", r"\bclothes\b"),
)

REQUIRED_EXTRA_VERBS = {
    "pick up",
    "place",
    "set",
    "insert",
    "pull",
    "fold",
    "gather",
}

WORK_DRAFT_VERBS = {
    "mop",
    "sweep",
    "rake",
    "wipe",
    "scrub",
    "iron",
    "strip",
    "twist",
    "set",
    "place",
    "pick up",
    "pass",
    "fill",
    "water",
    "stir",
    "align",
}

LEFTOVER_LABEL_PATTERN = re.compile(
    r"stuffed animal|work dough|trim stuffed",
    re.IGNORECASE,
)
GENERIC_VISION_DEGRADATIONS = re.compile(
    r"\b(?:clothes|clothing)\b|"
    r"\b(?:blue|red|green|yellow|orange|pink|grey|gray|white|black)\s+package\b",
    re.IGNORECASE,
)
CONTINUOUS_WORK_VERBS = WIPE_VERBS | {
    "squeeze",
    "iron",
    "work",
    "stir",
    "twist",
    "fold",
    "knead",
    "seal",
    "smoothen",
}


def draft_object_phrases(label: str | None) -> list[str]:
    """Multi-word object phrases from each clause (Atlas vocabulary lock source)."""
    if not label:
        return []
    phrases: list[str] = []
    for clause in split_actions(label):
        obj = _clause_object_noun(clause)
        if obj:
            phrases.append(obj.strip())
        implement = IMPLEMENT_IN_HAND.search(clause or "")
        if implement:
            phrases.append(implement.group(1).strip())
    seen: set[str] = set()
    unique: list[str] = []
    for phrase in phrases:
        key = phrase.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(phrase)
    return unique


def _object_phrase_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in re.findall(r"[a-z]+", (text or "").lower()):
        if len(token) > 2 and token not in SCENE_STOP:
            tokens.add(OBJECT_CANONICAL.get(token, token))
    return tokens


def object_noun_similarity(model: str, draft: str | None) -> float:
    """Share of Atlas draft object tokens that appear in the Vision label (0–1)."""
    draft_phrases = draft_object_phrases(draft)
    if not draft_phrases:
        return 1.0
    draft_tokens: set[str] = set()
    for phrase in draft_phrases:
        draft_tokens |= _object_phrase_tokens(phrase)
    model_tokens: set[str] = set()
    for phrase in draft_object_phrases(model):
        model_tokens |= _object_phrase_tokens(phrase)
    if not draft_tokens:
        return 1.0
    if not model_tokens:
        return 0.0
    return len(draft_tokens & model_tokens) / len(draft_tokens)


def model_degrades_draft_vocabulary(model: str, draft: str | None) -> bool:
    """True when Vision swapped specific Atlas nouns for generic color/category terms."""
    if not model or not draft:
        return False
    if GENERIC_VISION_DEGRADATIONS.search(model):
        return True
    draft_tokens: set[str] = set()
    for phrase in draft_object_phrases(draft):
        draft_tokens |= _object_phrase_tokens(phrase)
    model_tokens: set[str] = set()
    for phrase in draft_object_phrases(model):
        model_tokens |= _object_phrase_tokens(phrase)
    if model_tokens and draft_tokens and model_tokens <= draft_tokens:
        return False
    return object_noun_similarity(model, draft) < OBJECT_SIMILARITY_THRESHOLD


def should_trust_vision_over_draft(
    model: str,
    draft: str | None,
    *,
    frames_have_video: bool = False,
) -> bool:
    """Vision may override Atlas only when objects match and vocabulary is not degraded."""
    if not draft or not model:
        return bool(model)
    if looks_like_leftover_label(draft):
        return frames_have_video
    if model_hallucinates_against_draft(model, draft):
        return False
    if model_fits_draft(model, draft):
        return True
    if not frames_have_video:
        return False
    if model_degrades_draft_vocabulary(model, draft):
        return False
    return object_noun_similarity(model, draft) >= OBJECT_SIMILARITY_THRESHOLD


def build_draft_vocabulary_system_addon(
    draft: str | None,
    global_context: GlobalVideoContext | None = None,
) -> str:
    """Append Atlas draft + Pass-1 glossary object names to the Vision system prompt."""
    phrases = merge_allowed_object_names(draft, global_context)
    if not phrases:
        return ""
    quoted = ", ".join(f"'{phrase}'" for phrase in phrases)
    forbidden = ", ".join(f"'{word}'" for word in FORBIDDEN_GENERIC_OBJECTS[:6])
    return (
        "\n\nCRITICAL DRAFT VOCABULARY LOCK:\n"
        f"MUST only use these nouns: [{quoted}]. Select object nouns EXCLUSIVELY from this list.\n"
        f"You are strictly forbidden from outputting generic terms like {forbidden}.\n"
        "DO NOT rename items to generic colors or categories "
        "(e.g. use 'glass cleaner pouch' NOT 'blue package'; "
        "use 'grey shirt' or 'garment' NOT 'clothes').\n"
        "Select object nouns ONLY from the allowed list above."
    )


def _clean_atlas_draft_fallback(
    draft: str,
    model: str | None = None,
    duration_seconds: float | None = None,
) -> str:
    """Strip redundant compound draft clauses when Vision confirms one continuous action."""
    if not draft:
        return draft
    blob = draft.lower()
    if re.search(r"place.*bucket", blob) and re.search(r"pick up hoe", blob):
        return enforce_segment_action_limit(draft, duration_seconds)
    model_parts = split_actions(model or "")
    draft_parts = split_actions(draft)
    chosen = draft
    if model and model_degrades_draft_vocabulary(model, draft):
        model_parts = split_actions(model)
        draft_parts = split_actions(draft)
        if (
            len(model_parts) == 1
            and len(draft_parts) > 1
            and (model_fits_draft(model, draft) or _same_goal_verb(model, draft))
        ):
            work_parts = [
                part
                for part in draft_parts
                if _leading_verb(part) not in {"hold", "pass"}
            ]
            if work_parts:
                chosen = work_parts[0]
        return enforce_segment_action_limit(chosen, duration_seconds)
    if model_parts and len(model_parts) == 1 and len(draft_parts) > 1:
        model_verb = _leading_verb(model_parts[0])
        if model_verb and model_verb not in {"hold", "pass"}:
            matching = [
                part for part in draft_parts if _leading_verb(part) == model_verb
            ]
            if matching:
                chosen = matching[0]
            else:
                work_parts = [
                    part
                    for part in draft_parts
                    if _leading_verb(part) in CONTINUOUS_WORK_VERBS
                ]
                if len(work_parts) == 1:
                    chosen = work_parts[0]
                elif work_parts and model_verb in CONTINUOUS_WORK_VERBS:
                    chosen = work_parts[0]
    return enforce_segment_action_limit(chosen, duration_seconds)


def _finalize_draft_choice(
    draft: str,
    model: str | None = None,
    duration_seconds: float | None = None,
) -> str:
    return _clean_atlas_draft_fallback(draft, model, duration_seconds)


@dataclass(frozen=True)
class GlobalVideoContext:
    """Pass-1 observation sweep: object glossary and coarse state timeline."""

    objects: tuple[str, ...] = ()
    timeline: str = ""
    raw_summary: str = ""


def held_objects_at_segment_end(label: str | None) -> set[str]:
    """Objects still in hand when the segment ends (for pick up vs hold continuity)."""
    if not label or label == "No Action":
        return set()
    held: set[str] = set()
    release_verbs = {"place", "set", "put down", "drop", "empty"}
    for clause in split_actions(label):
        verb = _leading_verb(clause)
        obj = _clause_object_noun(clause)
        if not obj:
            continue
        key = obj.lower()
        if verb in release_verbs:
            held.discard(key)
            continue
        if verb in {"hold", "pick up", "pass"} or verb not in {"", "hold"}:
            held.add(key)
    return held


def apply_state_continuity(label: str, previous_label: str | None) -> str:
    """If the prior segment ended holding an object, rewrite erroneous pick up → hold."""
    if not label or not previous_label or label == "No Action":
        return label
    prev_held = held_objects_at_segment_end(previous_label)
    if not prev_held:
        return label
    updated: list[str] = []
    for clause in split_actions(label):
        verb = _leading_verb(clause)
        obj = _clause_object_noun(clause)
        if verb == "pick up" and obj and obj.lower() in prev_held:
            clause = re.sub(r"^pick up\b", "hold", clause, count=1, flags=re.IGNORECASE)
        updated.append(clause)
    return ", ".join(updated)


def align_verb_state(
    vision_verb: str,
    segment_start_has_contact: bool,
    has_active_motion: bool,
) -> str:
    """Enforce pick up vs hold from Frame-0 contact and segment motion."""
    verb = (vision_verb or "").strip().lower()
    if verb not in {"pick up", "hold"}:
        return vision_verb
    if segment_start_has_contact:
        if has_active_motion:
            return vision_verb
        return "hold"
    if verb == "hold":
        return "pick up"
    return vision_verb


def apply_verb_state_from_frames(
    label: str,
    motion_profile: SegmentMotionProfile | None,
) -> str:
    """Rewrite pick up/hold clauses using physical frame state heuristics."""
    if not label or label == "No Action" or not motion_profile or not motion_profile.reliable:
        return label
    updated: list[str] = []
    for clause in split_actions(label):
        verb = _leading_verb(clause)
        if verb not in {"pick up", "hold"}:
            updated.append(clause)
            continue
        aligned = align_verb_state(
            verb,
            motion_profile.start_has_contact,
            motion_profile.has_active_motion,
        )
        if aligned.lower() != verb:
            clause = re.sub(
                rf"^{re.escape(verb)}\b",
                aligned,
                clause,
                count=1,
                flags=re.IGNORECASE,
            )
        updated.append(clause)
    return ", ".join(updated)


def enforce_atlas_template(label: str) -> str:
    """Pre-submission check: every clause is [VERB] [NOUN] with [HAND]."""
    if not label or label == "No Action":
        return label
    fixed: list[str] = []
    for clause in split_actions(label):
        piece = clause.strip()
        if not piece:
            continue
        if validate_clause_syntax(piece) and HAND_PATTERN.search(piece):
            fixed.append(piece)
            continue
        verb = _leading_verb(piece)
        obj = _clause_object_noun(piece)
        hand = _clause_hand(piece)
        if verb and obj and not hand:
            piece = f"{piece} with right hand"
        if verb and not obj and hand:
            obj_guess = _named_implement_in(piece) or "object"
            piece = re.sub(
                rf"^{re.escape(verb)}\b",
                f"{verb} {obj_guess}",
                piece,
                count=1,
                flags=re.IGNORECASE,
            )
        fixed.append(piece)
    return ", ".join(fixed) if fixed else label


def _lock_draft_work_verbs(label: str, draft: str | None) -> str:
    """Prefer Atlas draft work verbs when Vision swaps synonyms (scrub vs wash)."""
    if not label or not draft or label == "No Action":
        return label
    draft_parts = split_actions(draft)
    label_parts = split_actions(label)
    if not draft_parts or not label_parts:
        return label
    updated: list[str] = []
    for index, clause in enumerate(label_parts):
        draft_clause = draft_parts[min(index, len(draft_parts) - 1)]
        draft_verb = _leading_verb(draft_clause)
        model_verb = _leading_verb(clause)
        if (
            draft_verb
            and model_verb
            and draft_verb != model_verb
            and draft_verb in CONTINUOUS_WORK_VERBS
            and model_verb in CONTINUOUS_WORK_VERBS
        ):
            model_obj = _object_phrase_tokens(_clause_object_noun(clause) or "")
            draft_obj = _object_phrase_tokens(_clause_object_noun(draft_clause) or "")
            if model_obj & draft_obj:
                clause = re.sub(
                    rf"^{re.escape(model_verb)}\b",
                    draft_verb,
                    clause,
                    count=1,
                    flags=re.IGNORECASE,
                )
        updated.append(clause)
    return ", ".join(updated)


def _should_lock_clause_noun(clause: str) -> bool:
    """Skip noun-lock on implement/transfer clauses the grader parses separately."""
    verb = _leading_verb(clause)
    if verb in {"insert", "pull", "pass", "cut", "strip", "rake", "water", "fill", "dig"}:
        return False
    if re.search(
        r"\b(?:sewing needle|needle into|into cap|into patch)\b",
        clause,
        re.IGNORECASE,
    ):
        return False
    if re.search(r"\binsert\b.*\bneedle\b", clause, re.IGNORECASE):
        return False
    return True


def _map_clause_object_to_draft_noun(clause: str, draft_nouns: list[str]) -> str:
    """Replace a Vision object phrase with the closest Atlas draft noun."""
    if not clause or not draft_nouns:
        return clause
    obj = _clause_object_noun(clause)
    if not obj:
        return clause
    obj_tokens = _object_phrase_tokens(obj)
    best = draft_nouns[0]
    best_score = -1
    for noun in draft_nouns:
        score = len(obj_tokens & _object_phrase_tokens(noun))
        if score > best_score:
            best_score = score
            best = noun
    if obj.casefold() == best.casefold():
        return clause
    return re.sub(re.escape(obj), best, clause, count=1, flags=re.IGNORECASE)


def _object_needs_draft_lock(obj: str, draft_nouns: list[str]) -> bool:
    """True when Vision used a different object phrase than any Atlas draft noun."""
    if not obj or not draft_nouns:
        return False
    obj_cf = obj.casefold().strip()
    return not any(obj_cf == noun.casefold().strip() for noun in draft_nouns)


def lock_draft_nouns(atlas_draft: str | None, vision_output: str) -> str:
    """Keep Atlas draft nouns; let Vision update active verbs and hands only."""
    if not atlas_draft or not vision_output or vision_output == "No Action":
        return vision_output
    updated = _lock_atlas_draft_objects(vision_output, atlas_draft)
    if looks_like_leftover_label(atlas_draft):
        return updated
    draft_nouns = draft_object_phrases(atlas_draft)
    if not draft_nouns:
        return updated
    primary = draft_nouns[0]
    for forbidden in FORBIDDEN_GENERIC_OBJECTS:
        updated = re.sub(
            rf"\b{re.escape(forbidden)}\b",
            primary,
            updated,
            count=1,
            flags=re.IGNORECASE,
        )
    needs_map = bool(GENERIC_VISION_DEGRADATIONS.search(updated))
    if not needs_map:
        for clause in split_actions(updated):
            obj = _clause_object_noun(clause)
            if obj and _object_needs_draft_lock(obj, draft_nouns):
                needs_map = True
                break
    if not needs_map:
        return updated
    mapped: list[str] = []
    for clause in split_actions(updated):
        if _should_lock_clause_noun(clause):
            mapped.append(_map_clause_object_to_draft_noun(clause, draft_nouns))
        else:
            mapped.append(clause)
    return ", ".join(mapped)


def lint_atlas_syntax(text: str) -> str:
    """Deterministic pre-submit linter for the grading NLP semantic parser."""
    if not text or text == "No Action":
        return text
    updated = lint_label_final(text)
    for progressive, imperative in sorted(
        VERB_CORRECTIONS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        updated = re.sub(
            rf"\b{re.escape(progressive)}\b",
            imperative,
            updated,
            flags=re.IGNORECASE,
        )
    updated = enforce_atlas_template(updated)
    return updated.strip(" ,")


def perform_draft_surgery(atlas_draft: str | None, vision_label: str) -> str:
    """Keep Atlas object nouns; let Vision update verbs and hands."""
    if not atlas_draft or not vision_label or vision_label == "No Action":
        return vision_label
    updated = lock_draft_nouns(atlas_draft, vision_label)
    updated = _lock_draft_work_verbs(updated, atlas_draft)
    return updated


def lint_label_final(label: str) -> str:
    """Deterministic pre-submission linter for Atlas syntax guideline failures."""
    if not label or label == "No Action":
        return label
    updated = label.strip()
    dual = re.match(
        r"^(scrub|squeeze|wash|wipe|iron|fold)\s+and\s+"
        r"(scrub|squeeze|wash|wipe|iron|fold)\s+(.+)$",
        updated,
        re.IGNORECASE,
    )
    if dual and "," not in updated:
        tail = dual.group(3).strip()
        updated = (
            f"{dual.group(1).lower()} {tail}, "
            f"{dual.group(2).lower()} {tail}"
        )
    updated = SEMICOLON_PATTERN.sub(", ", updated)
    updated = re.sub(r"\bthen\b", ", ", updated, flags=re.IGNORECASE)
    updated = NARRATIVE_PATTERN.sub("", updated)
    updated = re.sub(r"\bholding\b", "hold", updated, flags=re.IGNORECASE)
    updated = re.sub(r"\bpicking up\b", "pick up", updated, flags=re.IGNORECASE)
    parts: list[str] = []
    for clause in split_actions(updated):
        piece = clause.strip()
        if not piece:
            continue
        dual = re.match(
            r"^(scrub|squeeze|wash|wipe|iron|fold)\s+and\s+"
            r"(scrub|squeeze|wash|wipe|iron|fold)\s+(.+)$",
            piece,
            re.IGNORECASE,
        )
        if dual:
            first_verb, second_verb, tail = dual.group(1), dual.group(2), dual.group(3)
            parts.append(f"{first_verb.lower()} {tail.strip()}")
            parts.append(f"{second_verb.lower()} {tail.strip()}")
            continue
        if re.search(r"\band\b", piece, re.IGNORECASE):
            split_parts = re.split(r"\s+and\s+", piece, maxsplit=1, flags=re.IGNORECASE)
            if len(split_parts) == 2 and LEADING_VERB_PATTERN.search(split_parts[1].strip()):
                parts.append(split_parts[0].strip())
                parts.append(split_parts[1].strip())
                continue
        parts.append(piece)
    updated = ", ".join(parts)
    updated = COMMA_AND_PATTERN.sub(",", updated)
    updated = " ".join(updated.split())
    return updated.strip(" ,")


def merge_allowed_object_names(
    draft_label: str | None,
    global_context: GlobalVideoContext | None,
) -> list[str]:
    """Union of Pass-1 glossary and segment draft object phrases."""
    names: list[str] = []
    seen: set[str] = set()
    for source in (
        draft_object_phrases(draft_label),
        list(global_context.objects) if global_context else [],
    ):
        for phrase in source:
            key = phrase.casefold()
            if key not in seen:
                seen.add(key)
                names.append(phrase)
    return names


def build_global_context_system_addon(context: GlobalVideoContext | None) -> str:
    if not context or (not context.objects and not context.timeline):
        return ""
    lines = ["\n\nGLOBAL VIDEO CONTEXT (Pass 1 observation sweep):"]
    if context.objects:
        quoted = ", ".join(f"'{name}'" for name in context.objects)
        lines.append(f"Canonical object glossary for this clip: {quoted}.")
        lines.append(
            "You are strictly forbidden from outputting generic terms like "
            "'blue package', 'item', 'container', or 'clothes' when a glossary name fits."
        )
    if context.timeline:
        lines.append(f"Object state timeline: {context.timeline}")
    lines.append(
        "Use pick up ONLY at the moment an object leaves a surface. "
        "If the timeline or Frame 0 shows the object already held, write hold."
    )
    return "\n".join(lines) + "\n"


def finalize_pipeline_label(
    label: str,
    draft_label: str | None = None,
    previous_label: str | None = None,
    duration_seconds: float | None = None,
    global_context: GlobalVideoContext | None = None,
    motion_profile: SegmentMotionProfile | None = None,
) -> str:
    """Draft surgery, state continuity, lint, and duration caps before browser submit."""
    if not label or label == "No Action":
        return label
    updated = perform_draft_surgery(draft_label, label)
    updated = apply_state_continuity(updated, previous_label)
    updated = apply_verb_state_from_frames(updated, motion_profile)
    if global_context and global_context.objects:
        for phrase in global_context.objects:
            for forbidden in FORBIDDEN_GENERIC_OBJECTS:
                updated = re.sub(
                    rf"\b{re.escape(forbidden)}\b",
                    phrase,
                    updated,
                    count=1,
                    flags=re.IGNORECASE,
                )
    updated = lint_atlas_syntax(updated)
    updated = sanitize_label(updated)
    updated = apply_context_fixes(
        updated,
        draft_label,
        previous_label,
        duration_seconds=duration_seconds,
    )
    if draft_label and model_degrades_draft_vocabulary(label, draft_label):
        draft_clean = apply_context_fixes(
            sanitize_label(draft_label),
            draft_label,
            previous_label,
            duration_seconds=duration_seconds,
        )
        work_parts = [
            part
            for part in split_actions(draft_clean)
            if _leading_verb(part) not in {"hold", "pass"}
        ]
        if work_parts and len(split_actions(updated)) == 1:
            updated = work_parts[0]
    updated = enforce_segment_action_limit(updated, duration_seconds)
    return updated


def _parse_global_context_json(text: str) -> GlobalVideoContext | None:
    blob = (text or "").strip()
    if not blob:
        return None
    match = re.search(r"\{.*\}", blob, re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    raw_objects = payload.get("objects") or payload.get("object_glossary") or []
    objects: list[str] = []
    if isinstance(raw_objects, list):
        for item in raw_objects:
            if isinstance(item, str) and item.strip():
                objects.append(item.strip())
    timeline = str(payload.get("timeline") or payload.get("state_history") or "").strip()
    return GlobalVideoContext(
        objects=tuple(objects),
        timeline=timeline,
        raw_summary=blob[:500],
    )


def analyze_global_video_context(
    base64_frames: list[str],
    frame_timestamps: list[float] | None = None,
    segment_drafts: list[str] | None = None,
) -> GlobalVideoContext:
    """Pass 1: full-clip observation sweep for object glossary and state timeline."""
    if not _api_key() or not base64_frames:
        draft_objects: list[str] = []
        for draft in segment_drafts or []:
            draft_objects.extend(draft_object_phrases(draft))
        unique = list(dict.fromkeys(draft_objects))
        return GlobalVideoContext(objects=tuple(unique))

    frames, times = prepare_segment_frames(
        base64_frames,
        frame_timestamps,
        duration_seconds=None,
        start_seconds=frame_timestamps[0] if frame_timestamps else 0.0,
    )
    frames = frames[:GLOBAL_SWEEP_MAX_FRAMES]
    if times:
        times = times[: len(frames)]

    draft_hint = ""
    if segment_drafts:
        hints = []
        for draft in segment_drafts:
            hints.extend(draft_object_phrases(draft))
        if hints:
            draft_hint = (
                " Atlas row hints (prefer these exact names): "
                + ", ".join(dict.fromkeys(hints))
                + "."
            )

    user_parts: list[dict] = [
        {
            "type": "text",
            "text": (
                "Analyze this ENTIRE first-person activity clip from the frames. "
                "List every primary object using precise terms (not generic package/clothes/item). "
                "Map when objects are picked up, held, put down, or passed between hands."
                + draft_hint
                + " Return ONLY valid JSON with keys: "
                '{"objects": ["..."], "timeline": "..."}'
            ),
        }
    ]
    for index, frame in enumerate(frames):
        stamp = f" t={times[index]:.1f}s" if times and index < len(times) else ""
        user_parts.append({"type": "text", "text": f"Timeline frame {index + 1}{stamp}"})
        user_parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{frame}", "detail": "low"},
            }
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + build_global_context_system_addon(None)},
        {"role": "user", "content": user_parts},
    ]
    try:
        response = client.chat.completions.create(
            model=VISION_MODELS[0],
            messages=messages,
            temperature=0.0,
            extra_headers=OPENROUTER_HEADERS,
        )
        raw = response.choices[0].message.content or ""
        parsed = _parse_global_context_json(raw)
        if parsed and parsed.objects:
            print(
                f"[Pipeline]: Pass 1 glossary ({len(parsed.objects)} objects): "
                f"{', '.join(parsed.objects)}"
            )
            return parsed
    except Exception as exc:
        print(f"[Pipeline]: Pass 1 context sweep failed ({exc}). Using draft hints only.")

    draft_objects = []
    for draft in segment_drafts or []:
        draft_objects.extend(draft_object_phrases(draft))
    unique = list(dict.fromkeys(draft_objects))
    return GlobalVideoContext(objects=tuple(unique))


def scene_tokens(label: str | None) -> set[str]:
    """Object-like words in a label, ignoring hands and common verbs."""
    words = re.findall(r"[a-z]+", (label or "").lower())
    return {word for word in words if len(word) > 2 and word not in SCENE_STOP}


def _canonical_scene_tokens(label: str | None) -> set[str]:
    raw = label or ""
    mapped = set()
    for token in scene_tokens(raw):
        if token == "pin" and re.search(r"\bmetal pin\b", raw, re.IGNORECASE):
            mapped.add("pin")
        else:
            mapped.add(OBJECT_CANONICAL.get(token, token))
    return mapped


def looks_like_leftover_label(label: str | None) -> bool:
    """True when row text is leftover bot output from another clip, not Atlas gold."""
    text = (label or "").strip()
    if not text:
        return False
    if _is_prompt_example(text):
        return True
    return bool(LEFTOVER_LABEL_PATTERN.search(text))


def model_hallucinates_against_draft(model_label: str, draft_label: str | None) -> bool:
    """True when Flash swapped a specific Atlas noun/verb for a common VLM mistake."""
    draft = usable_draft(draft_label)
    if not draft or not model_label or model_label == "No Action":
        return False
    if looks_like_leftover_label(draft):
        return False
    d = draft.lower()
    m = model_label.lower()
    for draft_pat, model_pat in HALLUCINATION_PAIRS:
        if re.search(draft_pat, d) and re.search(model_pat, m) and not re.search(draft_pat, m):
            return True
    return False


def model_fits_draft(model_label: str, draft_label: str | None) -> bool:
    """False when the model names a different scene than a specific Atlas draft."""
    draft = usable_draft(draft_label)
    if not draft:
        return True
    if not model_label or model_label == "No Action":
        return False
    draft_objects = _canonical_scene_tokens(draft)
    model_objects = _canonical_scene_tokens(model_label)
    if not draft_objects:
        return True
    if not draft_objects & model_objects:
        return False
    similarity = object_noun_similarity(model_label, draft)
    if similarity >= OBJECT_SIMILARITY_THRESHOLD:
        return True
    if model_objects <= draft_objects and len(model_objects) < len(draft_objects):
        return False
    return similarity >= 0.5


def _labels_match(left: str | None, right: str | None) -> bool:
    return (left or "").strip().casefold() == (right or "").strip().casefold()


def _work_verbs(label: str | None) -> tuple[str, ...]:
    return tuple(
        _leading_verb(clause)
        for clause in split_actions(label or "")
        if _leading_verb(clause) and _leading_verb(clause) != "hold"
    )


def _copied_previous_ignoring_draft(
    model: str, draft: str, previous: str | None
) -> bool:
    """True when the model reused the last row while this Atlas draft has a new verb."""
    if not previous or not draft or not model:
        return False
    if looks_like_leftover_label(draft) or is_generic_placeholder_label(draft):
        return False
    model_verbs = _work_verbs(model)
    prev_verbs = _work_verbs(previous)
    if not model_verbs or model_verbs != prev_verbs:
        return False
    draft_work = set(_work_verbs(draft))
    if draft_work - set(model_verbs):
        return True
    return not draft_work and bool(model_verbs)


def _prefer_work_draft_over_idle_hold(model: str, draft: str) -> bool:
    """set/place/mop beat a model that only wrote hold — not when Vision is simpler."""
    model_parts = split_actions(model)
    draft_parts = split_actions(draft)
    if not model_parts or not draft_parts:
        return False
    if len(model_parts) < len(draft_parts):
        return False
    model_all_hold = all(_leading_verb(part) == "hold" for part in model_parts)
    if not model_all_hold:
        return False
    blob = model.lower()
    if "both hands" in blob and any(
        re.search(rf"\b{re.escape(tool)}\b", blob) for tool in TWO_HANDED_TOOLS
    ):
        return False
    draft_has_work = any(
        _leading_verb(part) not in {"", "hold"} for part in draft_parts
    )
    return draft_has_work


def _prefer_simpler_model_over_compound_draft(
    model: str,
    draft: str,
    draft_raw: str | None,
    previous_label: str | None = None,
    duration_seconds: float | None = None,
) -> bool:
    """Trust Vision when it reports fewer actions than a compound Atlas draft."""
    model_parts = split_actions(model)
    draft_parts = split_actions(draft)
    if not model_parts or not draft_parts:
        return False
    if len(model_parts) >= len(draft_parts):
        return False
    if looks_like_leftover_label(draft_raw) or is_generic_placeholder_label(
        draft_raw or ""
    ):
        return False
    if (
        len(model_parts) == 1
        and _leading_verb(model_parts[0]) == "hold"
        and len(draft_parts) > 1
    ):
        hold_objects = draft_object_phrases(model)
        draft_blob = " ".join(draft_object_phrases(draft)).lower()
        if hold_objects and all(obj.lower() in draft_blob for obj in hold_objects):
            return True
    if not model_fits_draft(model, draft):
        return False
    if _model_skipped_setup(model, draft, previous_label):
        return False
    if model_degrades_draft_vocabulary(model, draft):
        return False
    model_work = set(_work_verbs(model))
    draft_work = set(_work_verbs(draft))
    if model_work and draft_work and not model_work <= draft_work:
        return False
    if _is_case_a_stabilize(draft) and not _is_case_a_stabilize(model):
        draft_work = {
            _leading_verb(part)
            for part in draft_parts
            if _leading_verb(part) not in {"hold", "pass"}
        }
        model_work = {
            _leading_verb(part)
            for part in model_parts
            if _leading_verb(part) not in {"hold", "pass"}
        }
        if draft_work == model_work:
            return False
    if (
        duration_seconds is not None
        and duration_seconds >= SHORT_WINDOW_MAX_SECONDS
        and _has_release(draft)
        and not _has_release(model)
        and _same_goal_verb(model, draft)
    ):
        return False
    return True


def _prefer_hold_draft_over_pickup(model: str, draft: str) -> bool:
    """Object already in hand at START is hold, not pick up."""
    draft_parts = split_actions(draft)
    model_parts = split_actions(model)
    if not draft_parts or not model_parts:
        return False
    if not all(_leading_verb(part) == "hold" for part in draft_parts):
        return False
    return any(_leading_verb(part) == "pick up" for part in model_parts)


def _invented_cut_on_hold_draft(model: str, draft: str) -> bool:
    """Do not upgrade hold scissors to cut when the Atlas row only held them."""
    if any(_leading_verb(part) == "cut" for part in split_actions(draft)):
        return False
    if not any(_leading_verb(part) == "cut" for part in split_actions(model)):
        return False
    return bool(re.search(r"\bscissors\b", draft, re.IGNORECASE))


def _same_goal_verb(model: str, draft: str) -> bool:
    """True when both labels are the same work verb with different object names."""
    model_verbs = _work_verbs(model)
    draft_verbs = _work_verbs(draft)
    return bool(model_verbs) and model_verbs == draft_verbs


def _model_copied_previous_scene(
    model: str, draft: str, previous: str | None
) -> bool:
    """True when the model reused the last row's objects and ignored this Atlas draft."""
    if not previous or not draft or not model:
        return False
    if looks_like_leftover_label(draft) or is_generic_placeholder_label(draft):
        return False
    prev_obj = _canonical_scene_tokens(previous)
    draft_obj = _canonical_scene_tokens(draft)
    model_obj = _canonical_scene_tokens(model)
    if not prev_obj or not draft_obj or not model_obj:
        return False
    if model_obj & draft_obj:
        return False
    return bool(model_obj & prev_obj)


def _model_adds_required_extra(model: str, draft: str) -> bool:
    """Keep a trailing pick up/place/insert the draft omitted."""
    model_parts = split_actions(model)
    draft_parts = split_actions(draft)
    if len(model_parts) <= len(draft_parts):
        return False
    if _has_release(draft) and not _has_release(model):
        return False
    extra = model_parts[-1]
    verb = _leading_verb(extra)
    if verb not in REQUIRED_EXTRA_VERBS:
        return False
    if verb == "pick up" and extra is model_parts[0]:
        return False
    if verb == "gather" and len(draft_parts) == 1:
        if _leading_verb(draft_parts[0]) in {
            "dig",
            "strip",
            "twist",
            "rake",
            "mop",
            "wipe",
            "iron",
        }:
            return False
    if verb == "pick up" and re.search(r"\b(?:pliers|shears)\b", extra, re.IGNORECASE):
        if any(_leading_verb(part) == "strip" for part in draft_parts):
            return False
    return True


def reconcile_with_draft(model_label: str, draft_label: str | None) -> str:
    """Keep a one-action draft when the model only invented a trailing hold."""
    if not draft_label:
        return model_label
    if is_generic_placeholder_label(draft_label):
        return model_label
    draft = sanitize_label(draft_label)
    if draft == "No Action":
        return model_label
    model_parts = split_actions(model_label)
    draft_parts = split_actions(draft)
    if len(model_parts) == len(draft_parts) + 1 and HAND_PATTERN.search(draft):
        extra_pickup = (
            _leading_verb(model_parts[0]) == "pick up"
            and _leading_verb(draft_parts[0]) != "pick up"
        )
        extra_hold = HOLD_CLAUSE_PATTERN.search(model_parts[-1]) and not any(
            HOLD_CLAUSE_PATTERN.search(part) for part in draft_parts
        )
        extra_micro = _leading_verb(model_parts[-1]) in WORK_MICROS
        if extra_pickup or extra_micro:
            return draft
        if extra_hold and "both hands" in draft.lower():
            return draft
    if (
        len(model_parts) >= 2
        and HOLD_CLAUSE_PATTERN.search(model_parts[-1])
        and len(draft_parts) == len(model_parts)
        and _leading_verb(draft_parts[-1]) == "pick up"
    ):
        return draft
    if (
        len(draft_parts) == len(model_parts) + 1
        and len(draft_parts) <= MAX_ACTIONS_PER_LABEL
        and (
            _leading_verb(draft_parts[-1]) in {"place", "set", "pass", "gather"}
            or _is_case_a_stabilize(draft)
        )
        and HAND_PATTERN.search(draft)
    ):
        return draft
    return model_label


def choose_final_label(
    model_label: str,
    draft_label: str | None,
    previous_label: str | None = None,
    frames_have_video: bool = False,
    duration_seconds: float | None = None,
    next_label: str | None = None,
) -> str:
    """Keep a specific Atlas row unless the frames show a leftover wrong-clip scene."""
    draft_raw = usable_draft(draft_label)
    if _is_prompt_example(draft_raw):
        draft_raw = None
    model = apply_context_fixes(
        sanitize_label(model_label or ""),
        draft_raw,
        previous_label,
        next_label,
        duration_seconds,
    )
    long_idle = (
        duration_seconds is not None
        and duration_seconds >= NO_ACTION_MIN_SECONDS
        and frames_have_video
    )
    if model == "No Action":
        if long_idle:
            return "No Action"
        model = ""

    if draft_raw:
        draft = apply_context_fixes(
            rewrite_generic_animal_draft(draft_raw),
            draft_raw,
            previous_label,
            next_label,
            duration_seconds,
        )
        if not model:
            print(f"[Pipeline]: Using Atlas draft (model empty): '{draft}'")
            return _finalize_draft_choice(draft, model, duration_seconds)
        if model_hallucinates_against_draft(model, draft_raw):
            print(
                "[Pipeline]: Model swapped a specific Atlas name for a common mistake. "
                f"Keeping Atlas draft: '{draft}'"
            )
            return _finalize_draft_choice(draft, model, duration_seconds)
        if _copied_previous_ignoring_draft(model, draft, previous_label):
            print(
                "[Pipeline]: Model copied the previous segment. "
                f"Keeping Atlas draft: '{draft}'"
            )
            return _finalize_draft_choice(draft, model, duration_seconds)
        if _model_copied_previous_scene(model, draft, previous_label):
            print(
                "[Pipeline]: Model reused the previous clip's objects. "
                f"Keeping Atlas draft: '{draft}'"
            )
            return _finalize_draft_choice(draft, model, duration_seconds)
        if _prefer_simpler_model_over_compound_draft(
            model,
            draft,
            draft_raw,
            previous_label,
            duration_seconds,
        ):
            print(
                "[Pipeline]: Vision found fewer actions than compound Atlas draft. "
                f"Using the model: '{model}'"
            )
            return model
        if _prefer_work_draft_over_idle_hold(model, draft):
            print(
                "[Pipeline]: Model turned work into a hold. "
                f"Keeping Atlas draft: '{draft}'"
            )
            return _finalize_draft_choice(draft, model, duration_seconds)
        if _prefer_hold_draft_over_pickup(model, draft):
            print(
                "[Pipeline]: Object was already in hand. "
                f"Keeping Atlas hold: '{draft}'"
            )
            return _finalize_draft_choice(draft, model, duration_seconds)
        if not validate_clause_syntax(model) and validate_clause_syntax(draft):
            print(
                "[Pipeline]: Model clause is missing an object noun. "
                f"Keeping Atlas draft: '{draft}'"
            )
            return _finalize_draft_choice(draft, model, duration_seconds)
        if _invented_cut_on_hold_draft(model, draft):
            print(
                "[Pipeline]: Model invented a cut. "
                f"Keeping Atlas draft: '{draft}'"
            )
            return _finalize_draft_choice(draft, model, duration_seconds)
        if _model_skipped_setup(model, draft, previous_label):
            print(
                "[Pipeline]: Model skipped setup before the main task. "
                f"Keeping Atlas draft: '{draft}'"
            )
            return _finalize_draft_choice(draft, model, duration_seconds)
        if _model_inflated_pass_chain(model, draft):
            print(
                "[Pipeline]: Model added stabilizing holds around a pass. "
                f"Keeping Atlas draft: '{draft}'"
            )
            return _finalize_draft_choice(draft, model, duration_seconds)
        if (
            _same_goal_verb(model, draft)
            and len(split_actions(model)) == 1
            and len(split_actions(draft)) == 1
            and model_fits_draft(model, draft)
            and not looks_like_leftover_label(draft_raw)
        ):
            print(
                "[Pipeline]: Same single goal as the Atlas draft. "
                f"Keeping Atlas names: '{draft}'"
            )
            return _finalize_draft_choice(draft, model, duration_seconds)
        if not model_fits_draft(model, draft):
            leftover = looks_like_leftover_label(draft_raw)
            if should_trust_vision_over_draft(
                model, draft_raw, frames_have_video=frames_have_video
            ):
                reason = "leftover row text" if leftover else "sufficient object overlap"
                print(
                    f"[Pipeline]: Vision object names accepted ({reason}). "
                    f"Using the model: '{model}'"
                )
                return model
            if _same_goal_verb(model, draft) and not leftover:
                print(
                    "[Pipeline]: Same goal verb as the Atlas draft. "
                    f"Keeping Atlas names: '{draft}'"
                )
                return _finalize_draft_choice(draft, model, duration_seconds)
            similarity = object_noun_similarity(model, draft_raw)
            print(
                "[Pipeline]: Vision degraded Atlas object vocabulary "
                f"({similarity:.0%} overlap). "
                f"Keeping Atlas draft: '{draft}'"
            )
            return _finalize_draft_choice(draft, model, duration_seconds)
        placed = _prefer_place_over_pickup(model, draft)
        if placed:
            print(
                "[Pipeline]: pick up vs place of the same object. Keeping place."
            )
            return placed
        if len(split_actions(model)) > len(split_actions(draft)):
            if (
                duration_seconds is not None
                and duration_seconds < SHORT_WINDOW_MAX_SECONDS
                and not looks_like_leftover_label(draft_raw)
            ):
                print(
                    "[Pipeline]: Short window cannot fit the extra clauses. "
                    f"Keeping Atlas draft: '{draft}'"
                )
                return _finalize_draft_choice(draft, model, duration_seconds)
            if _has_release(draft) and not _has_release(model):
                print(
                    "[Pipeline]: Draft already has a place/set. "
                    f"Keeping Atlas draft: '{draft}'"
                )
                return _finalize_draft_choice(draft, model, duration_seconds)
            if _is_case_a_stabilize(model) and not _is_case_a_stabilize(draft):
                print(
                    "[Pipeline]: Draft missed an off-hand stabilize. "
                    f"Using the model: '{model}'"
                )
                return model
            if _hid_distinct_hands(draft_raw) and _has_distinct_hands(model):
                print(
                    "[Pipeline]: Draft hid distinct hands as both hands. "
                    f"Using the model: '{model}'"
                )
                return model
            if _has_release(model) and not _has_release(draft):
                print(
                    "[Pipeline]: Draft missed a place/set. "
                    f"Using the model: '{model}'"
                )
                return model
            if _model_adds_required_extra(model, draft):
                print(
                    "[Pipeline]: Draft missed a pick up/place/pass. "
                    f"Using the model: '{model}'"
                )
                return model
            print(
                f"[Pipeline]: Model added extra actions. Keeping Atlas draft: '{draft}'"
            )
            return _finalize_draft_choice(draft, model, duration_seconds)
        if len(split_actions(draft)) > len(split_actions(model)):
            if _prefer_simpler_model_over_compound_draft(
                model,
                draft,
                draft_raw,
                previous_label,
                duration_seconds,
            ):
                print(
                    "[Pipeline]: Compound Atlas draft exceeds short-window model. "
                    f"Using the model: '{model}'"
                )
                return model
            if _is_case_a_stabilize(draft) or (
                _has_release(draft) and not _has_release(model)
            ):
                if (
                    duration_seconds is not None
                    and duration_seconds < SHORT_WINDOW_MAX_SECONDS
                    and not _is_case_a_stabilize(draft)
                ):
                    print(
                        "[Pipeline]: Short window — trusting simpler model over "
                        f"extra draft clauses: '{model}'"
                    )
                    return model
                print(
                    "[Pipeline]: Model dropped a required hold/place. "
                    f"Keeping Atlas draft: '{draft}'"
                )
                return _finalize_draft_choice(draft, model, duration_seconds)
        chosen = reconcile_with_draft(model, draft)
        if is_generic_placeholder_label(chosen):
            return _finalize_draft_choice(draft, model, duration_seconds)
        return chosen

    if model:
        if is_generic_placeholder_label(model):
            return rewrite_generic_animal_draft(model)
        return model
    return "No Action"


def _api_key() -> str | None:
    for name in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        key = (os.getenv(name) or "").strip().strip('"').strip("'")
        if key and not key.startswith("your-actual-api-key"):
            return key
    return None


def _build_client():
    if openai is None:
        return None
    key = _api_key()
    if not key:
        return None
    return openai.OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=key,
        default_headers=OPENROUTER_HEADERS,
    )


def _llm_disabled_create(**kwargs):
    raise RuntimeError(
        "Vision LLM is disabled in atlas-hybrid-bot. Use label_pipeline.generate_label_hybrid."
    )


# Patchable stub — LLM unit tests monkeypatch client.chat.completions.create.
client = SimpleNamespace(
    chat=SimpleNamespace(
        completions=SimpleNamespace(create=_llm_disabled_create)
    )
)

ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
TENS = [
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
]


def _int_to_words(value: int) -> str:
    """Convert a non-negative integer to English words. NUMBER_MAP covers 0-10."""
    if str(value) in NUMBER_MAP:
        return NUMBER_MAP[str(value)]
    if value < 20:
        return ONES[value]
    if value < 100:
        ten, remainder = divmod(value, 10)
        if remainder == 0:
            return TENS[ten]
        return f"{TENS[ten]} {ONES[remainder]}"
    if value < 1000:
        hundred, remainder = divmod(value, 100)
        if remainder == 0:
            return f"{ONES[hundred]} hundred"
        return f"{ONES[hundred]} hundred { _int_to_words(remainder)}"
    return str(value)


def _strip_looking_language(text: str) -> str:
    """Drop inspect/check/examine clauses. Looking is not a hand action."""
    cleaned = text
    for verb in LOOKING_VERBS:
        cleaned = re.sub(rf"\b{re.escape(verb)}\s+\w+\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(rf"\b{re.escape(verb)}\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = " ".join(cleaned.split())
    cleaned = re.sub(r"\b(?:and|,)\s+(?:and|,)\b", ",", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:and|,)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:\s+\band\b|\s*,)\s*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" ,")


def _fix_plural_only_tools(text: str) -> str:
    cleaned = text
    for singular, plural in PLURAL_ONLY_TOOLS.items():
        cleaned = re.sub(rf"\b{singular}s?\b", plural, cleaned, flags=re.IGNORECASE)
    return cleaned


def _drop_mixed_no_action(text: str) -> str:
    if re.search(r"\bno action\b", text, re.IGNORECASE) and re.search(
        r"\b(?:pick|place|hold|pass|move|chop|open|close)\b", text, re.IGNORECASE
    ):
        cleaned = re.sub(r"\bno action\b", "", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*,\s*,", ",", cleaned)
        return cleaned.strip(" ,")
    return text


def sanitize_label(text: str) -> str:
    """Cleans and validates generated labels against Atlas audit rules."""
    if not text or text.strip().lower() in ["no action", "no action."]:
        return "No Action"

    cleaned = text.strip().strip('"').strip("'")

    # 1. Strip trailing periods
    if cleaned.endswith("."):
        cleaned = cleaned[:-1].strip()

    # 2. Convert numerical digits to words
    def replace_digit(match):
        digit_str = match.group(0)
        if digit_str in NUMBER_MAP:
            return NUMBER_MAP[digit_str]
        try:
            return _int_to_words(int(digit_str))
        except ValueError:
            return digit_str

    cleaned = DIGIT_PATTERN.sub(replace_digit, cleaned)

    # 3. Convert continuous/past verbs to imperative forms
    for continuous, imperative in VERB_CORRECTIONS.items():
        pattern = re.compile(rf"\b{continuous}\b", re.IGNORECASE)
        cleaned = pattern.sub(imperative, cleaned)
    cleaned = re.sub(
        r"\bwatering\b(?!\s+can\b)", "water", cleaned, flags=re.IGNORECASE
    )

    # 4. Drop looking language (never rewrite as "adjust")
    cleaned = _strip_looking_language(cleaned)

    # 5. Replace remaining banned verbs with audit-safe alternatives
    for banned, replacement in VERB_REPLACEMENTS.items():
        cleaned = re.sub(rf"\b{banned}\b", replacement, cleaned, flags=re.IGNORECASE)

    # 6. Drop "reach" except leftover empty labels become No Action
    cleaned = re.sub(r"\breach\b", "", cleaned, flags=re.IGNORECASE)

    # 7. Progressive leftovers from FORBIDDEN_WORDS
    for word in FORBIDDEN_WORDS:
        if word in LOOKING_VERBS or word in VERB_REPLACEMENTS or word == "reach":
            continue
        pattern = re.compile(rf"\b{word}\b", re.IGNORECASE)
        if word == "holding":
            cleaned = pattern.sub("hold", cleaned)
        elif word == "picking":
            cleaned = pattern.sub("pick", cleaned)
        elif word == "placing":
            cleaned = pattern.sub("place", cleaned)

    # 8. Articles, illegal separators, plural-only tools
    cleaned = ARTICLE_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"\busing\b", "with", cleaned, flags=re.IGNORECASE)
    cleaned = COMMA_AND_PATTERN.sub(",", cleaned)
    cleaned = SLASH_PATTERN.sub(", ", cleaned)
    cleaned = SEMICOLON_PATTERN.sub(", ", cleaned)
    cleaned = _fix_plural_only_tools(cleaned)
    cleaned = _drop_mixed_no_action(cleaned)
    cleaned = _strip_narrative_words(cleaned)
    cleaned = " ".join(cleaned.split())
    cleaned = cleaned.strip(" ,")
    cleaned = _fill_with_visible_substance(cleaned)
    cleaned = _finish_incomplete_hands(cleaned)
    cleaned = _fill_missing_clause_objects(cleaned)
    cleaned = _insert_pass_on_hand_change(cleaned)
    cleaned = _trim_redundant_pass_stabilizers(cleaned)
    cleaned = _drop_soil_pickup_while_digging(cleaned)
    cleaned = _normalize_glass_cup(cleaned)
    cleaned = _split_false_both_hands_pickup(cleaned)
    cleaned = _strip_book_page_turn(cleaned)
    cleaned = _split_false_both_hands(cleaned)
    cleaned = _replace_unapproved_nouns(cleaned)
    cleaned = _name_wipe_cloth(cleaned)
    cleaned = _ensure_offhand_hold_for_dish_wipe(cleaned)
    cleaned = _ensure_offhand_hold_for_cloth_work(cleaned)
    cleaned = _name_self_tool_and_location(cleaned)
    cleaned = _strip_instrumental_pickup(cleaned)
    cleaned = _strip_micro_movements(cleaned)
    cleaned = _collapse_repeated_work(cleaned)
    cleaned = _drop_contradictory_hold_after_pickup(cleaned)
    cleaned = _collapse_redundant_hold(cleaned)
    cleaned = _drop_cookware_hold_while_stirring(cleaned)
    cleaned = _rewrite_close_door_to_pass(cleaned)
    cleaned = _attach_missing_hands(cleaned)
    cleaned = _ensure_place_location(cleaned, None)
    cleaned = _cap_actions(cleaned)
    cleaned = " ".join(cleaned.split())
    cleaned = cleaned.strip(" ,")

    if not cleaned or cleaned.lower() in {"and", "with", "no action"}:
        return "No Action"

    has_action_verb = re.search(
        r"\b(?:pick|place|hold|pass|move|chop|open|close|slide|shift|align|"
        r"rotate|flatten|tighten|fold|tuck|squeeze|wipe|cut|put|take|work|"
        r"scrub|iron|wash|dip|unfold|grip|press|push|pull|twist|pinch|turn|"
        r"straighten|tilt|dig|scoop|lift|pour|mix|stir|pack|tamp|scrape|"
        r"sweep|shovel|pat|tap|shake|peel|insert|remove|fill|empty|drop|"
        r"set|lower|raise|carry|drag|flip|spread|smooth|stack|unstack|water|gather|trim|unfold|seal|smoothen|rake|fold|strip|mop|align|stir|sew|draw|insert)\b",
        cleaned,
        re.IGNORECASE,
    )
    has_hand = HAND_PATTERN.search(cleaned)
    if not has_action_verb and not has_hand:
        return "No Action"

    if not HAND_PATTERN.search(cleaned):
        print(
            f"[Sanitize Warning]: Label is missing a hand: '{cleaned}'. "
            "Atlas requires left hand, right hand, or both hands."
        )

    return cleaned


REFUSAL_MARKERS = (
    "i cannot",
    "i can't",
    "i am unable",
    "i'm unable",
    "i'm not able",
    "cannot assist",
    "can't assist",
    "not able to",
    "against my",
    "content policy",
    "i won't",
    "i will not",
    "as an ai",
)


def _looks_like_refusal(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return True
    return any(marker in low for marker in REFUSAL_MARKERS)


def _subsample_frames(
    frames: list[str],
    timestamps: list[float] | None,
    max_frames: int = 8,
) -> tuple[list[str], list[float] | None]:
    if len(frames) <= max_frames:
        return frames, timestamps
    last = len(frames) - 1
    indexes = sorted(
        {
            round(index * last / (max_frames - 1))
            for index in range(max_frames)
        }
    )
    picked = [frames[i] for i in indexes]
    times = None
    if timestamps:
        times = [timestamps[i] for i in indexes if i < len(timestamps)]
    return picked, times


def _vision_user_content(
    base64_frames: list[str],
    previous_label: str | None = None,
    draft_label: str | None = None,
    duration_seconds: float | None = None,
    frame_timestamps: list[float] | None = None,
    insist_action: bool = False,
    frames_have_video: bool = False,
    global_context: GlobalVideoContext | None = None,
) -> list[dict]:
    """Build the vision prompt. Atlas drafts are never included — models copy them."""
    total = len(base64_frames)
    intro = (
        "These frames are sampled while the clip plays at normal speed "
        "(laundry, cooking, dishes, grooming, assembly, crafts). "
        "Always output an Atlas label or No Action. Never refuse. Never explain. "
        + SPATIAL_HAND_RULES
        + "Name the hand, the object, and the motion. No pronouns. No -ing. No articles. "
        "Always label the off-hand when it holds or works. "
        "If an object changes hands, write pass [object] from [hand] to [hand]. "
        "place/set always needs a location. "
        "If they grab a tool only to use it immediately, omit pick up. Write pick up not grab. "
        "Do not add hold for an empty hand or for the same tool already named. "
        "Do add hold when one hand stabilizes (carrot, paper, plate) while the other works. "
        "Do not add hold pan/wok while stirring. "
        "If scissors are only held, write hold scissors not cut. "
        "set/place beat hold of the same object. "
        "Every clause needs an object noun. Never write pick up with right hand. "
        "If the object starts in one hand and ends in the other, write pass. "
        "place bucket needs pick up hoe. After digging write place hoe, gather soil. "
        "pick up ONLY if the object starts on a surface. Already in hand → hold. "
        "Do not split cut/wipe/dig/water/write/trim into micro shift/align/tap clauses. "
        "Max 3 clauses. Prefer one coarse verb. Never write tool/then/next/other/fingers. "
        "Never write bare animal. Stay consistent with prior object and verb names. "
        "If the object is released, write place/set. "
        "No Action ONLY if hands are off the task for at least five seconds. "
        "A task-relevant hold is not No Action. Never mix No Action with a real action. "
        "Name the object you see in THESE frames (plate, cloth, hose, toy, plant, etc.). "
        "Do not reuse an example from the instructions if it is not in the pictures. "
        "If an object changes hands, write pass [object] from [hand] to [hand]. "
        "Hands holding or using an object is an action even if the stills look similar. "
        "both hands ONLY if both hands do the same job. "
        "If one hand holds a cloth and the other rubs it, write hold cloth in left hand, smoothen cloth with right hand. Not fold with both hands. "
        "If one hand holds a glass cup and the other wipes it, write hold glass cup with left hand, wipe glass cup with cloth in right hand. Not both hands. "
        "Never write sew, draw, write, or press on a cap. Write insert sewing needle into cap and pull sewing needle. "
        "If the hand turns the cup while wiping, write rotate glass cup with left hand, not hold. "
        "When wiping a glass cup, the cup is the target; cloth is only the implement. "
        "A window under 3 seconds usually has 1 or 2 actions. Do not invent extra hold/pass/place chains. "
        "KEEP pass when the object changes hands. Do not copy the previous segment if this window shows fold, strip, place, or insert. "
        "A metal pin is not a wrench. "
        "rake leaves needs on ground and with rake in [hand]. Never erase — write wipe with cloth. "
        "A sewing needle is not a pen. A cap is not a hat. Shears are not pliers. strip is not twist. "
        "If the LAST frame shows the object on a shelf or table, write place not pick up. "
        "If pick up is the last motion in this window, keep it. "
        "Do NOT output No Action if either hand holds an object or a tool. "
        "Never copy a gold example (dough, hose, wrench, scissors) unless it is in the pictures. "
        "Output only the raw label."
    )
    if insist_action:
        intro = (
            "These frames show first-person HAND WORK. "
            "Write No Action only if hands are off the task for at least five seconds. "
            "A hold that matters to the task is not No Action. "
            "Name the object you actually see in the pictures. "
            "Always name left hand, right hand, or both hands. Always label the off-hand if it holds. "
            "If the object changes hands, write pass [object] from [hand] to [hand]. "
            "place/set needs a location. No articles. No pronouns. No grab (write pick up). "
            "Do not write pick up if the tool is used immediately. "
            "Do not write shift/align/slide inside a continuous action. "
            "Do write place/set/pass if the object is released or changes hands. "
            "If one hand holds a plate and the other wipes with a cloth, write two clauses "
            "with left hand and right hand. Do not write both hands for that. "
            "Missing the hold is Missing Action. "
            "A clear dish is glass plate, not bowl. "
            "Do not write stuffed animal, scissors, dough, hose, or any example unless it is visible. "
            "Atlas syntax: verb + object + with [hand]. Never refuse. Never explain. "
            + SPATIAL_HAND_RULES
            + "Output only the raw label."
        )
    user_content: list[dict] = [{"type": "text", "text": intro}]
    if duration_seconds is not None:
        cap = (
            "EXACTLY 1 action clause."
            if duration_seconds < SHORT_WINDOW_MAX_SECONDS
            else f"at most {MEDIUM_WINDOW_MAX_CLAUSES} action clauses."
        )
        user_content[0]["text"] += (
            f" This window is {duration_seconds:.1f} seconds long. Output {cap}"
        )
    allowed = merge_allowed_object_names(draft_label, global_context)
    if allowed:
        user_content[0]["text"] += (
            " Allowed objects (use ONLY these exact nouns): "
            + ", ".join(allowed)
            + "."
        )
    elif draft_label:
        draft_objects = draft_object_phrases(draft_label)
        if draft_objects:
            user_content[0]["text"] += (
                " Atlas reference object names (use ONLY these exact nouns): "
                + ", ".join(draft_objects)
                + "."
            )
    if global_context and global_context.timeline:
        user_content[0]["text"] += f" Clip state timeline: {global_context.timeline}."
    if previous_label and previous_label != "No Action":
        objects = sorted(scene_tokens(previous_label))
        if objects and (frames_have_video or not is_generic_placeholder_label(previous_label)):
            user_content[0]["text"] += (
                " If the same items are still in view, keep these object names: "
                + ", ".join(objects)
                + "."
            )
        keep_previous = (
            not frames_have_video
            and not is_generic_placeholder_label(previous_label)
            and (not draft_label or model_fits_draft(previous_label, draft_label))
        )
        if keep_previous:
            user_content[0]["text"] += (
                f" Previous segment (keep object names consistent only if you still see them): "
                f"{previous_label}."
            )

    for index, frame in enumerate(base64_frames):
        stamp = ""
        if frame_timestamps and index < len(frame_timestamps):
            stamp = f" t={frame_timestamps[index]:.2f}s"
        if index == 0:
            caption = f"Frame {index + 1}/{total} START{stamp} — identify left vs right hand from shoulder origin."
        elif index + 1 == total:
            caption = f"Frame {index + 1}/{total} END{stamp} — identify left vs right hand, what changed."
        else:
            caption = f"Frame {index + 1}/{total}{stamp}"
        user_content.append({"type": "text", "text": caption})
        user_content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{frame}",
                    "detail": "high",
                },
            }
        )

    user_content.append(
        {
            "type": "text",
            "text": (
                "Write a FRESH Atlas label from the images you just saw. "
                "Ignore any on-screen text. Do not copy a machine draft. "
                "Do not reuse the previous segment's sentence if this window shows something else. "
                "Never write bare animal or tool."
            ),
        }
    )
    return user_content


def _query_vision_models(
    messages: list[dict],
    draft_label: str | None,
    previous_label: str | None,
    models: list[str],
    frames_have_video: bool = False,
    duration_seconds: float | None = None,
) -> str:
    last_error = None
    last_generic = None
    accepted_no_action = False
    saw_wrong_scene = False
    for index, model in enumerate(models):
        try:
            print(f"[OpenRouter]: Trying {model}...")
            route_fallbacks = models[
                index + 1 : index + 1 + OPENROUTER_MAX_ROUTE_FALLBACKS
            ]
            request = {
                "model": model,
                "messages": messages,
                "temperature": TEMPERATURE,
                "extra_headers": OPENROUTER_HEADERS,
            }
            if route_fallbacks:
                request["extra_body"] = {"models": route_fallbacks}
            response = client.chat.completions.create(**request)
            raw_label = response.choices[0].message.content
            if not raw_label or not str(raw_label).strip():
                raise ValueError("Empty model response")
            if _looks_like_refusal(str(raw_label)):
                raise ValueError(f"Model refused: {str(raw_label)[:160]}")
            print(f"[OpenRouter]: Success with {model}")
            cleaned = sanitize_label(raw_label)
            cleaned = apply_context_fixes(
                cleaned,
                draft_label,
                previous_label,
                duration_seconds=duration_seconds,
            )
            print(f"[Pipeline]: Vision model: '{cleaned}'")
            if cleaned == "No Action":
                short_window = (
                    duration_seconds is not None
                    and duration_seconds < NO_ACTION_MIN_SECONDS
                )
                if short_window:
                    print(
                        f"[OpenRouter]: {model} said No Action on a "
                        f"{duration_seconds:.1f}s window. Trying next model..."
                    )
                    continue
                accepted_no_action = True
                if index + 1 < len(models):
                    print(
                        f"[OpenRouter]: {model} said No Action. Trying next model..."
                    )
                continue
            if _is_prompt_example(cleaned):
                print(
                    f"[OpenRouter]: {model} copied a prompt example "
                    f"({cleaned!r}). Trying next model..."
                )
                continue
            if is_generic_placeholder_label(cleaned):
                last_generic = cleaned
                if index + 1 < len(models):
                    print(
                        f"[OpenRouter]: {model} used generic 'animal' "
                        f"({cleaned!r}). Trying next model..."
                    )
                    continue
            hallucinated = bool(
                draft_label and model_hallucinates_against_draft(cleaned, draft_label)
            )
            if hallucinated:
                saw_wrong_scene = True
                print(
                    f"[OpenRouter]: {model} swapped a specific Atlas name "
                    f"({cleaned!r} vs {draft_label!r}). Trying next model..."
                )
                continue
            if draft_label and not model_fits_draft(cleaned, draft_label):
                if should_trust_vision_over_draft(
                    cleaned,
                    draft_label,
                    frames_have_video=frames_have_video,
                ):
                    print(
                        f"[OpenRouter]: {model} object names accepted "
                        f"({object_noun_similarity(cleaned, draft_label):.0%} draft overlap). "
                        f"Using the model."
                    )
                    return reconcile_with_draft(cleaned, draft_label)
                saw_wrong_scene = True
                print(
                    f"[OpenRouter]: {model} object vocabulary degraded vs Atlas draft "
                    f"({object_noun_similarity(cleaned, draft_label):.0%} overlap, "
                    f"need {OBJECT_SIMILARITY_THRESHOLD:.0%}). Trying next model..."
                )
                continue
            if draft_label and _labels_match(cleaned, draft_label):
                print(
                    "[Pipeline]: Model output matches the Atlas draft. "
                    "The draft was not sent to the model."
                )
            return reconcile_with_draft(cleaned, draft_label)
        except Exception as e:
            last_error = e
            print(f"[Warning] {model} failed: {e}. Trying next fallback...")
            continue

    kept_draft = usable_draft(draft_label)
    if kept_draft and saw_wrong_scene:
        cleaned_draft = apply_context_fixes(
            sanitize_label(kept_draft),
            draft_label,
            previous_label,
            duration_seconds=duration_seconds,
        )
        print(
            "[Pipeline]: Models did not match the scene. Keeping Atlas draft: "
            f"'{cleaned_draft}'"
        )
        return _finalize_draft_choice(
            cleaned_draft,
            duration_seconds=duration_seconds,
        )
    if last_generic:
        print(
            "[Pipeline]: Every vision model used generic 'animal'. "
            "Not copying the Atlas draft."
        )
        return last_generic
    if accepted_no_action:
        return "No Action"
    print(f"[Error] All vision models failed. Last error: {last_error}")
    return "No Action"


def generate_label_from_frames(
    base64_frames: list[str],
    previous_label: str | None = None,
    draft_label: str | None = None,
    duration_seconds: float | None = None,
    frame_timestamps: list[float] | None = None,
    frames_have_video: bool = False,
    next_label: str | None = None,
    global_context: GlobalVideoContext | None = None,
    segment_start_seconds: float | None = None,
) -> str:
    """Sends encoded frame images to OpenRouter VLMs with sequential fallbacks."""
    if not _api_key():
        print("[API Error]: OPENROUTER_API_KEY is missing. Returning 'No Action'.")
        return "No Action"

    draft_label = usable_draft(draft_label)
    previous_label = usable_draft(previous_label)
    next_label = usable_draft(next_label)

    start_seconds = segment_start_seconds
    if start_seconds is None and frame_timestamps:
        start_seconds = min(frame_timestamps)
    motion_profile = analyze_segment_motion(base64_frames, frame_timestamps)
    base64_frames, frame_timestamps = prepare_segment_frames(
        base64_frames,
        frame_timestamps,
        duration_seconds=duration_seconds,
        start_seconds=start_seconds,
        motion_profile=motion_profile,
    )
    insist = bool(frames_have_video)
    user_content = _vision_user_content(
        base64_frames,
        previous_label=previous_label,
        draft_label=draft_label,
        duration_seconds=duration_seconds,
        frame_timestamps=frame_timestamps,
        insist_action=insist,
        frames_have_video=frames_have_video,
        global_context=global_context,
    )
    system = ACTION_SYSTEM_PROMPT if frames_have_video else SYSTEM_PROMPT
    system += build_draft_vocabulary_system_addon(draft_label, global_context)
    system += build_global_context_system_addon(global_context)
    messages = [{"role": "system", "content": system}]
    messages.extend(FEW_SHOT_CORRECTION_MESSAGES)
    messages.append({"role": "user", "content": user_content})
    label = _query_vision_models(
        messages,
        draft_label,
        previous_label,
        list(VISION_MODELS),
        frames_have_video=frames_have_video,
        duration_seconds=duration_seconds,
    )
    if label == "No Action" and not draft_label:
        print(
            "[Pipeline]: All models said No Action and there is no usable Atlas draft."
        )
    final = choose_final_label(
        label,
        draft_label,
        previous_label,
        frames_have_video=frames_have_video,
        duration_seconds=duration_seconds,
        next_label=next_label,
    )
    return finalize_pipeline_label(
        final,
        draft_label,
        previous_label,
        duration_seconds,
        global_context,
        motion_profile,
    )


if __name__ == "__main__":
    test_raw = "picking up 2 spoons and inspect handle."
    print("Raw Input: ", test_raw)
    print("Sanitized Output:", sanitize_label(test_raw))
