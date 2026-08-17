import os
import re

import openai
from dotenv import load_dotenv

from config import (
    ARTICLE_PATTERN,
    COMMA_AND_PATTERN,
    DIGIT_PATTERN,
    FILL_SOURCE_TOOLS,
    FORBIDDEN_WORDS,
    GENERIC_NOUNS,
    HAND_PATTERN,
    LOOKING_VERBS,
    NAMED_IMPLEMENTS,
    NARRATIVE_WORDS,
    NUMBER_MAP,
    OPENROUTER_BASE_URL,
    OPENROUTER_HEADERS,
    OPENROUTER_MAX_ROUTE_FALLBACKS,
    PLURAL_ONLY_TOOLS,
    SEMICOLON_PATTERN,
    SLASH_PATTERN,
    SYSTEM_PROMPT,
    TEMPERATURE,
    TRANSFER_VERBS,
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
    r"put|grab|hand|gather)\b",
    re.IGNORECASE,
)
HOLD_CLAUSE_PATTERN = re.compile(r"^hold\b", re.IGNORECASE)
TWO_HANDED_TOOLS = ("hose", "rope")
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
    """Swap generic 'tool' for a specific name seen in the draft or prior segment."""
    if not label or label == "No Action":
        return label
    if not GENERIC_NOUN_PATTERN.search(label):
        return label
    specific = _named_implement_in(draft_label, previous_label)
    if not specific:
        return label
    return GENERIC_NOUN_PATTERN.sub(specific, label)


def reconcile_with_draft(model_label: str, draft_label: str | None) -> str:
    """Keep a one-action draft when the model only invented a trailing hold."""
    if not draft_label:
        return model_label
    draft = sanitize_label(draft_label)
    if draft == "No Action":
        return model_label
    model_parts = split_actions(model_label)
    draft_parts = split_actions(draft)
    if (
        len(model_parts) >= 2
        and HOLD_CLAUSE_PATTERN.search(model_parts[-1])
        and len(draft_parts) == len(model_parts)
        and _leading_verb(draft_parts[-1]) == "pick up"
    ):
        return draft
    return model_label


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
        r"set|lower|raise|carry|drag|flip|spread|smooth|stack|unstack|water|gather)\b",
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


def generate_label_from_frames(
    base64_frames: list[str],
    previous_label: str | None = None,
    draft_label: str | None = None,
    duration_seconds: float | None = None,
    frame_timestamps: list[float] | None = None,
) -> str:
    """Sends encoded frame images to OpenRouter VLMs with sequential fallbacks."""
    if not _api_key():
        print("[API Error]: OPENROUTER_API_KEY is missing. Returning 'No Action'.")
        return "No Action"

    total = len(base64_frames)
    user_content: list[dict] = [
        {
            "type": "text",
            "text": (
                "Ego-camera frames from ONE Atlas segment, in time order. "
                "LEFT side of each image = LEFT hand. RIGHT side = RIGHT hand. Do not mirror. "
                "For every frame ask: what is the left hand doing, and what is the right hand doing? "
                "If a hand is gripping or stabilizing an object, that hold MUST appear in the label. "
                "If a hand is empty, do not invent a hold. "
                "both hands only when both grip the SAME tool. "
                "Name the exact object. Never write tool/then/next/other. "
                "If an object changes hands, write pass [object] from [hand] to [hand]. "
                "Do NOT output No Action if either hand holds something. "
                "Output only the raw label or No Action."
            ),
        }
    ]
    for index, frame in enumerate(base64_frames):
        stamp = ""
        if frame_timestamps and index < len(frame_timestamps):
            stamp = f" t={frame_timestamps[index]:.2f}s"
        if index == 0:
            caption = f"Frame {index + 1}/{total} START{stamp} — both hands."
        elif index + 1 == total:
            caption = f"Frame {index + 1}/{total} END{stamp} — both hands, what changed."
        else:
            caption = f"Frame {index + 1}/{total}{stamp}"
        user_content.append({"type": "text", "text": caption})
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{frame}"},
            }
        )
    if duration_seconds is not None:
        user_content[0]["text"] += f" Segment length: {duration_seconds:.1f} seconds."
    if draft_label:
        user_content[0]["text"] += (
            f" Current AI draft to correct (fix hands and missing holds, keep specific object names): "
            f"{draft_label}."
        )
    if previous_label and previous_label != "No Action":
        user_content[0]["text"] += (
            f" Previous segment (keep object names and hand-state consistent): {previous_label}."
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    last_error = None
    for index, model in enumerate(VISION_MODELS):
        try:
            print(f"[OpenRouter]: Trying {model}...")
            route_fallbacks = VISION_MODELS[
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
            print(f"[OpenRouter]: Success with {model}")
            cleaned = sanitize_label(raw_label)
            cleaned = apply_context_fixes(cleaned, draft_label, previous_label)
            if (
                cleaned == "No Action"
                and draft_label
                and draft_label.strip().lower() != "no action"
                and index + 1 < len(VISION_MODELS)
            ):
                print(
                    f"[OpenRouter]: {model} said No Action while a draft describes work. "
                    "Trying next model..."
                )
                continue
            return reconcile_with_draft(cleaned, draft_label)
        except Exception as e:
            last_error = e
            print(f"[Warning] {model} failed: {e}. Trying next fallback...")
            continue

    print(f"[Error] All vision models failed. Last error: {last_error}")
    return "No Action"


if __name__ == "__main__":
    test_raw = "picking up 2 spoons and inspect handle."
    print("Raw Input: ", test_raw)
    print("Sanitized Output:", sanitize_label(test_raw))
