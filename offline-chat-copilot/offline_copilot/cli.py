"""CLI: draft three compliant options from local rules only."""

from __future__ import annotations

import argparse
import sys

from .attach import run_attach
from .chathomebase import CLAIMED_URL
from .compliance import validate_draft
from .controller import serve_forever
from .engine import draft_replies
from .logbook import Logbook


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline non-AI chat copilot. Builds 3 compliant drafts. No LLM API."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    draft = sub.add_parser("draft", help="Build 3 reply options")
    draft.add_argument("--name", required=True, help="Client name")
    draft.add_argument("--city", required=True, help="Client city/town")
    draft.add_argument("--id", dest="client_id", default="", help="Worker-facing client id")
    draft.add_argument("--message", required=True, help="Incoming client message")
    draft.add_argument("--logbook", default="logbook.json")
    draft.add_argument("--no-save", action="store_true")

    check = sub.add_parser("check", help="Validate an operator-edited draft before send")
    check.add_argument("--text", required=True)
    check.add_argument("--name", default="")
    check.add_argument("--city", default="")
    check.add_argument("--location-required", action="store_true")

    note = sub.add_parser("note", help="Save a logbook fact")
    note.add_argument("--id", dest="client_id", required=True)
    note.add_argument("--fact", required=True)
    note.add_argument("--name", default="")
    note.add_argument("--city", default="")
    note.add_argument("--logbook", default="logbook.json")

    show = sub.add_parser("show", help="Print a client logbook record")
    show.add_argument("--id", dest="client_id", required=True)
    show.add_argument("--logbook", default="logbook.json")

    serve = sub.add_parser("serve", help="Localhost desktop controller for the userscript")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--logbook", default="logbook.json")

    attach = sub.add_parser("attach", help="Attach to already-open IX Browser on Chat Home Base")
    attach.add_argument("--cdp", default="", help="Optional CDP URL, e.g. http://127.0.0.1:9222")
    attach.add_argument("--url", default=CLAIMED_URL)
    attach.add_argument("--logbook", default="logbook.json")
    attach.add_argument("--once", action="store_true", help="Process one claimed chat then exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd == "draft":
        result = draft_replies(
            args.name,
            args.city,
            args.message,
            client_id=args.client_id,
            logbook_path=args.logbook,
            remember=not args.no_save,
        )
        if result.blocked:
            print(f"BLOCKED: {result.reason}", file=sys.stderr)
            return 2
        print(f"[Incoming] {args.message}")
        print(f"[Client] {args.name} / {args.city}")
        if result.suggested_facts:
            print("[Suggested logbook facts]")
            for fact in result.suggested_facts:
                print(f"  - {fact}")
        print()
        for idx, option in enumerate(result.options, 1):
            print(f"Option {idx}: {option}")
            print("  └─ Compliance Check: PASSED")
            print()
        return 0
    if args.cmd == "check":
        ok, reason = validate_draft(
            args.text,
            client_name=args.name,
            client_city=args.city,
            location_required=args.location_required,
        )
        print("PASSED" if ok else f"FAILED: {reason}")
        return 0 if ok else 2
    if args.cmd == "note":
        book = Logbook(args.logbook)
        book.add_fact(args.client_id, args.fact, name=args.name, city=args.city)
        print("saved")
        return 0
    if args.cmd == "show":
        book = Logbook(args.logbook)
        record = book.get(args.client_id)
        print(f"id: {record.client_id}")
        print(f"name: {record.name}")
        print(f"city: {record.city}")
        print("facts:")
        for fact in record.facts:
            print(f"  - {fact}")
        return 0
    if args.cmd == "serve":
        serve_forever(args.host, args.port, args.logbook)
        return 0
    if args.cmd == "attach":
        return run_attach(
            cdp_url=args.cdp or None,
            target_url=args.url,
            logbook_path=args.logbook,
            once=args.once,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
