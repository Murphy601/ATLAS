import os
import re

import openai
from dotenv import load_dotenv

from config import (
    ARTICLE_PATTERN,
    COMMA_AND_PATTERN,
    DIGIT_PATTERN,
    FORBIDDEN_WORDS,
    HAND_PATTERN,
    LOOKING_VERBS,
    NUMBER_MAP,
    OPENROUTER_BASE_URL,
    OPENROUTER_HEADERS,
    PLURAL_ONLY_TOOLS,
    SEMICOLON_PATTERN,
    SLASH_PATTERN,
    SYSTEM_PROMPT,
    TEMPERATURE,
    VERB_CORRECTIONS,
    VERB_REPLACEMENTS,
    VISION_MODELS,
)

load_dotenv()


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
        r"set|lower|raise|carry|drag|flip|spread|smooth|stack|unstack)\b",
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
) -> str:
    """Sends encoded frame images to OpenRouter VLMs with sequential fallbacks."""
    if not _api_key():
        print("[API Error]: OPENROUTER_API_KEY is missing. Returning 'No Action'.")
        return "No Action"

    image_contents = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{frame}"},
        }
        for frame in base64_frames
    ]

    instruction = (
        "These are consecutive ego-camera keyframes from ONE existing Atlas segment, "
        "played in order. Label what THE WORKER'S HANDS actually do. "
        "Digging, carrying, picking up buckets or tools, passing, placing, and holding "
        "ARE actions. Output No Action ONLY if hands are idle and touching nothing. "
        "Keep the same segment; do not invent extra segments. "
        "Account for both hands. Output only the raw label or No Action."
    )
    if draft_label:
        instruction += f" Current AI draft to correct: {draft_label}."
    if previous_label and previous_label != "No Action":
        instruction += (
            f" Previous segment label (keep object names and hand-state consistent): "
            f"{previous_label}."
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": instruction},
                *image_contents,
            ],
        },
    ]

    last_error = None
    for index, model in enumerate(VISION_MODELS):
        try:
            print(f"[OpenRouter]: Trying {model}...")
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=TEMPERATURE,
                extra_body={"models": VISION_MODELS[index + 1 :]},
                extra_headers=OPENROUTER_HEADERS,
            )
            raw_label = response.choices[0].message.content
            if not raw_label or not str(raw_label).strip():
                raise ValueError("Empty model response")
            print(f"[OpenRouter]: Success with {model}")
            return sanitize_label(raw_label)
        except Exception as e:
            last_error = e
            print(f"[Warning] {model} failed: {e}. Trying next fallback...")
            continue

    print(f"[Error] All free vision models failed. Last error: {last_error}")
    return "No Action"


if __name__ == "__main__":
    test_raw = "picking up 2 spoons and inspect handle."
    print("Raw Input: ", test_raw)
    print("Sanitized Output:", sanitize_label(test_raw))
