"""Hard-coded outgoing and incoming policy checks. No LLM."""

from __future__ import annotations

import re

from .cities import NOT_A_CITY_MARKERS, TIMEZONE_CODES, TIMEZONE_MARKERS
from .location import MIN_MINUTES, MAX_MINUTES, has_travel_window, looks_like_street_address

BANNED_BODY_PHRASES = (
    "my dick",
    "my penis",
    "my cock",
    "your dick is mine",
    "i own your",
    "come over",
    "come thru",
    "come through",
    "come by my",
    "come to my place",
    "come to my house",
    "pull up",
    "meet up",
    "meetup",
    "let's meet",
    "lets meet",
    "we should meet",
    "i'll meet you",
    "ill meet you",
    "meet me at",
    "go on a date",
    "take you on a date",
    "when can we meet",
    "what time should we meet",
    "see you tonight",
    "see you tomorrow",
    "at your place",
    "at my place",
    "my house",
    "your house",
    "i'm a moderator",
    "im a moderator",
    "paid moderator",
    "i get paid to chat",
    "i'm paid to",
    "im paid to",
    "send me money",
    "venmo",
    "cashapp",
    "cash app",
    "paypal",
    "zelle",
    "wire me",
)

ILLEGAL_TOPIC_RE = re.compile(
    r"\b("
    r"pedophil(?:e|ia)|child\s*porn|csam|underage\s*sex|sexual(?:ly)?\s*(?:with\s*)?(?:a\s*)?minor|"
    r"bestiality|zoophilia|rape(?:d|s)?|raping|incest|"
    r"suicid(?:e|al)|kill\s+my(?:self)|self[\s-]?harm|"
    r"cocaine|heroin|meth(?:amphetamine)?|fentanyl|how to cook meth|"
    r"murder(?:ing)?|shoot (?:him|her|them)|stab (?:him|her|them)"
    r")\b",
    flags=re.I,
)

MINOR_AGE_RE = re.compile(
    r"\b(?:[1-9]|1[0-7])\s*(?:year|yr)s?\s*old\b|"
    r"\b(?:under|not quite|almost)\s*(?:18|eighteen)\b|"
    r"\b(?:little (?:girl|boy)|schoolgirl|schoolboy)\b",
    flags=re.I,
)

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", flags=re.I)
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.-]*)?(?:\(?\d{3}\)?[\s.-]*)\d{3}[\s.-]*\d{4}(?!\d)"
)
HANDLE_SHARE_RE = re.compile(
    r"\b(?:snap(?:chat)?|telegram|whatsapp|kik|discord|instagram|imessage)\s*(?:me|:|is)\b",
    flags=re.I,
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _lower(text: str) -> str:
    return _normalize(text).casefold()


def incoming_is_illegal(text: str) -> bool:
    blob = text or ""
    return bool(ILLEGAL_TOPIC_RE.search(blob) or MINOR_AGE_RE.search(blob))


def validate_incoming(text: str) -> tuple[bool, str]:
    """True when the operator may draft a normal reply."""
    blob = text or ""
    if incoming_is_illegal(blob):
        return False, "Incoming message hits an illegal topic. Do not engage. Do not continue the subject."
    return True, "ok"


def _timezone_used_as_location(text: str) -> bool:
    n = _lower(text)
    if any(marker in n for marker in TIMEZONE_MARKERS):
        return True
    return bool(re.search(r"\b(" + "|".join(TIMEZONE_CODES) + r")\b", n))


def _non_city_place(text: str) -> bool:
    n = _lower(text)
    return any(marker in n for marker in NOT_A_CITY_MARKERS)


def validate_draft(
    text: str,
    *,
    client_name: str = "",
    client_city: str = "",
    location_required: bool = False,
) -> tuple[bool, str]:
    """Deterministic outgoing policy check. Fail closed."""
    raw = _normalize(text)
    if not raw:
        return False, "Empty draft"
    n = raw.casefold()

    if ILLEGAL_TOPIC_RE.search(raw) or MINOR_AGE_RE.search(raw):
        return False, "Illegal topic in outgoing draft"
    for phrase in BANNED_BODY_PHRASES:
        if phrase in n:
            return False, f"Banned phrase: {phrase}"
    if EMAIL_RE.search(raw):
        return False, "Looks like an email address"
    if PHONE_RE.search(raw):
        return False, "Looks like a phone number"
    if HANDLE_SHARE_RE.search(raw):
        return False, "Shares off-platform contact"
    if looks_like_street_address(raw):
        return False, "Looks like a street address"
    if _timezone_used_as_location(raw) and not has_travel_window(raw):
        return False, "Time zone used instead of a city"
    if location_required:
        if not client_city.strip():
            return False, "Location was asked but no client city was supplied"
        if client_city.strip().casefold() not in n:
            return False, "Location answer is missing the client city"
        if not has_travel_window(raw):
            return False, f"Location must sit in a {MIN_MINUTES}–{MAX_MINUTES} minute window"
        if _non_city_place(raw):
            return False, "Location names a park/restaurant/place instead of a city"
        if _timezone_used_as_location(raw):
            return False, "Time zone used instead of a city"
    if client_name.strip():
        first = client_name.strip().split()[0]
        # Catch a different given name we might have interpolated.
        other = re.findall(r"\b[A-Z][a-z]{2,}\b", raw)
        blocked = {"i", "i've", "i'm"}
        for token in other:
            if token.casefold() in blocked:
                continue
            if token.casefold() == first.casefold():
                continue
            if token in {
                "UFC",
                "MLB",
                "NFL",
                "Sunday",
                "Saturday",
                "Monday",
                "Friday",
                "August",
            }:
                continue
            # Common sentence starts are fine; only flag if it looks like addressing someone else.
            if re.search(rf"\bhey {token}\b", raw, flags=re.I) and token.casefold() != first.casefold():
                return False, f"Wrong name: {token}"

    questions = raw.count("?")
    if questions != 1:
        return False, f"Must contain exactly 1 question mark CTA (found {questions})"
    if not raw.endswith("?"):
        return False, "CTA must be the final sentence"
    return True, "Passed"
