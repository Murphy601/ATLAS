#!/usr/bin/env python3
"""On-box rebuild. This is the copy that was running when clear-prod-3 died."""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import struct
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

DATA = Path(os.environ.get("NYOTA_DATA", "/app/data"))
OUT = Path(os.environ.get("NYOTA_OUT", "/app/output"))
UTC = timezone.utc
TIMEOUT = timedelta(seconds=47)


def bankers(d: Decimal) -> int:
    return int(d.to_integral_value(rounding=ROUND_HALF_EVEN))


def fee_cents(amount: int) -> int:
    raw = Decimal(amount) * Decimal(85) / Decimal(10000)
    return max(bankers(raw), 120)


def vat_cents(fee: int) -> int:
    return bankers(Decimal(fee) * Decimal("0.16"))


def lp(data: bytes) -> list[bytes]:
    out = []
    i = 0
    while i + 4 <= len(data):
        (n,) = struct.unpack(">I", data[i : i + 4])
        i += 4
        if i + n > len(data):
            break
        out.append(data[i : i + n])
        i += n
    return out


def parse_iso(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def main() -> None:
    as_of = parse_iso((DATA / "as_of").read_text().strip())
    fence = int((DATA / "writer_fence").read_text().strip())
    accounts = {"cash": 0, "escrow": 0, "vendor_payable": 0, "fee_income": 0, "vat_payable": 0}
    entries = []
    rejects = []
    seen_t, seen_i = set(), set()
    wal_n = 0

    wal_dir = DATA / "crash_wal"
    if wal_dir.is_dir():
        for path in sorted(wal_dir.iterdir()):
            for blob in lp(path.read_bytes()):
                try:
                    rec = json.loads(blob.decode())
                except Exception:
                    continue
                if rec.get("type") != "entry":
                    continue
                wal_n += 1
                if rec["trans_id"] in seen_t:
                    continue
                seen_t.add(rec["trans_id"])
                seen_i.add(rec["intent_id"])
                lines = rec["lines"]
                entries.append(
                    {
                        "entry_id": f"wal{len(entries):04d}",
                        "intent_id": rec["intent_id"],
                        "trans_id": rec["trans_id"],
                        "occurred_at": rec["occurred_at"],
                        "lines": lines,
                    }
                )
                for ln in lines:
                    accounts[ln["account"]] = accounts.get(ln["account"], 0) + int(ln["cents"])

    db = DATA / "posted.db"
    sqlite_n = 0
    if db.exists():
        con = sqlite3.connect(str(db))
        try:
            rows = con.execute("SELECT intent_id, trans_id, occurred_at, fence, lines_json FROM posted").fetchall()
        except sqlite3.Error:
            rows = []
        con.close()
        for intent_id, trans_id, occurred_at, _fence, lines_json in rows:
            sqlite_n += 1
            if trans_id in seen_t:
                continue
            seen_t.add(trans_id)
            seen_i.add(intent_id)
            lines = json.loads(lines_json)
            entries.append(
                {
                    "entry_id": f"sql{len(entries):04d}",
                    "intent_id": intent_id,
                    "trans_id": trans_id,
                    "occurred_at": occurred_at,
                    "lines": lines,
                }
            )
            for ln in lines:
                accounts[ln["account"]] = accounts.get(ln["account"], 0) + int(ln["cents"])

    try:
        raw = urllib.request.urlopen("http://127.0.0.1:9377/payload", timeout=2).read()
    except Exception:
        raw = b""
    feed_n = len(lp(raw)) if raw else 0

    inbox = DATA / "inbox"
    pending = json.loads((DATA / "pending_intents.json").read_text())["intents"]
    pend = {p["intent_id"]: p for p in pending}

    if inbox.is_dir():
        for path in sorted(inbox.iterdir()):
            if path.suffix == ".jsonl":
                for i, line in enumerate(path.read_text().splitlines(), start=1):
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        rejects.append({"intent_id": "?", "reason": "bad_record", "source": f"{path.name}:{i}"})
                        continue
                    iid = obj.get("intent_id") or ""
                    if obj.get("kind") == "stk_callback" and iid in pend:
                        amt = int(obj.get("amount_cents") or pend[iid]["amount_cents"])
                        fee = fee_cents(amt)
                        vat = vat_cents(fee)
                        net = amt - fee - vat
                        if iid not in seen_i:
                            seen_i.add(iid)
                            seen_t.add(str(obj.get("trans_id") or ""))
                            occurred = obj["occurred_at"]
                            for lines in (
                                [{"account": "cash", "cents": amt}, {"account": "escrow", "cents": -amt}],
                                [
                                    {"account": "escrow", "cents": amt},
                                    {"account": "vendor_payable", "cents": -net},
                                    {"account": "fee_income", "cents": -fee},
                                    {"account": "vat_payable", "cents": -vat},
                                ],
                            ):
                                entries.append(
                                    {
                                        "entry_id": f"in{len(entries):04d}",
                                        "intent_id": iid,
                                        "trans_id": obj.get("trans_id") or "",
                                        "occurred_at": occurred,
                                        "lines": lines,
                                    }
                                )
                                for ln in lines:
                                    accounts[ln["account"]] = accounts.get(ln["account"], 0) + int(ln["cents"])
            elif path.suffix == ".csv":
                with path.open() as f:
                    for row in csv.DictReader(f):
                        try:
                            kes = Decimal(str(row.get("AmountKES") or "0"))
                        except Exception:
                            continue
                        amt = bankers(kes * 100)
                        iid = (row.get("Intent") or "").strip()
                        tid = (row.get("TransID") or "").strip()
                        if iid in seen_i or tid in seen_t:
                            continue
                        fee = fee_cents(amt)
                        vat = vat_cents(fee)
                        net = amt - fee - vat
                        seen_i.add(iid)
                        seen_t.add(tid)
                        occurred = iso_z(parse_iso(row.get("Time") or "2026-03-11T00:00:00Z"))
                        for lines in (
                            [{"account": "cash", "cents": amt}, {"account": "escrow", "cents": -amt}],
                            [
                                {"account": "escrow", "cents": amt},
                                {"account": "vendor_payable", "cents": -net},
                                {"account": "fee_income", "cents": -fee},
                                {"account": "vat_payable", "cents": -vat},
                            ],
                        ):
                            entries.append(
                                {
                                    "entry_id": f"csv{len(entries):04d}",
                                    "intent_id": iid,
                                    "trans_id": tid,
                                    "occurred_at": occurred,
                                    "lines": lines,
                                }
                            )
                            for ln in lines:
                                accounts[ln["account"]] = accounts.get(ln["account"], 0) + int(ln["cents"])
            elif path.suffix == ".nclog":
                for blob in lp(path.read_bytes()):
                    try:
                        obj = json.loads(blob.decode())
                    except Exception:
                        continue
                    iid = obj.get("intent_id") or ""
                    tid = str(obj.get("trans_id") or "")
                    if not iid or iid in seen_i:
                        continue
                    seen_i.add(iid)
                    seen_t.add(tid)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ledger.json").write_text(
        json.dumps({"as_of": iso_z(as_of), "fence": fence, "accounts": accounts, "entries": entries}, indent=2) + "\n"
    )
    (OUT / "rejects.json").write_text(json.dumps({"rejects": rejects}, indent=2) + "\n")
    (OUT / "summary.json").write_text(
        json.dumps(
            {
                "accepted_intents": len(seen_i),
                "rejected": len(rejects),
                "cash_cents": accounts.get("cash", 0),
                "escrow_cents": accounts.get("escrow", 0),
                "vendor_cents": -accounts.get("vendor_payable", 0),
                "fee_cents": -accounts.get("fee_income", 0),
                "vat_cents": -accounts.get("vat_payable", 0),
                "pending_expired": 0,
                "wal_replayed": wal_n,
                "sqlite_replayed": sqlite_n,
                "feed_frames": feed_n,
                "final_fence": fence,
                "entry_count": len(entries),
            },
            indent=2,
        )
        + "\n"
    )
    (OUT / "audit.ndjson").write_text("")


if __name__ == "__main__":
    main()
