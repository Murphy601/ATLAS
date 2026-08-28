"""Orchestrate parse → assemble → filter. Returns 3 compliant options or a hard block."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .assembler import assemble
from .compliance import validate_draft, validate_incoming
from .ingest import ingest_history
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
    logbook_fields: dict[str, str] = field(default_factory=dict)
    save_logbook: bool = False
    save_reason: str = ""
    never_send: bool = True

    @property
    def fill_draft(self) -> str | None:
        if self.blocked or not self.options:
            return None
        return self.options[0]


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
        include_sports = False
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


def handle_claimed_chat(
    history: list[dict] | list[tuple[str, str]],
    *,
    client_id: str = "",
    client_name: str = "",
    header_name: str = "",
    header_city: str = "",
    persona_city: str = "",
    logbook: Logbook | None = None,
    logbook_path: str | Path | None = None,
    logbook_dir: str | Path | None = None,
    remember: bool = True,
    today: date | None = None,
) -> CopilotResult:
    """Ingest scrolled history, update the JSON logbook, then draft. Never sends."""
    name_hint = (header_name or client_name or "").strip()
    ingest = ingest_history(history, header_name=name_hint, header_city=header_city)
    if logbook is None:
        path: str | Path | None = logbook_path
        if path is None and logbook_dir is not None:
            path = Path(logbook_dir) / "logbook.json"
        book = Logbook(path)
    else:
        book = logbook
    record = book.apply_ingest(
        client_id or ingest.client_name or "unknown",
        ingest,
        name=name_hint or ingest.client_name,
        city=header_city or ingest.client_city,
    )
    name = record.name or ingest.client_name or name_hint
    city = record.city or ingest.client_city or header_city
    message = ingest.last_client_message or (ingest.client_messages[-1] if ingest.client_messages else "")
    fields = ingest.to_fields(persona_city)
    # Block if ANY client line is illegal. Draft from the latest client line only.
    for client_line in ingest.client_messages or ([message] if message else []):
        ok_in, why_in = validate_incoming(client_line)
        if not ok_in:
            return CopilotResult(
                blocked=True,
                reason=why_in,
                options=[],
                checks=[why_in],
                logbook_fields=fields,
                save_logbook=ingest.save_logbook,
                save_reason=ingest.save_reason,
            )
    if not message:
        return CopilotResult(
            blocked=True,
            reason="No client messages in the scrolled history",
            logbook_fields=fields,
            save_logbook=ingest.save_logbook,
            save_reason=ingest.save_reason,
        )
    drafted = draft_replies(
        name,
        city,
        message,
        client_id=record.client_id,
        logbook=book,
        remember=remember,
        today=today,
    )
    drafted.logbook_fields = fields
    drafted.save_logbook = ingest.save_logbook
    drafted.save_reason = ingest.save_reason
    drafted.suggested_facts = list(dict.fromkeys([*drafted.suggested_facts, *ingest.facts]))
    return drafted
