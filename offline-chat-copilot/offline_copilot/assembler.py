"""Assemble Slot A (answer) + Slot B (context) + Slot C (one CTA)."""

from __future__ import annotations

from datetime import date

from .cta import CTA_BANK, CTA_BY_CATEGORY
from .location import WINDOW_MINUTES, location_sentence, validate_city
from .logbook import fingerprint
from .parser import ParsedMessage
from .sports import sports_banter


ACKS = (
    "That's a solid little detail to share.",
    "I like how you put that.",
    "That actually paints a clear picture.",
    "I'm glad you said that instead of keeping it generic.",
    "That stuck with me for a second.",
)

ACTIVITY_LINES = (
    "I'm taking it easy at home and catching up on a few things.",
    "I'm in for the night, just winding down with some food nearby.",
    "I'm keeping the evening low-key and staying in.",
)

MEETUP_DEFLECT = (
    "I like keeping this in chat for now rather than making plans in person."
)

FACT_BRIDGES = (
    "That reminds me of what you said about {fact}.",
    "I keep thinking back to you mentioning {fact}.",
    "It tracks with what you told me about {fact}.",
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


def _clip_fact(fact: str) -> str:
    text = " ".join((fact or "").split())
    if len(text) > 80:
        text = text[:77].rstrip() + "..."
    return text[:1].lower() + text[1:] if text else text


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
    first = (name or "").strip().split()[0] if name.strip() else ""
    parts: list[str] = []
    if parsed.meetup_request or parsed.dating_request:
        parts.append(MEETUP_DEFLECT)
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
    if parsed.story_bits and not parts:
        bit = parsed.story_bits[0]
        parts.append(f"{ACKS[ack_index % len(ACKS)]}")
        parts.append(f"You mentioning '{bit}' actually tells me a lot.")
    if facts and not parsed.asked_location:
        fact = _clip_fact(facts[ack_index % len(facts)])
        bridge = FACT_BRIDGES[ack_index % len(FACT_BRIDGES)].format(fact=fact)
        if bridge not in parts:
            parts.append(bridge)
    if not parts:
        ack = ACKS[ack_index % len(ACKS)]
        if first:
            parts.append(f"{ack} {first}, I like when you actually get into it.")
        else:
            parts.append(ack)
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
    draft = " ".join(chunks)
    return draft, cta
