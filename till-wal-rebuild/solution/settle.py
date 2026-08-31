#!/usr/bin/env python3
"""NyotaClear till-journal rebuild. Stdlib only. Reads /app/data, writes /app/output."""

from __future__ import annotations

import csv
import json
import os
import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

DATA = Path(os.environ.get("NYOTA_DATA", "/app/data"))
OUT = Path(os.environ.get("NYOTA_OUT", "/app/output"))
NAIROBI = ZoneInfo("Africa/Nairobi")
UTC = timezone.utc

FEE_BPS = 85
FEE_MIN_CENTS = 120
VAT = Decimal("0.16")
TIMEOUT = timedelta(seconds=47)

REASON_STALE_FENCE = "stale_fence"
REASON_DUPLICATE_TRANS = "duplicate_trans_id"
REASON_DUPLICATE_INTENT = "duplicate_intent"
REASON_TIMEOUT = "timeout"
REASON_STK_FAILED = "stk_failed"
REASON_BAD_RECORD = "bad_record"
REASON_UNKNOWN_INTENT = "unknown_intent"


def bankers(d: Decimal) -> int:
    return int(d.to_integral_value(rounding=ROUND_HALF_EVEN))


def fee_cents(amount_cents: int) -> int:
    raw = Decimal(amount_cents) * Decimal(FEE_BPS) / Decimal(10000)
    return max(bankers(raw), FEE_MIN_CENTS)


def vat_cents(fee: int) -> int:
    return bankers(Decimal(fee) * VAT)


def parse_iso_utc(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_nairobi(s: str) -> datetime:
    s = s.strip()
    # "2026-03-11 14:22:01" or "2026-03-11 14:22:01.441"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NAIROBI)
    return dt.astimezone(UTC)


@dataclass
class Line:
    account: str
    cents: int


@dataclass
class Entry:
    entry_id: str
    intent_id: str
    trans_id: str
    occurred_at: str
    lines: list[Line]

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "intent_id": self.intent_id,
            "trans_id": self.trans_id,
            "occurred_at": self.occurred_at,
            "lines": [{"account": ln.account, "cents": ln.cents} for ln in self.lines],
        }


@dataclass
class Reject:
    intent_id: str
    reason: str
    source: str
    trans_id: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        d = {
            "intent_id": self.intent_id,
            "reason": self.reason,
            "source": self.source,
        }
        if self.trans_id:
            d["trans_id"] = self.trans_id
        if self.detail:
            d["detail"] = self.detail
        return d


@dataclass
class Intent:
    intent_id: str
    opened_at: datetime
    amount_cents: int
    till: str
    fence: int


@dataclass
class InboxRec:
    kind: str
    intent_id: str
    trans_id: str
    fence: int
    occurred_at: datetime
    amount_cents: int
    till: str
    result_code: int
    source: str
    source_seq: int


@dataclass
class State:
    fence: int
    as_of: datetime
    accounts: dict[str, int] = field(
        default_factory=lambda: {
            "cash": 0,
            "escrow": 0,
            "vendor_payable": 0,
            "fee_income": 0,
            "vat_payable": 0,
        }
    )
    entries: list[Entry] = field(default_factory=list)
    rejects: list[Reject] = field(default_factory=list)
    seen_trans: set[str] = field(default_factory=set)
    seen_intent: set[str] = field(default_factory=set)
    pending: dict[str, Intent] = field(default_factory=dict)
    wal_replayed: int = 0
    entry_seq: int = 0
    pending_expired: int = 0

    def bump_fence(self, f: int) -> None:
        if f > self.fence:
            self.fence = f

    def add_entry(self, intent_id: str, trans_id: str, occurred_at: datetime, lines: list[Line]) -> None:
        self.entry_seq += 1
        eid = f"e_{self.entry_seq:06d}"
        iso = occurred_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        ent = Entry(eid, intent_id, trans_id, iso, lines)
        if sum(ln.cents for ln in lines) != 0:
            raise RuntimeError(f"imbalanced entry {eid}")
        for ln in lines:
            self.accounts[ln.account] = self.accounts.get(ln.account, 0) + ln.cents
        self.entries.append(ent)
        self.seen_trans.add(trans_id)
        self.seen_intent.add(intent_id)

    def reject(self, intent_id: str, reason: str, source: str, trans_id: str = "", detail: str = "") -> None:
        self.rejects.append(Reject(intent_id, reason, source, trans_id, detail))


def read_length_prefixed(path: Path) -> tuple[list[bytes], bool]:
    """Return payloads and whether the file ended on a torn record."""
    data = path.read_bytes()
    out: list[bytes] = []
    i = 0
    torn = False
    while i < len(data):
        if i + 4 > len(data):
            torn = True
            break
        (n,) = struct.unpack(">I", data[i : i + 4])
        i += 4
        if i + n > len(data):
            torn = True
            break
        out.append(data[i : i + n])
        i += n
    return out, torn


def load_fence(path: Path) -> int:
    return int(path.read_text().strip())


def load_as_of(path: Path) -> datetime:
    return parse_iso_utc(path.read_text().strip())


def load_pending(path: Path) -> dict[str, Intent]:
    raw = json.loads(path.read_text())
    out: dict[str, Intent] = {}
    for row in raw["intents"]:
        out[row["intent_id"]] = Intent(
            intent_id=row["intent_id"],
            opened_at=parse_iso_utc(row["opened_at"]),
            amount_cents=int(row["amount_cents"]),
            till=str(row["till"]),
            fence=int(row["fence"]),
        )
    return out


def replay_wal(state: State, path: Path) -> None:
    payloads, _torn = read_length_prefixed(path)
    # torn tail is ignored; complete records replay
    for blob in payloads:
        try:
            rec = json.loads(blob.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if rec.get("type") != "entry":
            continue
        lines = [Line(x["account"], int(x["cents"])) for x in rec["lines"]]
        occurred = parse_iso_utc(rec["occurred_at"])
        state.add_entry(rec["intent_id"], rec["trans_id"], occurred, lines)
        state.wal_replayed += 1
        if "fence" in rec:
            state.bump_fence(int(rec["fence"]))


def parse_jsonl(path: Path) -> list[InboxRec]:
    recs: list[InboxRec] = []
    for i, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        src = f"{path.name}:{i}"
        try:
            obj = json.loads(line)
            recs.append(
                InboxRec(
                    kind=str(obj["kind"]),
                    intent_id=str(obj.get("intent_id") or ""),
                    trans_id=str(obj.get("trans_id") or ""),
                    fence=int(obj["fence"]),
                    occurred_at=parse_iso_utc(obj["occurred_at"]),
                    amount_cents=int(obj["amount_cents"]),
                    till=str(obj.get("till") or ""),
                    result_code=int(obj.get("result_code", 0)),
                    source=src,
                    source_seq=i,
                )
            )
        except (KeyError, ValueError, json.JSONDecodeError, TypeError):
            recs.append(
                InboxRec(
                    kind="bad",
                    intent_id="",
                    trans_id="",
                    fence=-1,
                    occurred_at=datetime(1970, 1, 1, tzinfo=UTC),
                    amount_cents=0,
                    till="",
                    result_code=-1,
                    source=src,
                    source_seq=i,
                )
            )
    return recs


def parse_csv(path: Path) -> list[InboxRec]:
    recs: list[InboxRec] = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):  # header is line 1
            src = f"{path.name}:{i}"
            try:
                kes = Decimal(str(row["AmountKES"]).strip())
                cents = bankers(kes * 100)
                recs.append(
                    InboxRec(
                        kind="c2b" if row["Type"].strip().upper() == "C2B" else row["Type"].strip().lower(),
                        intent_id=str(row["Intent"]).strip(),
                        trans_id=str(row["TransID"]).strip(),
                        fence=int(row["Fence"]),
                        occurred_at=parse_nairobi(row["Time"].strip()),
                        amount_cents=cents,
                        till=str(row["Till"]).strip(),
                        result_code=0,
                        source=src,
                        source_seq=i,
                    )
                )
            except (KeyError, ValueError, TypeError):
                recs.append(
                    InboxRec(
                        kind="bad",
                        intent_id=str(row.get("Intent") or ""),
                        trans_id=str(row.get("TransID") or ""),
                        fence=-1,
                        occurred_at=datetime(1970, 1, 1, tzinfo=UTC),
                        amount_cents=0,
                        till="",
                        result_code=-1,
                        source=src,
                        source_seq=i,
                    )
                )
    return recs


def parse_nclog(path: Path) -> list[InboxRec]:
    payloads, torn = read_length_prefixed(path)
    recs: list[InboxRec] = []
    for i, blob in enumerate(payloads, start=1):
        src = f"{path.name}#{i}"
        try:
            obj = json.loads(blob.decode("utf-8"))
            recs.append(
                InboxRec(
                    kind=str(obj["kind"]),
                    intent_id=str(obj.get("intent_id") or ""),
                    trans_id=str(obj.get("trans_id") or ""),
                    fence=int(obj["fence"]),
                    occurred_at=parse_iso_utc(obj["occurred_at"]),
                    amount_cents=int(obj["amount_cents"]),
                    till=str(obj.get("till") or ""),
                    result_code=int(obj.get("result_code", 0)),
                    source=src,
                    source_seq=i,
                )
            )
        except (KeyError, ValueError, json.JSONDecodeError, UnicodeDecodeError, TypeError):
            recs.append(
                InboxRec(
                    kind="bad",
                    intent_id="",
                    trans_id="",
                    fence=-1,
                    occurred_at=datetime(1970, 1, 1, tzinfo=UTC),
                    amount_cents=0,
                    till="",
                    result_code=-1,
                    source=src,
                    source_seq=i,
                )
            )
    if torn:
        recs.append(
            InboxRec(
                kind="torn_marker",
                intent_id="",
                trans_id="",
                fence=-1,
                occurred_at=datetime(1970, 1, 1, tzinfo=UTC),
                amount_cents=0,
                till="",
                result_code=-1,
                source=f"{path.name}:torn",
                source_seq=10_000_000,
            )
        )
    return recs


def book_payment_and_settle(state: State, intent_id: str, trans_id: str, occurred_at: datetime, amount: int) -> None:
    fee = fee_cents(amount)
    vat = vat_cents(fee)
    net = amount - fee - vat
    # Dr cash / Cr escrow
    state.add_entry(
        intent_id,
        trans_id,
        occurred_at,
        [Line("cash", amount), Line("escrow", -amount)],
    )
    # Dr escrow / Cr vendor, fee, vat
    state.add_entry(
        intent_id,
        trans_id,
        occurred_at,
        [
            Line("escrow", amount),
            Line("vendor_payable", -net),
            Line("fee_income", -fee),
            Line("vat_payable", -vat),
        ],
    )
    # add_entry marks seen_intent/trans twice — that's fine (set)


def apply_inbox(state: State, rec: InboxRec) -> None:
    if rec.kind in ("bad", "torn_marker"):
        if rec.kind == "bad":
            state.reject(rec.intent_id or "?", REASON_BAD_RECORD, rec.source, rec.trans_id)
        return

    if rec.fence < state.fence:
        state.reject(rec.intent_id, REASON_STALE_FENCE, rec.source, rec.trans_id)
        return
    state.bump_fence(rec.fence)

    if rec.kind == "stk_callback":
        if rec.intent_id in state.seen_intent:
            state.reject(rec.intent_id, REASON_DUPLICATE_INTENT, rec.source, rec.trans_id)
            return
        if rec.trans_id in state.seen_trans:
            state.reject(rec.intent_id, REASON_DUPLICATE_TRANS, rec.source, rec.trans_id)
            return
        intent = state.pending.get(rec.intent_id)
        if intent is None:
            state.reject(rec.intent_id, REASON_UNKNOWN_INTENT, rec.source, rec.trans_id)
            return
        if rec.result_code != 0:
            state.reject(rec.intent_id, REASON_STK_FAILED, rec.source, rec.trans_id)
            state.pending.pop(rec.intent_id, None)
            return
        delta = rec.occurred_at - intent.opened_at
        if delta > TIMEOUT:
            state.reject(rec.intent_id, REASON_TIMEOUT, rec.source, rec.trans_id)
            state.pending.pop(rec.intent_id, None)
            return
        # amount on the callback is ignored; the intent amount is authoritative
        book_payment_and_settle(state, rec.intent_id, rec.trans_id, rec.occurred_at, intent.amount_cents)
        state.pending.pop(rec.intent_id, None)
        return

    if rec.kind == "c2b":
        if rec.intent_id in state.seen_intent:
            state.reject(rec.intent_id, REASON_DUPLICATE_INTENT, rec.source, rec.trans_id)
            return
        if rec.trans_id in state.seen_trans:
            state.reject(rec.intent_id, REASON_DUPLICATE_TRANS, rec.source, rec.trans_id)
            return
        book_payment_and_settle(state, rec.intent_id, rec.trans_id, rec.occurred_at, rec.amount_cents)
        state.pending.pop(rec.intent_id, None)
        return

    state.reject(rec.intent_id or "?", REASON_BAD_RECORD, rec.source, rec.trans_id)


def expire_pending(state: State) -> None:
    already = {r.intent_id for r in state.rejects}
    for iid, intent in list(state.pending.items()):
        if iid in state.seen_intent:
            state.pending.pop(iid, None)
            continue
        if iid in already:
            continue
        if state.as_of - intent.opened_at > TIMEOUT:
            state.reject(iid, REASON_TIMEOUT, "as_of", detail="expired_at_rebuild")
            state.pending_expired += 1
            state.pending.pop(iid, None)


def collect_inbox(inbox_dir: Path) -> list[InboxRec]:
    recs: list[InboxRec] = []
    if not inbox_dir.is_dir():
        return recs
    for path in sorted(inbox_dir.iterdir(), key=lambda p: p.name):
        if path.suffix == ".jsonl":
            recs.extend(parse_jsonl(path))
        elif path.suffix == ".csv":
            recs.extend(parse_csv(path))
        elif path.suffix == ".nclog":
            recs.extend(parse_nclog(path))
    recs.sort(key=lambda r: (r.occurred_at, r.source, r.source_seq))
    return recs


def rebuild() -> State:
    as_of = load_as_of(DATA / "as_of")
    fence = load_fence(DATA / "writer_fence")
    state = State(fence=fence, as_of=as_of)
    wal = DATA / "crash_wal" / "writer.wal"
    if wal.exists():
        replay_wal(state, wal)
    pending_path = DATA / "pending_intents.json"
    if pending_path.exists():
        for iid, intent in load_pending(pending_path).items():
            if iid not in state.seen_intent:
                state.pending[iid] = intent
    recs = collect_inbox(DATA / "inbox")
    for rec in recs:
        apply_inbox(state, rec)
    expire_pending(state)
    return state


def write_outputs(state: State) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ledger = {
        "as_of": state.as_of.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "fence": state.fence,
        "accounts": dict(state.accounts),
        "entries": [e.as_dict() for e in state.entries],
    }
    rejects = {
        "rejects": [r.as_dict() for r in sorted(state.rejects, key=lambda x: (x.source, x.intent_id, x.reason))]
    }
    summary = {
        "accepted_intents": len(state.seen_intent),
        "rejected": len(state.rejects),
        "cash_cents": state.accounts["cash"],
        "escrow_cents": state.accounts["escrow"],
        "vendor_cents": -state.accounts["vendor_payable"],
        "fee_cents": -state.accounts["fee_income"],
        "vat_cents": -state.accounts["vat_payable"],
        "pending_expired": state.pending_expired,
        "wal_replayed": state.wal_replayed,
        "final_fence": state.fence,
        "entry_count": len(state.entries),
    }
    (OUT / "ledger.json").write_text(json.dumps(ledger, indent=2, sort_keys=False) + "\n")
    (OUT / "rejects.json").write_text(json.dumps(rejects, indent=2) + "\n")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def main() -> None:
    state = rebuild()
    write_outputs(state)


if __name__ == "__main__":
    main()
