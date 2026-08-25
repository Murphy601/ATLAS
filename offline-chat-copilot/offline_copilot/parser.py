"""Regex intent parser. Answers every asked question, not just the first match."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


LOCATION_RE = re.compile(
    r"\b(?:where\s+(?:do\s+you\s+live|are\s+you(?:\s+from|\s+located)?|you\s+from)|"
    r"what\s+city|what\s+town|your\s+location|you\s+located)\b",
    flags=re.I,
)
ACTIVITY_RE = re.compile(
    r"\b(?:what(?:'s| is)?\s+up|what\s+are\s+you\s+(?:doing|up\s+to)|"
    r"you\s+busy|any\s+plans|what\s+you\s+doing)\b",
    flags=re.I,
)
SPORTS_RE = re.compile(
    r"\b(?:sports?|ufc|nfl|mlb|nba|baseball|football|fight\s*night|the\s+game|any\s+games?)\b",
    flags=re.I,
)
MEETUP_RE = re.compile(
    r"\b(?:come\s+over|meet\s+up|meet\s+me|go\s+on\s+a\s+date|when\s+can\s+we\s+meet|"
    r"what\s+time\s+should\s+we|come\s+to\s+my|pull\s+up|see\s+you\s+(?:tonight|tomorrow))\b",
    flags=re.I,
)
DATING_RE = re.compile(
    r"\b(?:be\s+my\s+(?:gf|bf|girlfriend|boyfriend)|wanna\s+date|will\s+you\s+date|"
    r"are\s+we\s+dating|boyfriend|girlfriend)\b",
    flags=re.I,
)
INTIMATE_RE = re.compile(
    r"\b(?:cock|clit|pussy|g-?spot|nipples?|balls?|suck(?:ing)?|kiss(?:ing)?|"
    r"on top of me|in your mouth|blowjob|oral|horny|fuck|tease my|wet clit|"
    r"come hither|medical students?)\b",
    flags=re.I,
)


@dataclass
class ParsedMessage:
    text: str
    questions: list[str] = field(default_factory=list)
    asked_location: bool = False
    asked_activity: bool = False
    asked_sports: bool = False
    asked_intimate: bool = False
    meetup_request: bool = False
    dating_request: bool = False
    story_bits: list[str] = field(default_factory=list)

    @property
    def asked_anything(self) -> bool:
        return bool(self.questions or self.asked_location or self.asked_activity or self.asked_sports)


def _question_clauses(text: str) -> list[str]:
    bits: list[str] = []
    for chunk in re.split(r"(?<=[?])\s+", text or ""):
        chunk = chunk.strip()
        if "?" in chunk:
            bits.append(chunk)
    return bits


def parse_message(user_message: str) -> ParsedMessage:
    text = (user_message or "").strip()
    parsed = ParsedMessage(text=text, questions=_question_clauses(text))
    parsed.asked_location = bool(LOCATION_RE.search(text))
    parsed.asked_activity = bool(ACTIVITY_RE.search(text))
    parsed.asked_sports = bool(SPORTS_RE.search(text))
    parsed.meetup_request = bool(MEETUP_RE.search(text))
    parsed.dating_request = bool(DATING_RE.search(text))
    parsed.asked_intimate = bool(INTIMATE_RE.search(text))
    # Keep short first-person notes so drafts can reference them.
    for match in re.finditer(r"\bI(?:'m| am| have| like| love)\s+[^.]{3,80}", text, flags=re.I):
        parsed.story_bits.append(match.group(0).strip())
    return parsed
