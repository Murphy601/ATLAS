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
    r"what\s+time\s+should\s+we|come\s+to\s+my|pull\s+up|"
    r"see\s+you\s+(?:tonight|tomorrow)|want\s+to\s+see\s+you|"
    r"are\s+you\s+home|give\s+me\s+your\s+address|send\s+(?:me\s+)?your\s+address|"
    r"what(?:'s| is)\s+your\s+address|your\s+address|"
    r"i\s+want\s+to\s+see\s+you|come\s+see\s+me)\b",
    flags=re.I,
)
DATING_RE = re.compile(
    r"\b(?:be\s+my\s+(?:gf|bf|girlfriend|boyfriend)|wanna\s+date|will\s+you\s+date|"
    r"are\s+we\s+dating|boyfriend|girlfriend)\b",
    flags=re.I,
)
INTIMATE_RE = re.compile(
    r"\b(?:cock|dick|clit|pussy|g-?spot|nipples?|tits?|breast|balls?|"
    r"suck(?:ing)?|lick(?:ing)?|kiss(?:ing)?|taste(?: of it)?|"
    r"on top of me|in your mouth|blowjob|blow\s+job|oral|horny|fuck|"
    r"tease my|wet clit|come hither|medical students?|nude|naked)\b",
    flags=re.I,
)
VALIDATION_RE = re.compile(
    r"\b(?:making sense|can trust|feel secure|sense of clarity|feel safe|"
    r"do i make sense|am i making sense)\b",
    flags=re.I,
)
MARRIED_RE = re.compile(
    r"\b(?:you\s+are\s+married|you're\s+married|yet\s+you\s+are\s+married|"
    r"get\s+attached|if\s+we\s+get\s+attached|attached,?\s+and\s+yet)\b",
    flags=re.I,
)
ROMANCE_RE = re.compile(
    r"\b(?:romantic\s+dinners?|being\s+romantic|like\s+being\s+romantic|"
    r"fan\s+of\s+romantic)\b",
    flags=re.I,
)
HELP_OFFER_RE = re.compile(
    r"\b(?:i\s+can\s+help\s+you|let\s+me\s+help|we\s+can\s+figure\s+something\s+out)\b",
    flags=re.I,
)
WORK_SHIFT_RE = re.compile(
    r"\b(?:waiting\s+tables|work(?:ing)?\s+tonight|shift\s+tonight)\b",
    flags=re.I,
)
# Tiny "Really?" / "Sure?" should not steal the open-question path.
RHETORICAL_QUESTION_RE = re.compile(
    r"^(?:really|sure|yeah|yes|oh|wow|ok|okay|right|huh)\??$",
    flags=re.I,
)
# Chat Home Base stamps. Unicode hyphens (‑ – —) show up in UIA names.
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_WEEKDAY = r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*"
_RELATIVE = (
    r"(?:just now|a few seconds ago|\d+\s+(?:seconds?|minutes?|hours?|days?|weeks?)\s+ago)"
)
_HY = r"[-‑–—]"
TIMESTAMP_RE = re.compile(
    rf"^{_WEEKDAY},?\s+{_MONTH}\.?\s+\d{{1,2}},?\s*\d{{4}}"
    rf"(?:\s*{_HY}\s*.*)?$",
    flags=re.I,
)
# 07-Aug-2026 — 20 days ago
DAY_MONTH_YEAR_STAMP_RE = re.compile(
    rf"^\d{{1,2}}\s*{_HY}\s*{_MONTH}\s*{_HY}\s*\d{{2,4}}"
    rf"(?:\s*{_HY}\s*.*)?$",
    flags=re.I,
)
# Aug 28 (a few seconds ago)   /   Aug 28, 2026
MONTH_DAY_STAMP_RE = re.compile(
    rf"^{_MONTH}\.?\s+\d{{1,2}}(?:\s*,\s*\d{{4}})?"
    rf"(?:\s*(?:{_HY}|\()\s*.*)?$",
    flags=re.I,
)
RELATIVE_STAMP_RE = re.compile(
    rf"^{_RELATIVE}$",
    flags=re.I,
)
# Leftover copilot CTA glued onto a real bubble: "...itg after a long day?"
LEAKED_CTA_TAIL_RE = re.compile(
    r"(?:how do you usually\s[\w\s,'-]{0,80}after\s(?:a\s)?[\w\s]{2,40}\??|"
    r"(?:want me to|should i|does that kind|do you want me)\s[^?]{8,80}\?|"
    r"(?<=\w)g after a (?:long day|quiet evening|free sunday|busy week)\??)\s*$",
    flags=re.I,
)
SELF_DRAFT_PREFIXES = (
    "that actually made me smile",
    "i really like how you said that",
    "you're sweet for putting it that way",
    "i sat with that for a second",
    "that was a lovely thing to hear",
    "i wasn't expecting you to put it like that",
    "thank you for being open with me",
    "i like talking to you like this",
    "i heard your question",
    "yes. i am with you on that",
    "thank you for asking me that",
    "i won't be able to fit that into my schedule",
    "i think that's sweet of you to ask",
    "i've got to process that",
    "i'm flattered by your offer",
    "thinking back to what you said",
    "keep thinking back to you mentioning",
    "turning over what you told me",
    "how do you usually",
    "what's been the highlight of your week",
    "want me to go that slow",
    "should i stay on top of you",
)


@dataclass
class ParsedMessage:
    text: str
    questions: list[str] = field(default_factory=list)
    asked_location: bool = False
    asked_activity: bool = False
    asked_sports: bool = False
    asked_intimate: bool = False
    asked_validation: bool = False
    asked_married: bool = False
    asked_romance: bool = False
    offered_help: bool = False
    mentioned_work: bool = False
    meetup_request: bool = False
    dating_request: bool = False
    story_bits: list[str] = field(default_factory=list)

    @property
    def asked_anything(self) -> bool:
        return bool(
            self.questions
            or self.asked_location
            or self.asked_activity
            or self.asked_sports
            or self.asked_intimate
            or self.asked_validation
            or self.asked_married
            or self.asked_romance
            or self.offered_help
            or self.meetup_request
            or self.dating_request
        )


def _question_clauses(text: str) -> list[str]:
    bits: list[str] = []
    for chunk in re.split(r"(?<=[?])\s+", text or ""):
        chunk = chunk.strip()
        if "?" not in chunk:
            continue
        probe = chunk.rstrip("?!. ").strip()
        if RHETORICAL_QUESTION_RE.match(probe + "?"):
            continue
        words = re.findall(r"[A-Za-z]+", chunk)
        if len(words) <= 1:
            continue
        bits.append(chunk)
    return bits


def parse_message(user_message: str) -> ParsedMessage:
    text = clean_client_line(user_message or "")
    parsed = ParsedMessage(text=text, questions=_question_clauses(text))
    parsed.asked_location = bool(LOCATION_RE.search(text))
    parsed.asked_activity = bool(ACTIVITY_RE.search(text))
    parsed.asked_sports = bool(SPORTS_RE.search(text))
    parsed.meetup_request = bool(MEETUP_RE.search(text))
    parsed.dating_request = bool(DATING_RE.search(text))
    parsed.asked_intimate = bool(INTIMATE_RE.search(text))
    parsed.asked_validation = bool(VALIDATION_RE.search(text))
    parsed.asked_married = bool(MARRIED_RE.search(text))
    parsed.asked_romance = bool(ROMANCE_RE.search(text))
    parsed.offered_help = bool(HELP_OFFER_RE.search(text))
    parsed.mentioned_work = bool(WORK_SHIFT_RE.search(text))
    # Keep short first-person notes so drafts can reference them.
    for match in re.finditer(r"\bI(?:'m| am| have| like| love)\s+[^.]{3,80}", text, flags=re.I):
        parsed.story_bits.append(match.group(0).strip())
    return parsed


def is_timestamp_line(text: str) -> bool:
    blob = " ".join((text or "").split())
    if not blob:
        return False
    # Normalize unicode hyphens so 07‑Aug‑2026 matches.
    compact = blob.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    return bool(
        TIMESTAMP_RE.match(blob)
        or TIMESTAMP_RE.match(compact)
        or DAY_MONTH_YEAR_STAMP_RE.match(blob)
        or DAY_MONTH_YEAR_STAMP_RE.match(compact)
        or MONTH_DAY_STAMP_RE.match(blob)
        or MONTH_DAY_STAMP_RE.match(compact)
        or RELATIVE_STAMP_RE.match(blob)
    )


def is_self_draft_line(text: str) -> bool:
    """True when UIA is reading our own typed draft / CTA, not a customer bubble."""
    blob = " ".join((text or "").split()).casefold()
    if not blob:
        return False
    return any(blob.startswith(prefix) for prefix in SELF_DRAFT_PREFIXES)


def clean_client_line(text: str) -> str:
    """Drop timestamp chrome and leftover copilot CTA glued onto a real bubble."""
    blob = " ".join((text or "").split())
    if not blob:
        return ""
    if is_timestamp_line(blob) or is_self_draft_line(blob):
        return ""
    cleaned = blob
    for _ in range(3):
        nxt = LEAKED_CTA_TAIL_RE.sub("", cleaned).strip(" .")
        if nxt == cleaned:
            break
        cleaned = nxt
    if is_timestamp_line(cleaned) or is_self_draft_line(cleaned):
        return ""
    return cleaned


def describe_intent(parsed: ParsedMessage) -> str:
    """One-line explanation of which rule will write the draft."""
    if parsed.meetup_request or parsed.dating_request:
        return "meetup/dating — deflect, do not accept, never give an address"
    if parsed.asked_validation:
        return "validation — answer the trust / making-sense question"
    if parsed.asked_intimate:
        return "intimate — answer that request"
    if parsed.asked_married:
        return "married/attachment — answer that worry, do not promise a meetup"
    if parsed.asked_romance:
        return "romance — answer the romantic-dinner / being-romantic ask"
    if parsed.offered_help:
        return "help offer — thank them and stay with that offer"
    if parsed.mentioned_work:
        return "work/shift — ack that shift, not a random topic"
    if parsed.asked_location:
        return "location — answer with the 30-60 minute window"
    if parsed.asked_activity:
        return "activity — say what you are doing"
    if parsed.asked_sports:
        return "sports — answer the game/team ask"
    if parsed.questions:
        return "open question — answer the last question in that bubble"
    return "no specific ask — warm ack of that bubble, not a random topic"
