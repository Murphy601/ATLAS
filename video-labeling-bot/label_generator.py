import os
import re

import openai
from dotenv import load_dotenv

from config import (
    ARTICLE_PATTERN,
    COMMA_AND_PATTERN,
    CONTINUOUS_VERBS,
    DIGIT_PATTERN,
    FILL_SOURCE_TOOLS,
    FORBIDDEN_WORDS,
    GENERIC_NOUNS,
    HAND_PATTERN,
    LOOKING_VERBS,
    MAX_ACTIONS_PER_LABEL,
    MICRO_VERBS,
    NAMED_IMPLEMENTS,
    NARRATIVE_WORDS,
    NUMBER_MAP,
    OPENROUTER_BASE_URL,
    OPENROUTER_HEADERS,
    OPENROUTER_MAX_ROUTE_FALLBACKS,
    PLURAL_ONLY_TOOLS,
    PROMPT_EXAMPLE_LABELS,
    SEMICOLON_PATTERN,
    SLASH_PATTERN,
    SYSTEM_PROMPT,
    ACTION_SYSTEM_PROMPT,
    TEMPERATURE,
    TRANSFER_VERBS,
    USE_VERBS,
    VERB_CORRECTIONS,
    VERB_REPLACEMENTS,
    VISION_MODELS,
)

load_dotenv()


LEADING_VERB_PATTERN = re.compile(
    r"^(pick up|put down|pass|place|set|hold|move|fill|water|spray|wash|"
    r"rinse|scrub|sweep|dig|pour|stir|mix|iron|cut|chop|wipe|work|knead|"
    r"fold|flatten|tighten|squeeze|open|close|slide|shift|align|rotate|"
    r"tuck|grip|press|push|pull|twist|pinch|turn|straighten|tilt|scoop|"
    r"lift|pack|tamp|scrape|shovel|pat|tap|shake|peel|insert|remove|empty|"
    r"drop|lower|raise|carry|drag|flip|spread|smooth|stack|unstack|unfold|"
    r"put|grab|hand|gather|write|brush|sand|hammer|drill|trim)\b",
    re.IGNORECASE,
)
HOLD_CLAUSE_PATTERN = re.compile(r"^hold\b", re.IGNORECASE)
TWO_HANDED_TOOLS = ("hose", "rope")
WIPE_VERBS = {"wipe", "scrub", "wash", "dry", "polish"}
INCOMPLETE_HAND_PATTERN = re.compile(
    r"\b(with|in) (left|right)\b(?!\s+hand)",
    re.IGNORECASE,
)
FILL_SOURCE_PATTERN = re.compile(
    rf"\bfill\s+(.+?)\s+with\s+({'|'.join(FILL_SOURCE_TOOLS)})\b",
    re.IGNORECASE,
)
NARRATIVE_PATTERN = re.compile(
    rf"\b(?:{'|'.join(NARRATIVE_WORDS)})\b",
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


def _pickup_object(clause: str) -> str:
    text = LEADING_VERB_PATTERN.sub("", clause, count=1).strip()
    text = re.sub(
        r"\s+with\s+(?:left hand|right hand|both hands)\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


def _strip_instrumental_pickup(text: str) -> str:
    """Drop pick up X when the next clause immediately uses X (not place/pass)."""
    clauses = split_actions(text)
    if len(clauses) < 2 or _leading_verb(clauses[0]) != "pick up":
        return text
    next_verb = _leading_verb(clauses[1])
    if not next_verb or next_verb in TRANSFER_VERBS or next_verb == "pick up":
        return text
    if next_verb not in USE_VERBS:
        return text
    picked = _pickup_object(clauses[0])
    if not picked:
        return text
    if not re.search(rf"\b{re.escape(picked)}\b", clauses[1], re.IGNORECASE):
        return text
    print(f"[Sanitize]: Dropped instrumental pick up '{clauses[0]}'")
    return ", ".join(clauses[1:])


def _strip_micro_movements(text: str) -> str:
    """Drop shift/align/slide after a continuous work verb on the same idea."""
    clauses = split_actions(text)
    if len(clauses) != 2:
        return text
    first_verb = _leading_verb(clauses[0])
    second_verb = _leading_verb(clauses[1])
    if first_verb in CONTINUOUS_VERBS and second_verb in MICRO_VERBS:
        return clauses[0]
    if second_verb in CONTINUOUS_VERBS and first_verb in MICRO_VERBS:
        return clauses[1]
    return text


def _cap_actions(text: str, limit: int = MAX_ACTIONS_PER_LABEL) -> str:
    clauses = split_actions(text)
    if len(clauses) <= limit:
        return text
    print(f"[Sanitize]: Capping {len(clauses)} actions to {limit}")
    return ", ".join(clauses[:limit])


def _collapse_redundant_hold(text: str) -> str:
    """Only merge a trailing hold when both hands are on the same two-handed tool.

    Off-hand stabilize + work (hold paper, cut with scissors) must stay two clauses.
    """
    clauses = split_actions(text)
    if len(clauses) != 2 or not HOLD_CLAUSE_PATTERN.search(clauses[1]):
        return text
    first = clauses[0].lower()
    if not any(re.search(rf"\b{re.escape(tool)}\b", first) for tool in TWO_HANDED_TOOLS):
        return text
    first_verb = _leading_verb(clauses[0])
    if not first_verb or first_verb in TRANSFER_VERBS:
        return text
    return _use_both_hands(clauses[0])


def _finish_incomplete_hands(text: str) -> str:
    """wipe plate with right -> wipe plate with right hand."""
    return INCOMPLETE_HAND_PATTERN.sub(r"\1 \2 hand", text)


DISH_PATTERN = re.compile(
    r"\b(?:glass\s+)?(?:plate|bowl|dish|platter)\b", re.IGNORECASE
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


def _cloth_in(text: str) -> str:
    match = re.search(r"\b(cloth|rag|towel|sponge)\b", text or "", re.IGNORECASE)
    return match.group(1).lower() if match else "cloth"


def _split_false_both_hands(text: str) -> str:
    """Do not hide hold-left + wipe-right as wipe with both hands."""
    clauses = split_actions(_finish_incomplete_hands(text))
    if len(clauses) == 1:
        clause = clauses[0]
        verb = _leading_verb(clause)
        if (
            verb not in WIPE_VERBS
            or "both hands" not in clause.lower()
            or not _is_dish_clause(clause)
        ):
            return ", ".join(clauses)
        obj = _clause_object(clause) or "plate"
        implement = _cloth_in(clause)
        return (
            f"hold {obj} with left hand, "
            f"{verb} {obj} with {implement} in right hand"
        )
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
        if work_verb not in WIPE_VERBS:
            return ", ".join(clauses)
        if not (_is_dish_clause(hold) or _is_dish_clause(work)):
            return ", ".join(clauses)
        obj = _clause_object(hold) or _clause_object(work) or "plate"
        implement = _cloth_in(work)
        return (
            f"hold {obj} with left hand, "
            f"{work_verb} {obj} with {implement} in right hand"
        )
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


def _ensure_offhand_hold_for_dish_wipe(text: str) -> str:
    """Name the stabilizing hand when one hand wipes a dish the other is holding."""
    clauses = split_actions(text)
    if len(clauses) != 1:
        return text
    clause = clauses[0]
    if _leading_verb(clause) not in WIPE_VERBS or not _is_dish_clause(clause):
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
    if re.search(r"\bplate\b", prev) and re.search(r"\bbowl\b", updated, re.IGNORECASE):
        updated = re.sub(r"\bbowl\b", "plate", updated, flags=re.IGNORECASE)
    if re.search(r"\bglass plate\b", prev):
        updated = re.sub(r"(?<!glass )\bplate\b", "glass plate", updated, flags=re.IGNORECASE)
        updated = re.sub(r"\bglass glass plate\b", "glass plate", updated, flags=re.IGNORECASE)
    if re.search(r"\bcloth\b", prev) and re.search(
        r"\b(rag|towel)\b", updated, re.IGNORECASE
    ):
        updated = re.sub(r"\b(?:rag|towel)\b", "cloth", updated, flags=re.IGNORECASE)
    return updated


def _fill_with_visible_substance(text: str) -> str:
    if not re.search(r"\bfill\b", text, re.IGNORECASE):
        return text
    if re.search(r"\bwith water\b", text, re.IGNORECASE):
        return text
    return FILL_SOURCE_PATTERN.sub(r"fill \1 with water with \2", text)


def _strip_narrative_words(text: str) -> str:
    cleaned = NARRATIVE_PATTERN.sub("", text)
    cleaned = " ".join(cleaned.split())
    cleaned = re.sub(r"\s+,", ",", cleaned)
    return cleaned.strip(" ,")


def _named_implement_in(*texts: str | None) -> str | None:
    blob = " ".join(part or "" for part in texts)
    if not blob:
        return None
    for name in NAMED_IMPLEMENTS:
        if re.search(rf"\b{re.escape(name)}\b", blob, re.IGNORECASE):
            return name
    return None


def apply_context_fixes(
    label: str,
    draft_label: str | None = None,
    previous_label: str | None = None,
) -> str:
    """Swap generic nouns and keep object names consistent with the prior segment."""
    if not label or label == "No Action":
        return label
    updated = _align_object_names(label, previous_label)
    updated = _align_object_names(updated, draft_label)
    restored = _restore_stabilize_wipe(updated, previous_label)
    if restored != updated:
        updated = restored
    else:
        updated = _restore_stabilize_wipe(updated, draft_label)
    if GENERIC_NOUN_PATTERN.search(updated):
        specific = _named_implement_in(draft_label, previous_label)
        if specific:
            updated = GENERIC_NOUN_PATTERN.sub(specific, updated)
    return updated


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
    }
)


def scene_tokens(label: str | None) -> set[str]:
    """Object-like words in a label, ignoring hands and common verbs."""
    words = re.findall(r"[a-z]+", (label or "").lower())
    return {word for word in words if len(word) > 2 and word not in SCENE_STOP}


def model_fits_draft(model_label: str, draft_label: str | None) -> bool:
    """False when the model names a different scene than a specific Atlas draft."""
    draft = usable_draft(draft_label)
    if not draft:
        return True
    if not model_label or model_label == "No Action":
        return False
    draft_objects = scene_tokens(draft)
    model_objects = scene_tokens(model_label)
    if not draft_objects:
        return True
    return bool(draft_objects & model_objects)


def _labels_match(left: str | None, right: str | None) -> bool:
    return (left or "").strip().casefold() == (right or "").strip().casefold()


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
        extra_micro = _leading_verb(model_parts[-1]) in MICRO_VERBS
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
        and _leading_verb(draft_parts[-1]) in {"place", "set", "pass", "gather"}
        and HAND_PATTERN.search(draft)
    ):
        return draft
    return model_label


def choose_final_label(
    model_label: str,
    draft_label: str | None,
    previous_label: str | None = None,
    frames_have_video: bool = False,
) -> str:
    """Keep a specific Atlas row unless the frames show a different scene or extra clauses."""
    draft_raw = usable_draft(draft_label)
    if _is_prompt_example(draft_raw):
        draft_raw = None
    model = apply_context_fixes(
        sanitize_label(model_label or ""), draft_raw, previous_label
    )
    if model == "No Action":
        model = ""

    if draft_raw:
        draft = apply_context_fixes(
            rewrite_generic_animal_draft(draft_raw),
            draft_raw,
            previous_label,
        )
        if not model:
            print(f"[Pipeline]: Using Atlas draft (model empty): '{draft}'")
            return draft
        if not model_fits_draft(model, draft):
            if frames_have_video:
                print(
                    "[Pipeline]: Frames show different objects than the row text. "
                    f"Using the model: '{model}'"
                )
                return model
            print(
                f"[Pipeline]: Model named different objects. Keeping Atlas draft: '{draft}'"
            )
            return draft
        if len(split_actions(model)) > len(split_actions(draft)):
            if _hid_distinct_hands(draft_raw) and _has_distinct_hands(model):
                print(
                    "[Pipeline]: Draft hid distinct hands as both hands. "
                    f"Using the model: '{model}'"
                )
                return model
            print(
                f"[Pipeline]: Model added extra actions. Keeping Atlas draft: '{draft}'"
            )
            return draft
        chosen = reconcile_with_draft(model, draft)
        if is_generic_placeholder_label(chosen):
            return draft
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


def _build_client() -> openai.OpenAI:
    return openai.OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=_api_key(),
        default_headers=OPENROUTER_HEADERS,
    )


client = _build_client()

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
    cleaned = COMMA_AND_PATTERN.sub(",", cleaned)
    cleaned = SLASH_PATTERN.sub(", ", cleaned)
    cleaned = SEMICOLON_PATTERN.sub(", ", cleaned)
    cleaned = _fix_plural_only_tools(cleaned)
    cleaned = _drop_mixed_no_action(cleaned)
    cleaned = _strip_narrative_words(cleaned)
    cleaned = " ".join(cleaned.split())
    cleaned = cleaned.strip(" ,")
    cleaned = _fill_with_visible_substance(cleaned)
    cleaned = _collapse_redundant_hold(cleaned)
    cleaned = _strip_instrumental_pickup(cleaned)
    cleaned = _strip_micro_movements(cleaned)
    cleaned = _finish_incomplete_hands(cleaned)
    cleaned = _split_false_both_hands(cleaned)
    cleaned = _name_wipe_cloth(cleaned)
    cleaned = _ensure_offhand_hold_for_dish_wipe(cleaned)
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
        r"set|lower|raise|carry|drag|flip|spread|smooth|stack|unstack|water|gather|trim|unfold)\b",
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
) -> list[dict]:
    """Build the vision prompt. Atlas drafts are never included — models copy them."""
    total = len(base64_frames)
    intro = (
        "These frames are sampled while the clip plays at normal speed "
        "(laundry, cooking, dishes, grooming, assembly, crafts). "
        "Always output an Atlas label. Never refuse. Never explain. "
        "LEFT side of each image = LEFT hand. RIGHT side = RIGHT hand. Do not mirror. "
        "Ask: is this ONE continuous action with a tool, or TWO distinct goals? "
        "If the first frame already has the object in the hand, do not write pick up. "
        "If they grab a tool only to use it immediately, omit pick up. "
        "Do not add hold for an empty hand or for the same tool already named. "
        "Do add hold when one hand stabilizes (paper) while the other works (scissors). "
        "Do not split cut/wipe/dig/water/write/trim into micro shift/align clauses. "
        "Max 3 clauses. Never write tool/then/next/other. Never write bare animal. "
        "Name the object you see in THESE frames (plate, cloth, hose, toy, plant, etc.). "
        "Do not reuse an example from the instructions if it is not in the pictures. "
        "If an object changes hands, write pass [object] from [hand] to [hand]. "
        "Hands holding or using an object is an action even if the stills look similar. "
        "both hands ONLY if both hands do the same job. "
        "If left holds a plate and right wipes with a cloth, write: "
        "hold glass plate with left hand, wipe glass plate with cloth in right hand. "
        "Never write wipe plate with both hands for that scene. A clear dish is glass plate, not bowl. "
        "Do NOT output No Action if either hand holds an object or a tool. "
        "Never copy a gold example (dough, hose, wrench, scissors) unless it is in the pictures. "
        "Output only the raw label."
    )
    if insist_action:
        intro = (
            "These frames show first-person HAND WORK. Do not output No Action. "
            "Name the object you actually see in the pictures. "
            "If one hand holds a plate and the other wipes with a cloth, write two clauses "
            "with left hand and right hand. Do not write both hands for that. "
            "A clear dish is glass plate, not bowl. "
            "Do not write stuffed animal, scissors, dough, hose, or any example unless it is visible. "
            "LEFT side of each image = LEFT hand. RIGHT side = RIGHT hand. "
            "Atlas syntax: verb + object + with [hand]. Never refuse. Never explain. "
            "Output only the raw label."
        )
    user_content: list[dict] = [{"type": "text", "text": intro}]
    if duration_seconds is not None:
        user_content[0]["text"] += f" This window is {duration_seconds:.1f} seconds long."
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
            caption = f"Frame {index + 1}/{total} START{stamp} — LEFT hand and RIGHT hand separately."
        elif index + 1 == total:
            caption = f"Frame {index + 1}/{total} END{stamp} — LEFT hand and RIGHT hand, what changed."
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
            cleaned = apply_context_fixes(cleaned, draft_label, previous_label)
            print(f"[Pipeline]: Vision model: '{cleaned}'")
            if cleaned == "No Action":
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
            if draft_label and not model_fits_draft(cleaned, draft_label):
                if frames_have_video:
                    print(
                        f"[OpenRouter]: {model} named different objects than the row text "
                        f"({cleaned!r} vs {draft_label!r}). Frames look real, using the model."
                    )
                    return cleaned
                saw_wrong_scene = True
                print(
                    f"[OpenRouter]: {model} named different objects than the Atlas draft "
                    f"({cleaned!r} vs {draft_label!r}). Trying next model..."
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
        print(
            "[Pipeline]: Models did not match the scene. Keeping Atlas draft: "
            f"'{kept_draft}'"
        )
        return apply_context_fixes(
            sanitize_label(kept_draft), draft_label, previous_label
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
) -> str:
    """Sends encoded frame images to OpenRouter VLMs with sequential fallbacks."""
    if not _api_key():
        print("[API Error]: OPENROUTER_API_KEY is missing. Returning 'No Action'.")
        return "No Action"

    draft_label = usable_draft(draft_label)
    previous_label = usable_draft(previous_label)

    base64_frames, frame_timestamps = _subsample_frames(
        base64_frames, frame_timestamps, max_frames=5
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
    )
    system = ACTION_SYSTEM_PROMPT if frames_have_video else SYSTEM_PROMPT
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]
    label = _query_vision_models(
        messages,
        draft_label,
        previous_label,
        list(VISION_MODELS),
        frames_have_video=frames_have_video,
    )
    if label == "No Action" and not draft_label:
        print(
            "[Pipeline]: All models said No Action and there is no usable Atlas draft."
        )
    return choose_final_label(
        label, draft_label, previous_label, frames_have_video=frames_have_video
    )


if __name__ == "__main__":
    test_raw = "picking up 2 spoons and inspect handle."
    print("Raw Input: ", test_raw)
    print("Sanitized Output:", sanitize_label(test_raw))
