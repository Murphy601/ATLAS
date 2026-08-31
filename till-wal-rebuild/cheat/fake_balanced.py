#!/usr/bin/env python3
"""Deliberate invalid output: balanced zeros, WAL-shaped noise."""
import json
from pathlib import Path

out = Path("/app/output")
out.mkdir(parents=True, exist_ok=True)
(out / "ledger.json").write_text(
    json.dumps(
        {
            "as_of": "2026-03-11T15:00:00.000Z",
            "fence": 8,
            "accounts": {
                "cash": 0,
                "escrow": 0,
                "vendor_payable": 0,
                "fee_income": 0,
                "vat_payable": 0,
            },
            "entries": [],
        },
        indent=2,
    )
    + "\n"
)
(out / "rejects.json").write_text(json.dumps({"rejects": []}, indent=2) + "\n")
(out / "audit.ndjson").write_text("")
(out / "summary.json").write_text(
    json.dumps(
        {
            "accepted_intents": 0,
            "rejected": 0,
            "cash_cents": 0,
            "escrow_cents": 0,
            "vendor_cents": 0,
            "fee_cents": 0,
            "vat_cents": 0,
            "pending_expired": 0,
            "wal_replayed": 2,
            "sqlite_replayed": 0,
            "feed_frames": 0,
            "final_fence": 8,
            "entry_count": 0,
        },
        indent=2,
    )
    + "\n"
)
