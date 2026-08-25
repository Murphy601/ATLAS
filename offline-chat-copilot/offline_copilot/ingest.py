"""Turn a scrolled chat history into logbook fields. Client text only for bio facts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .cities import CITY_STOPWORDS, US_CITIES, US_STATES
from .location import validate_city
from .parser import parse_message

LIVE_IN_RE = re.compile(
    r"\b(?:i(?:'m| am)?\s+(?:from|in)|i live(?:\s+in)?|i stay(?:\s+in)?)\s+"
    r"(?!the\b|a\b|an\b|bed\b|love\b|fact\b)"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b",
    re.I,
)
NAME_RE = re.compile(r"\b(?:my name is|i'm|i am)\s+([A-Z][a-z]{2,15})\b", re.I)
NAME_STOP = frozenset(
    {
        "from",
        "just",
        "really",
        "very",
        "into",
        "here",
        "there",
        "good",
        "fine",
        "doing",
        "watching",
        "living",
        "working",
    }
)
INTEREST_RULES = (
    ("Sports", re.compile(r"\b(?:sports?|ufc|nfl|mlb|nba|baseball|football|fight\s*night)\b", re.I)),
    ("Music", re.compile(r"\b(?:music|concert|band|playlist|guitar|karaoke)\b", re.I)),
    ("Cars", re.compile(r"\b(?:car|chevy|ford|mustang|truck|garage)\b", re.I)),
    ("Food", re.compile(r"\b(?:cook|grilling|bbq|baking|recipe)\b", re.I)),
    ("Outdoors", re.compile(r"\b(?:fishing|hiking|camping|hunting)\b", re.I)),
    ("Gaming", re.compile(r"\b(?:xbox|playstation|pc gaming|video games?)\b", re.I)),
    ("Travel", re.compile(r"\b(?:travel|solo travel|walking city|visited)\b", re.I)),
)

# Places for the customer logbook only — not used as the persona location city.
LOGBOOK_PLACES = frozenset(
    {
        "florence",
        "rome",
        "milan",
        "venice",
        "naples",
        "italy",
        "germany",
        "berlin",
        "munich",
        "frankfurt",
        "thailand",
        "bangkok",
        "phuket",
        "china",
        "beijing",
        "shanghai",
        "japan",
        "tokyo",
        "osaka",
        "france",
        "paris",
        "spain",
        "madrid",
        "barcelona",
        "mexico",
        "canada",
        "england",
        "london",
        "uk",
        "australia",
        "sydney",
        "india",
        "brazil",
        "vietnam",
        "korea",
        "seoul",
        "ireland",
        "scotland",
        "portugal",
        "greece",
        "athens",
        "hendersonville",
        "richmond",
        "southeast asia",
        "se asia",
        "asia",
        "europe",
    }
)
PLACE_SPECIAL = {
    "se asia": "SE Asia",
    "southeast asia": "Southeast Asia",
    "uk": "UK",
}
JUNK_FACT_SNIPPETS = (
    "thinking back to what you said",
    "keep thinking back to you mentioning",
    "minutes outside of",
    "your message is too short",
    "type your reply",
    "waiting for conversation",
    "profile details",
    "add new log",
    "memory usage",
    "action required",
    "i am here is because",
    "chat is claimed",
    "create the log",
    "how do you usually like to unwind",
    "favorite way to spend a sunday",
)
FAVE_RE = re.compile(
    r"\b(?:my\s+)?(?:fave|fav|favorite|favourite)\s+(?:place|city|spot|thing|food|hobby)?\s*(?:is|was|:)?\s*([^.]{3,70})",
    re.I,
)
LIKE_LINE_RE = re.compile(r"\bI\s+(?:like|love|enjoy|prefer)\s+([^.]{3,70})", re.I)
WORK_IN_RE = re.compile(r"\bworkdays were in\s+([^.]{3,50})", re.I)
TRAVELED_RE = re.compile(
    r"\b(?:traveled|travelled|often traveled|often travelled)\s+to\s+([^.]{3,80})",
    re.I,
)
IMPORTANT_RE = re.compile(
    r"\b(?:travel|visited|florence|italy|germany|thailand|china|asia|fave|favorite|favourite|"
    r"widow|retired|workdays|cane|walker|friendship|walking city|live in|i live|"
    r"from [A-Z]|solo travel|like|love|enjoy)\b",
    re.I,
)

_CITIES_LONGEST = tuple(sorted(US_CITIES, key=len, reverse=True))


@dataclass
class HistoryMessage:
    sender: str
    text: str

    @property
    def is_client(self) -> bool:
        return (self.sender or "").strip().casefold() in {"client", "user", "customer", "target"}

    @property
    def is_operator(self) -> bool:
        return (self.sender or "").strip().casefold() in {"operator", "persona", "me", "moderator"}


@dataclass
class IngestResult:
    client_name: str = ""
    client_city: str = ""
    city_confidence: str = "none"
    interests: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    likes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    last_client_message: str = ""
    client_messages: list[str] = field(default_factory=list)
    operator_messages: list[str] = field(default_factory=list)
    operator_questions: list[str] = field(default_factory=list)
    save_logbook: bool = False
    save_reason: str = "nothing high-confidence to save"

    def to_fields(self, persona_city: str = "") -> dict[str, str]:
        return {
            "clientName": self.client_name,
            "clientCity": self.client_city,
            "clientInterests": ", ".join(self.interests),
            "clientPlaces": ", ".join(self.places),
            "clientLikes": ", ".join(self.likes),
            "clientNotes": "; ".join(self.notes[:8]),
            "clientFacts": "; ".join(self.facts[:8]),
            "personaCity": persona_city,
        }

    @property
    def city(self) -> str:
        return self.client_city


_CLAIMED_TOKEN_RE = re.compile(r"[a-z]+")


def _status_is_claimed(status: str) -> bool:
    tokens = _CLAIMED_TOKEN_RE.findall((status or "").casefold())
    return "claimed" in tokens and "unclaimed" not in tokens


def claim_rising_edge(previous_status: str, current_status: str) -> bool:
    """Fire once when a chat becomes claimed. 'Unclaimed' is not claimed."""
    return _status_is_claimed(current_status) and not _status_is_claimed(previous_status)


def _normalize_sender(sender: str) -> str:
    n = (sender or "").strip().casefold()
    if n in {"client", "user", "customer", "target"}:
        return "client"
    if n in {"operator", "persona", "me", "moderator"}:
        return "operator"
    return n or "unknown"


def _as_messages(history: list[HistoryMessage] | list[dict] | list[tuple[str, str]]) -> list[HistoryMessage]:
    out: list[HistoryMessage] = []
    for item in history or []:
        if isinstance(item, HistoryMessage):
            out.append(item)
            continue
        if isinstance(item, dict):
            out.append(
                HistoryMessage(
                    sender=_normalize_sender(str(item.get("sender") or "")),
                    text=str(item.get("text") or "").strip(),
                )
            )
            continue
        sender, text = item
        out.append(HistoryMessage(sender=_normalize_sender(str(sender)), text=str(text).strip()))
    return [row for row in out if row.text]


def _display_city(folded: str) -> str:
    return " ".join(part.capitalize() for part in folded.split())


def _cities_from_text(text: str) -> list[str]:
    """Only real cities. 'from Monday' / 'from Texas' / parks do not count."""
    blob = text or ""
    found: list[str] = []
    seen: set[str] = set()
    for match in LIVE_IN_RE.finditer(blob):
        candidate = match.group(1).strip()
        folded = candidate.casefold()
        if folded in CITY_STOPWORDS:
            continue
        if folded in US_STATES and folded not in US_CITIES:
            continue
        ok, cleaned = validate_city(candidate)
        if not ok:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        found.append(cleaned)
    for city in _CITIES_LONGEST:
        if city in seen:
            continue
        if not re.search(rf"\b{re.escape(city)}\b", blob, flags=re.I):
            continue
        if city in US_STATES and city not in US_CITIES:
            continue
        seen.add(city)
        found.append(_display_city(city))
    return found


def extract_cities(source: str | list) -> list[str]:
    """Cities from free text or from client turns in a history list."""
    if isinstance(source, str):
        return _cities_from_text(source)
    found: list[str] = []
    seen: set[str] = set()
    for row in _as_messages(source):
        if not row.is_client:
            continue
        for city in _cities_from_text(row.text):
            key = city.casefold()
            if key in seen:
                continue
            seen.add(key)
            found.append(city)
    return found


def extract_name(text: str) -> str | None:
    match = NAME_RE.search(text or "")
    if not match:
        return None
    name = match.group(1).strip()
    if name.casefold() in NAME_STOP or name.casefold() in CITY_STOPWORDS:
        return None
    return name


def extract_interests(source: str | list) -> list[str]:
    if isinstance(source, str):
        blob = source
    else:
        blob = " ".join(row.text for row in _as_messages(source) if row.is_client)
    out: list[str] = []
    for label, rule in INTEREST_RULES:
        if rule.search(blob or "") and label not in out:
            out.append(label)
    return out


def is_junk_client_text(text: str) -> bool:
    lowered = (text or "").casefold()
    return any(snippet in lowered for snippet in JUNK_FACT_SNIPPETS)


def _title_place(place: str) -> str:
    key = (place or "").casefold().strip()
    if key in PLACE_SPECIAL:
        return PLACE_SPECIAL[key]
    return " ".join(part.capitalize() for part in key.split())


def _clip_detail(text: str, limit: int = 140) -> str:
    value = " ".join((text or "").split())
    if len(value) > limit:
        return value[: limit - 3].rstrip() + "..."
    return value


def extract_places_for_log(text: str) -> list[str]:
    """Client places for the logbook. Includes travel cities/countries, not just US towns."""
    blob = text or ""
    found: list[str] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        cleaned = " ".join((label or "").split()).strip(" .,;:")
        if not cleaned:
            return
        key = cleaned.casefold()
        if key in seen or key in {"the", "and", "countries like"}:
            return
        seen.add(key)
        found.append(cleaned)

    pairs: list[str] = []
    pair_parts: set[str] = set()
    for match in re.finditer(r"\b([A-Z][a-z]{2,16}),\s*([A-Z][a-z]{2,16})\b", blob):
        pair = f"{match.group(1)}, {match.group(2)}"
        pairs.append(pair)
        pair_parts.add(match.group(1).casefold())
        pair_parts.add(match.group(2).casefold())
    for pair in pairs:
        add(pair)
    for city in _cities_from_text(blob):
        if city.casefold() not in pair_parts:
            add(city)
    for place in sorted(LOGBOOK_PLACES, key=len, reverse=True):
        if place in pair_parts:
            continue
        if not re.search(rf"\b{re.escape(place)}\b", blob, flags=re.I):
            continue
        add(_title_place(place))
    return found


def extract_likes(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        cleaned = _clip_detail(label, 80).strip(" .,;:")
        if len(cleaned) < 3:
            return
        key = cleaned.casefold()
        if key in seen:
            return
        if any(snippet in key for snippet in JUNK_FACT_SNIPPETS):
            return
        seen.add(key)
        out.append(cleaned)

    if re.search(r"\bsolo travel\b", text or "", flags=re.I):
        add("solo travel")
    if re.search(r"\bwalking city\b", text or "", flags=re.I):
        add("walking cities")
    for match in FAVE_RE.finditer(text or ""):
        add(match.group(1))
    for match in LIKE_LINE_RE.finditer(text or ""):
        add(match.group(1))
    return out


def extract_notes(text: str) -> list[str]:
    if is_junk_client_text(text) or not IMPORTANT_RE.search(text or ""):
        return []
    notes: list[str] = []
    for match in WORK_IN_RE.finditer(text or ""):
        notes.append("Worked in " + _clip_detail(match.group(1), 60))
    for match in TRAVELED_RE.finditer(text or ""):
        notes.append("Traveled to " + _clip_detail(match.group(1), 80))
    if re.search(r"\bwidow(?:ed)?\b", text or "", flags=re.I):
        notes.append("Widow")
    if re.search(r"\b(?:cane|walker)\b", text or "", flags=re.I):
        notes.append("Uses a cane/walker")
    if re.search(r"\bfriendship\b", text or "", flags=re.I) and re.search(r"\bsex\b", text or "", flags=re.I):
        notes.append("Here for sex but open to friendship")
    if not notes:
        notes.append(_clip_detail(text, 140))
    return notes


def _uniq(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = " ".join((item or "").split()).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(" ".join(item.split()))
    return out


def _pick_last_client_message(messages: list[str]) -> str:
    if not messages:
        return ""
    for text in reversed(messages):
        if len(text) >= 12:
            return text
    return messages[-1]


def ingest_history(
    history: list[HistoryMessage] | list[dict] | list[tuple[str, str]],
    *,
    header_name: str = "",
    header_city: str = "",
) -> IngestResult:
    rows = _as_messages(history)
    result = IngestResult()
    result.client_name = (header_name or "").strip().split()[0] if header_name.strip() else ""
    for row in rows:
        if row.is_client:
            result.client_messages.append(row.text)
            parsed = parse_message(row.text)
            if len(row.text) >= 12 and not is_junk_client_text(row.text):
                result.facts.extend(parsed.story_bits)
                result.places.extend(extract_places_for_log(row.text))
                result.likes.extend(extract_likes(row.text))
                result.notes.extend(extract_notes(row.text))
            for interest in extract_interests(row.text):
                if interest not in result.interests:
                    result.interests.append(interest)
            if not result.client_name:
                guessed = extract_name(row.text)
                if guessed:
                    result.client_name = guessed
            cities = extract_cities(row.text)
            if cities and result.city_confidence != "high":
                result.client_city = cities[0]
                result.city_confidence = "high"
        elif row.is_operator:
            result.operator_messages.append(row.text)
            if "?" in row.text:
                result.operator_questions.append(row.text.strip())
    if header_city.strip() and not result.client_city:
        ok, cleaned = validate_city(header_city)
        if ok:
            result.client_city = cleaned
            result.city_confidence = "high"
    result.last_client_message = _pick_last_client_message(result.client_messages)
    result.places = _uniq(result.places)
    result.likes = _uniq(result.likes)
    result.notes = _uniq(result.notes)
    # Dedupe facts; keep places/likes/notes first so drafts and the logbook stay useful.
    seen_facts: set[str] = set()
    unique_facts: list[str] = []
    for fact in [*result.places, *result.likes, *result.notes, *result.facts]:
        text = " ".join(str(fact).split())
        key = text.casefold()
        if not text or key in seen_facts or is_junk_client_text(text):
            continue
        seen_facts.add(key)
        unique_facts.append(text)
    result.facts = unique_facts
    if (
        result.city_confidence == "high"
        or result.facts
        or result.interests
        or result.places
        or result.likes
        or result.notes
    ):
        result.save_logbook = True
        result.save_reason = "validated city, places, likes, or first-person facts"
    return result
