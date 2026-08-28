"""City validation and the 30–60 minute location window."""

from __future__ import annotations

import re

from .cities import CITY_STOPWORDS, NOT_A_CITY_MARKERS, TIMEZONE_CODES, TIMEZONE_MARKERS, US_CITIES, US_STATES

MIN_MINUTES = 30
MAX_MINUTES = 60
WINDOW_MINUTES = (30, 35, 40, 45, 50, 55, 60)

STREET_RE = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9.'-]+(?:\s+[A-Za-z0-9.'-]+)*\s+"
    r"(?:st|street|ave|avenue|rd|road|blvd|boulevard|ln|lane|dr|drive|ct|court|way|hwy|highway)\b",
    flags=re.I,
)
WINDOW_RE = re.compile(
    r"\b(?:about|around|roughly|just about)?\s*"
    r"(?:30|35|40|45|50|55|60)"
    r"(?:\s*(?:to|-)\s*(?:35|40|45|50|55|60))?"
    r"\s*minutes?\b",
    flags=re.I,
)
CITY_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,48}$")


def looks_like_street_address(text: str) -> bool:
    return bool(STREET_RE.search(text or ""))


def has_travel_window(text: str) -> bool:
    return bool(WINDOW_RE.search(text or ""))


def _folded(name: str) -> str:
    n = re.sub(r"\s+", " ", (name or "").strip().casefold())
    n = n.replace("saint ", "st ").replace("saint-", "st ")
    n = n.replace("fort ", "fort ").replace("ft. ", "fort ").replace("ft ", "fort ")
    n = n.replace(".", "")
    return n


def validate_city(name: str) -> tuple[bool, str]:
    """Accept a real city/town. Reject parks, restaurants, streets, and time zones."""
    raw = re.sub(r"\s+", " ", (name or "").strip())
    if not raw:
        return False, "No city was provided"
    n = _folded(raw)
    if n in TIMEZONE_CODES or any(marker in n for marker in TIMEZONE_MARKERS):
        return False, "That is a time zone, not a city"
    if looks_like_street_address(raw):
        return False, "That looks like a street address"
    if n in CITY_STOPWORDS:
        return False, "That is not a city or town"
    if n in US_STATES and n not in US_CITIES:
        return False, "That is a state, not a city"
    if n in US_CITIES:
        return True, raw
    if any(marker in n for marker in NOT_A_CITY_MARKERS):
        return False, "That is not a city or town"
    if not CITY_NAME_RE.match(raw) or any(ch.isdigit() for ch in raw):
        return False, "Not a valid city or town name"
    return True, raw


def location_sentence(city: str, minutes: int) -> str:
    ok, cleaned = validate_city(city)
    if not ok:
        raise ValueError(cleaned)
    mins = int(minutes)
    if mins not in WINDOW_MINUTES:
        raise ValueError(f"Minutes must be in {WINDOW_MINUTES}")
    display = cleaned
    return f"I'm about {mins} minutes outside of {display}."
