"""Orchestrate parse → assemble → filter. Returns 3 compliant options or a hard block."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .assembler import assemble
from .compliance import validate_draft, validate_incoming
from .location import WINDOW_MINUTES, validate_city
from .logbook import Logbook, fingerprint
from .parser import parse_message


@dataclass
class CopilotResult:
    blocked: bool
    reason: str
    options: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    suggested_facts: list[str] = field(default_factory=list)
    location_required: bool = False


def draft_replies(
    client_name: str,
    client_city: str,
    user_message: str,
    *,
    client_id: str = "",
    logbook: Logbook | None = None,
    logbook_path: str | Path | None = None,
    remember: bool = True,
    today: date | None = None,
    count: int = 3,
) -> CopilotResult:
    ok_in, why_in = validate_incoming(user_message)
    if not ok_in:
        return CopilotResult(blocked=True, reason=why_in, options=[], checks=[why_in])

    parsed = parse_message(user_message)
    location_required = parsed.asked_location
    if location_required:
        city_ok, city_why = validate_city(client_city)
        if not city_ok:
            return CopilotResult(
                blocked=True,
                reason=city_why,
                options=[],
                checks=[city_why],
                location_required=True,
            )

    book = logbook or Logbook(logbook_path)
    record = book.get(client_id or client_name, name=client_name, city=client_city)
    used_ctas = book.used_cta_set(record.client_id)
    used_drafts = book.used_draft_set(record.client_id)
    facts = list(record.facts) or list(parsed.story_bits)

    options: list[str] = []
    checks: list[str] = []
    seen_local: set[str] = set()
    attempt = 0
    while len(options) < max(1, int(count)) and attempt < 40:
        minutes = WINDOW_MINUTES[attempt % len(WINDOW_MINUTES)]
        include_sports = (attempt % 2 == 1) and not parsed.asked_sports
        try:
            draft, cta = assemble(
                parsed,
                name=client_name,
                city=client_city,
                minutes=minutes,
                facts=facts,
                used_ctas=used_ctas | {fingerprint(opt.split("?")[0]) for opt in options},
                option_index=attempt,
                include_sports=include_sports,
                today=today,
            )
        except ValueError as exc:
            return CopilotResult(
                blocked=True,
                reason=str(exc),
                options=[],
                checks=[str(exc)],
                location_required=location_required,
            )
        ok, why = validate_draft(
            draft,
            client_name=client_name,
            client_city=client_city,
            location_required=location_required,
        )
        attempt += 1
        if not ok:
            checks.append(why)
            continue
        fp = fingerprint(draft)
        if fp in seen_local or fp in used_drafts:
            checks.append("Duplicate draft skipped")
            continue
        seen_local.add(fp)
        used_ctas.add(fingerprint(cta))
        options.append(draft)
        checks.append("Passed")
        if remember:
            book.remember_draft(record.client_id, draft, cta, name=client_name, city=client_city)

    if not options:
        return CopilotResult(
            blocked=True,
            reason="Could not assemble a compliant draft",
            options=[],
            checks=checks,
            location_required=location_required,
            suggested_facts=list(parsed.story_bits),
        )
    return CopilotResult(
        blocked=False,
        reason="ok",
        options=options,
        checks=checks,
        location_required=location_required,
        suggested_facts=list(parsed.story_bits),
    )
