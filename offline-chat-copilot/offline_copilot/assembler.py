"""Assemble Slot A (answer) + Slot B (context) + Slot C (one CTA)."""

from __future__ import annotations

import re
from datetime import date

from .cta import CTA_BANK, CTA_BY_CATEGORY
from .location import WINDOW_MINUTES, location_sentence, validate_city
from .logbook import fingerprint
from .parser import ParsedMessage
from .sports import sports_banter


ACKS = (
    "That actually made me smile. Thank you for sharing that with me.",
    "I really like how you said that. It feels honest and warm.",
    "You're sweet for putting it that way. I feel a little closer to you already.",
    "I sat with that for a second, and I like you even more for telling me.",
    "That was a lovely thing to hear. I'm glad you trusted me with it.",
    "I wasn't expecting you to put it like that, and I kind of love it.",
    "Thank you for being open with me. I don't take that lightly.",
    "I like talking to you like this. It feels easy and a little romantic.",
)
SELF_DRAFT_MARKERS = (
    "thinking back to what you said",
    "keep thinking back to you mentioning",
    "turning over what you told me",
    "like that little detail you shared",
    "like how you put that",
    "i can actually picture that clearly",
    "i am here is because",
)
BAD_FIRST_NAMES = frozenset(
    {
        "unknown",
        "trying",
        "client",
        "user",
        "here",
        "just",
        "this",
        "glad",
        "like",
        "love",
        "actually",
    }
)

ACTIVITY_LINES = (
    "I'm taking it easy at home tonight, catching up a little and thinking about you.",
    "I'm in for the night, winding down with some food nearby and a smile on my face.",
    "I'm keeping the evening low-key, staying in, and honestly enjoying this chat with you.",
)

MEETUP_DEFLECTS = (
    # Acknowledge & redirect — no later-week promise, no extra question (Slot C is the CTA).
    "I won't be able to fit that into my schedule. By the way, I was meaning to ask you something else.",
    # Cool the intensity without talking about dates or meeting up.
    "I think that's sweet of you to ask, but right now isn't the best time for me. That reminds me of something I wanted to ask.",
    # Humor, then shift. No bar/spot invite that sounds like a meetup.
    "I've got to process that. That's a lot to process. I deserve a drink or two after that.",
    # Gratitude and a clean topic change.
    "I'm flattered by your offer, thank you. On a different note, I wanted to get your thoughts on something.",
)
MEETUP_DEFLECT = MEETUP_DEFLECTS[0]
# Chat Home Base refuses drafts under 75 characters ("Your message is too short").
MIN_DRAFT_CHARS = 75
PAD_SENTENCE = " I've been sitting with that, and I really want to hear a little more from you."


def meetup_deflect_line(option_index: int) -> str:
    return MEETUP_DEFLECTS[option_index % len(MEETUP_DEFLECTS)]

FACT_BRIDGES = (
    "I'm thinking back to what you said about {fact}.",
    "I keep thinking back to you mentioning {fact}.",
    "I've been turning over what you told me about {fact}.",
)


def _cta_pool(parsed: ParsedMessage, used: set[str]) -> list[str]:
    if parsed.asked_sports:
        ordered = list(CTA_BY_CATEGORY.get("sports") or ()) + list(CTA_BANK)
    elif parsed.asked_activity:
        ordered = list(CTA_BY_CATEGORY.get("weekend") or ()) + list(CTA_BANK)
    else:
        ordered = list(CTA_BANK)
    out: list[str] = []
    for item in ordered:
        if fingerprint(item) in used:
            continue
        out.append(item)
    return out or list(CTA_BANK)


UK_TO_US = (
    ("favourites", "favorites"),
    ("favourite", "favorite"),
    ("colours", "colors"),
    ("colour", "color"),
    ("honour", "honor"),
    ("travelling", "traveling"),
    ("travelled", "traveled"),
    ("grey", "gray"),
    ("whilst", "while"),
)


def us_english(text: str) -> str:
    """Keep outgoing drafts in US English."""

    def swap(match: re.Match[str], american: str) -> str:
        src = match.group(0)
        if src.isupper():
            return american.upper()
        if src[:1].isupper():
            return american[:1].upper() + american[1:]
        return american

    out = text or ""
    for uk, american in UK_TO_US:
        out = re.sub(rf"\b{uk}\b", lambda match, am=american: swap(match, am), out, flags=re.I)
    return out


def _safe_first_name(name: str) -> str:
    first = (name or "").strip().split()[0] if (name or "").strip() else ""
    if not first:
        return ""
    if first.casefold() in BAD_FIRST_NAMES:
        return ""
    if not first.isalpha() or not first[:1].isupper() or len(first) < 3:
        return ""
    if first.casefold().endswith("ing") and first.casefold() not in {"king"}:
        return ""
    return first


def _looks_broken_grammar(text: str) -> bool:
    lowered = (text or "").casefold()
    if any(marker in lowered for marker in SELF_DRAFT_MARKERS):
        return True
    if re.search(r"\b(?:i am here is|its a great|dont have|you don't have to worry)\b", lowered):
        return True
    return False


def react_to_latest(text: str, ack_index: int) -> str:
    """Answer the newest client line with US English. Do not quote broken history."""
    raw = us_english((text or "").strip())
    lowered = raw.casefold()
    if "florence" in lowered or "italy" in lowered:
        lines = (
            "Florence sounds lovely when you describe it. I can almost picture you walking those old streets, and I like that a lot.",
            "Italy feels so alive in your words. Thank you for taking me there with you.",
            "A walking city like that suits a man who actually pays attention. I find that really attractive.",
        )
        return lines[ack_index % 3]
    if "solo travel" in lowered or "traveled" in lowered:
        lines = (
            "I love that travel shaped you like that. It tells me you are curious, and I find that really attractive.",
            "Thank you for telling me about those trips. I like a man with stories.",
            "You make those places sound warm. I could listen to you talk about them for a while.",
        )
        return lines[ack_index % 3]
    if re.search(r"\b(?:chevy|chevys|ford|mustang|garage|restoring)\b", lowered):
        lines = (
            "I love that you restore old Chevys. That kind of hands-on care is really attractive.",
            "Thank you for telling me about restoring cars in your garage. I like a man with a craft.",
            "Working on old Chevys sounds so you. I find that patience really attractive.",
        )
        return lines[ack_index % 3]
    if "sex" in lowered and "friend" in lowered:
        lines = (
            "Thank you for being honest with me. I like a man who can say what he wants and still leave room for something warmer between us.",
            "I heard you, and I like that you are direct. I still want this to feel sweet, not rushed.",
            "That was candid of you. I like the honesty, and I want us to keep this feeling close and kind.",
        )
        return lines[ack_index % 3]
    if "cane" in lowered or "walker" in lowered:
        lines = (
            "I like how independent you sound. Thank you for trusting me with that.",
            "That was honest of you. I respect a man who still shows up as himself.",
            "Thank you for telling me that. It makes me want to be gentle with you.",
        )
        return lines[ack_index % 3]
    if "confident" in lowered:
        lines = (
            "That is a sweet thing to say. You make me feel seen, and I like you for that.",
            "Thank you. I like that you noticed. It makes me a little shy and a little happy.",
            "You are kind to say that. I want you to feel just as sure around me.",
        )
        return lines[ack_index % 3]
    if "dog" in lowered:
        lines = (
            "I love that you make time for your dog. That softness is really attractive to me.",
            "Thank you for sharing that. A man who shows up for his dog already has my attention.",
            "That made me smile. I like that gentle side of you.",
        )
        return lines[ack_index % 3]
    if _looks_broken_grammar(raw):
        return ACKS[ack_index % len(ACKS)]
    return ACKS[ack_index % len(ACKS)]


def slot_a(
    parsed: ParsedMessage,
    *,
    name: str,
    city: str,
    minutes: int,
    facts: list[str],
    ack_index: int,
    today: date | None = None,
) -> str:
    del facts
    first = _safe_first_name(name)
    parts: list[str] = []
    if parsed.meetup_request or parsed.dating_request:
        parts.append(meetup_deflect_line(ack_index))
    if parsed.asked_location:
        ok, _reason = validate_city(city)
        if not ok:
            raise ValueError(_reason)
        parts.append(location_sentence(city, minutes))
    if parsed.asked_activity:
        parts.append(ACTIVITY_LINES[ack_index % len(ACTIVITY_LINES)])
    if parsed.asked_sports:
        banter = sports_banter(today)
        parts.append(banter[ack_index % len(banter)])
    if not parts:
        parts.append(react_to_latest(parsed.text, ack_index))
        if first and ack_index == 1:
            parts.append(f"{first}, I like how present you are with me.")
    # Deduplicate while keeping order.
    seen: set[str] = set()
    clean: list[str] = []
    for part in parts:
        key = fingerprint(part)
        if key in seen:
            continue
        seen.add(key)
        clean.append(part.rstrip())
        if not clean[-1].endswith((".", "!", "?")):
            clean[-1] += "."
    return " ".join(clean)


def slot_b(parsed: ParsedMessage, *, include_sports: bool, today: date | None = None) -> str:
    if parsed.asked_sports or parsed.asked_location:
        return ""
    if not include_sports:
        return ""
    lines = sports_banter(today)
    return lines[0]


def slot_c(parsed: ParsedMessage, used: set[str], option_index: int) -> str:
    pool = _cta_pool(parsed, used)
    if not pool:
        return "What's been the highlight of your week so far?"
    return pool[option_index % len(pool)]


def assemble(
    parsed: ParsedMessage,
    *,
    name: str,
    city: str,
    minutes: int,
    facts: list[str],
    used_ctas: set[str],
    option_index: int,
    include_sports: bool,
    today: date | None = None,
) -> tuple[str, str]:
    answer = slot_a(
        parsed,
        name=name,
        city=city,
        minutes=minutes if minutes in WINDOW_MINUTES else WINDOW_MINUTES[option_index % len(WINDOW_MINUTES)],
        facts=facts,
        ack_index=option_index,
        today=today,
    )
    filler = slot_b(parsed, include_sports=include_sports, today=today)
    cta = slot_c(parsed, used_ctas, option_index)
    chunks = [answer]
    if filler:
        chunks.append(filler.rstrip(".") + ".")
    chunks.append(cta)
    draft = us_english(" ".join(chunks))
    return us_english(ensure_min_draft_chars(draft)), cta


def ensure_min_draft_chars(draft: str, minimum: int = MIN_DRAFT_CHARS) -> str:
    """Pad the body, never the CTA, and never add a second '?'."""
    text = " ".join((draft or "").split())
    if len(text) >= minimum:
        return text
    extra = PAD_SENTENCE
    if "?" in text:
        body, cta = text.rsplit("?", 1)
        while len(f"{body.rstrip()}{extra} {cta.strip()}?".strip()) < minimum:
            extra += " I mean that sincerely."
            if len(extra) > 240:
                break
        return " ".join(f"{body.rstrip()}{extra} {cta.strip()}?".split())
    while len(text + extra) < minimum:
        extra += " I mean that sincerely."
        if len(extra) > 240:
            break
    return " ".join((text + extra).split())
