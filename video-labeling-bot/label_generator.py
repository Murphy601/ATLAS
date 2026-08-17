import os
import re

import openai
from dotenv import load_dotenv

from config import (
    DIGIT_PATTERN,
    FORBIDDEN_WORDS,
    NUMBER_MAP,
    OPENROUTER_BASE_URL,
    OPENROUTER_HEADERS,
    SYSTEM_PROMPT,
    TEMPERATURE,
    VERB_CORRECTIONS,
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


def sanitize_label(text: str) -> str:
    """Cleans and validates generated labels against strict formatting constraints."""
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

    # 3. Convert continuous verbs to imperative forms
    for continuous, imperative in VERB_CORRECTIONS.items():
        pattern = re.compile(rf"\b{continuous}\b", re.IGNORECASE)
        cleaned = pattern.sub(imperative, cleaned)

    # 4. Filter or replace forbidden terms
    for word in FORBIDDEN_WORDS:
        pattern = re.compile(rf"\b{word}\b", re.IGNORECASE)
        if pattern.search(cleaned):
            if word in ["inspect", "check", "examine"]:
                cleaned = pattern.sub("adjust", cleaned)
            elif word == "reach":
                cleaned = pattern.sub("move to", cleaned)
            elif word in ["touch", "touching"]:
                cleaned = pattern.sub("grab", cleaned)
            elif word == "holding":
                cleaned = pattern.sub("hold", cleaned)
            elif word == "picking":
                cleaned = pattern.sub("pick", cleaned)
            elif word == "placing":
                cleaned = pattern.sub("place", cleaned)

    # 5. Normalize whitespace
    cleaned = " ".join(cleaned.split())
    return cleaned


def generate_label_from_frames(base64_frames: list[str]) -> str:
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

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Analyze these video keyframes and output the exact action label.",
                },
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
