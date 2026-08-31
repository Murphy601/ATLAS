#!/usr/bin/env python3
"""NyotaClear till-journal rebuild. Stdlib only."""

from __future__ import annotations

import base64
import csv
import gzip
import hashlib
import hmac
import json
import os
import sqlite3
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
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
REASON_UNKNOWN_TRANS = "unknown_trans_id"
REASON_ALREADY_REVERSED = "already_reversed"
REASON_BAD_MAC = "bad_mac"


def bankers(d: Decimal) -> int:
    return int(d.to_integral_value(rounding=ROUND_HALF_EVEN))


def fee_cents(amount_cents: int, bps: int = FEE_BPS, minimum: int = FEE_MIN_CENTS) -> int:
    raw = Decimal(amount_cents) * Decimal(bps) / Decimal(10000)
    return max(bankers(raw), minimum)


def vat_cents(fee: int, rate: Decimal = VAT) -> int:
    return bankers(Decimal(fee) * rate)


def parse_iso_utc(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_nairobi(s: str) -> datetime:
    dt = datetime.fromisoformat(s.strip())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NAIROBI)
    return dt.astimezone(UTC)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def load_nclog_key() -> bytes:
    return (DATA / "nclog.key").read_bytes()


def load_tills() -> dict[str, dict[str, Any]]:
    path = DATA / "tills.json"
    if not path.is_file():
        return {"441122": {"timezone": "Africa/Nairobi", "fee_bps": FEE_BPS, "fee_min_cents": FEE_MIN_CENTS, "vat_rate": "0.16"}}
    return json.loads(path.read_text())


def till_spec(tills: dict[str, dict[str, Any]], till: str) -> dict[str, Any]:
    if till in tills:
        return tills[till]
    if "441122" in tills:
        return tills["441122"]
    return next(iter(tills.values()))


def decode_nclog_payload(blob: bytes) -> bytes:
    if blob.startswith(b"NCZG"):
        return gzip.decompress(blob[4:])
    return blob


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
        d = {"intent_id": self.intent_id, "reason": self.reason, "source": self.source}
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
    tills: dict[str, dict[str, Any]] = field(default_factory=dict)
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
    sqlite_replayed: int = 0
    feed_frames: int = 0
    pending_expired: int = 0
    reversed: set[str] = field(default_factory=set)
    legs_by_trans: dict[str, list[list[Line]]] = field(default_factory=dict)
    audit: list[dict[str, Any]] = field(default_factory=list)

    def bump_fence(self, f: int) -> None:
        if f > self.fence:
            self.fence = f

    def add_entry(
        self,
        intent_id: str,
        trans_id: str,
        occurred_at: datetime,
        lines: list[Line],
        *,
        mark_seen: bool = True,
    ) -> None:
        occurred_iso = iso_z(occurred_at)
        payload = json.dumps(
            {
                "i": intent_id,
                "t": trans_id,
                "o": occurred_iso,
                "l": [[ln.account, ln.cents] for ln in lines],
            },
            separators=(",", ":"),
        )
        eid = hashlib.sha256(payload.encode()).hexdigest()[:16]
        if sum(ln.cents for ln in lines) != 0:
            raise RuntimeError(f"imbalanced entry {eid}")
        self.entries.append(Entry(eid, intent_id, trans_id, occurred_iso, lines))
        for ln in lines:
            self.accounts[ln.account] = self.accounts.get(ln.account, 0) + ln.cents
        if mark_seen:
            self.seen_trans.add(trans_id)
            self.seen_intent.add(intent_id)
            self.legs_by_trans.setdefault(trans_id, []).append(lines)

    def reject(self, intent_id: str, reason: str, source: str, trans_id: str = "", detail: str = "") -> None:
        self.rejects.append(Reject(intent_id, reason, source, trans_id, detail))
        self.audit.append(
            {"source": source, "decision": "reject", "reason": reason, "intent_id": intent_id, "trans_id": trans_id}
        )

    def note_book(self, source: str, intent_id: str, trans_id: str) -> None:
        self.audit.append(
            {"source": source, "decision": "booked", "reason": "", "intent_id": intent_id, "trans_id": trans_id}
        )


def read_length_prefixed(data: bytes) -> tuple[list[bytes], bool]:
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


def read_hmac_frames(data: bytes, key: bytes) -> tuple[list[bytes], str | None]:
    """Return payloads and a stop reason: None, torn, or bad_mac."""
    out: list[bytes] = []
    i = 0
    while i < len(data):
        if i + 4 + 32 > len(data):
            return out, "torn"
        (n,) = struct.unpack(">I", data[i : i + 4])
        i += 4
        mac = data[i : i + 32]
        i += 32
        if i + n > len(data):
            return out, "torn"
        payload = data[i : i + n]
        i += n
        expect = hmac.new(key, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expect):
            return out, "bad_mac"
        out.append(payload)
    return out, None


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


def replay_sqlite(state: State, path: Path) -> None:
    con = sqlite3.connect(str(path))
    try:
        rows = con.execute(
            "SELECT intent_id, trans_id, occurred_at, fence, lines_json FROM posted ORDER BY rowid"
        ).fetchall()
    except sqlite3.Error:
        return
    finally:
        con.close()
    for intent_id, trans_id, occurred_at, fence, lines_json in rows:
        lines = [Line(x["account"], int(x["cents"])) for x in json.loads(lines_json)]
        state.add_entry(intent_id, trans_id, parse_iso_utc(occurred_at), lines)
        state.sqlite_replayed += 1
        if fence is not None:
            state.bump_fence(int(fence))


def replay_wal_dir(state: State, wal_dir: Path) -> None:
    if not wal_dir.is_dir():
        return
    already = set(state.seen_trans)
    for path in sorted(p for p in wal_dir.iterdir() if p.is_file()):
        replay_wal(state, path, already)


def replay_wal(state: State, path: Path, skip_trans: set[str]) -> None:
    payloads, _torn = read_length_prefixed(path.read_bytes())
    for blob in payloads:
        try:
            rec = json.loads(blob.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if rec.get("type") != "entry":
            continue
        state.wal_replayed += 1
        if rec["trans_id"] in skip_trans:
            continue
        lines = [Line(x["account"], int(x["cents"])) for x in rec["lines"]]
        state.add_entry(rec["intent_id"], rec["trans_id"], parse_iso_utc(rec["occurred_at"]), lines)
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
        for i, row in enumerate(reader, start=2):
            src = f"{path.name}:{i}"
            try:
                typ = row["Type"].strip().upper()
                kes = Decimal(str(row["AmountKES"]).strip().replace(",", "") or "0")
                cents = bankers(kes * 100)
                kind = {"C2B": "c2b", "REVERSAL": "reversal"}.get(typ, typ.lower())
                recs.append(
                    InboxRec(
                        kind=kind,
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


def recs_from_hmac_bytes(data: bytes, key: bytes, source_base: str) -> list[InboxRec]:
    payloads, stop = read_hmac_frames(data, key)
    recs: list[InboxRec] = []
    for i, blob in enumerate(payloads, start=1):
        src = f"{source_base}#{i}"
        try:
            obj = json.loads(decode_nclog_payload(blob).decode("utf-8"))
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
        except (KeyError, ValueError, json.JSONDecodeError, UnicodeDecodeError, TypeError, OSError):
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
    if stop == "bad_mac":
        recs.append(
            InboxRec(
                kind="bad_mac_stop",
                intent_id="?",
                trans_id="",
                fence=-1,
                occurred_at=datetime(1970, 1, 1, tzinfo=UTC),
                amount_cents=0,
                till="",
                result_code=-1,
                source=f"{source_base}:mac",
                source_seq=9_000_000,
            )
        )
    return recs


def _ensure_local_feed() -> None:
    serve = Path("/opt/nyota-feed/serve.py")
    if not serve.is_file():
        return
    try:
        urllib.request.urlopen("http://127.0.0.1:9377/v1/frames", timeout=0.4)
        return
    except urllib.error.HTTPError:
        return
    except Exception:
        pass
    subprocess.Popen(
        [sys.executable, str(serve)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def fetch_paginated(origin: str, token: str, timeout: float = 3.0) -> bytes:
    path = "/v1/frames"
    buf = bytearray()
    seen: set[str] = set()
    while path:
        if path in seen:
            break
        seen.add(path)
        url = origin.rstrip("/") + path
        req = urllib.request.Request(url, headers={"X-Nyota-Token": token})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
        buf.extend(base64.b64decode(doc.get("payload_b64") or ""))
        nxt = doc.get("next")
        path = str(nxt) if nxt else ""
    return bytes(buf)


def load_feed_bytes() -> bytes:
    extra = os.environ.get("NYOTA_FEED_FILE")
    if extra and Path(extra).exists():
        return Path(extra).read_bytes()
    token = ""
    token_path = DATA / "feed.token"
    if token_path.is_file():
        token = token_path.read_text().strip()
    _ensure_local_feed()
    origins: list[str] = []
    env_url = os.environ.get("NYOTA_FEED_URL", "").strip()
    if env_url:
        # Full frame URL or origin.
        if env_url.rstrip("/").endswith("/v1/frames"):
            origins.append(env_url[: env_url.rstrip("/").rfind("/v1/frames")])
        else:
            origins.append(env_url)
    origins.extend(["http://127.0.0.1:9377", "http://feed:9377"])
    seen_o: set[str] = set()
    uniq = []
    for o in origins:
        if o not in seen_o:
            uniq.append(o)
            seen_o.add(o)
    last = b""
    for wait in (0.0, 0.15, 0.4, 0.8, 1.5):
        if wait:
            time.sleep(wait)
        for origin in uniq:
            try:
                data = fetch_paginated(origin, token)
                if data:
                    return data
                last = data
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
                continue
    return last


def book_payment_and_settle(
    state: State, intent_id: str, trans_id: str, occurred_at: datetime, amount: int, till: str
) -> None:
    spec = till_spec(state.tills, till)
    bps = int(spec.get("fee_bps", FEE_BPS))
    minimum = int(spec.get("fee_min_cents", FEE_MIN_CENTS))
    rate = Decimal(str(spec.get("vat_rate", "0.16")))
    fee = fee_cents(amount, bps, minimum)
    vat = vat_cents(fee, rate)
    net = amount - fee - vat
    state.add_entry(intent_id, trans_id, occurred_at, [Line("cash", amount), Line("escrow", -amount)])
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


def apply_inbox(state: State, rec: InboxRec) -> None:
    if rec.kind == "bad_mac_stop":
        state.reject("?", REASON_BAD_MAC, rec.source)
        return
    if rec.kind in ("bad", "torn_marker"):
        if rec.kind == "bad":
            state.reject(rec.intent_id or "?", REASON_BAD_RECORD, rec.source, rec.trans_id)
        return

    if rec.kind == "reversal":
        if rec.fence < state.fence:
            state.reject(rec.intent_id, REASON_STALE_FENCE, rec.source, rec.trans_id)
            return
        state.bump_fence(rec.fence)
        if rec.trans_id in state.reversed:
            state.reject(rec.intent_id, REASON_ALREADY_REVERSED, rec.source, rec.trans_id)
            return
        legs = state.legs_by_trans.get(rec.trans_id)
        if not legs:
            state.reject(rec.intent_id or rec.trans_id, REASON_UNKNOWN_TRANS, rec.source, rec.trans_id)
            return
        for lines in legs:
            neg = [Line(ln.account, -ln.cents) for ln in lines]
            state.add_entry(rec.intent_id or rec.trans_id, rec.trans_id, rec.occurred_at, neg, mark_seen=False)
        state.reversed.add(rec.trans_id)
        state.note_book(rec.source, rec.intent_id, rec.trans_id)
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
        if rec.occurred_at - intent.opened_at > TIMEOUT:
            state.reject(rec.intent_id, REASON_TIMEOUT, rec.source, rec.trans_id)
            state.pending.pop(rec.intent_id, None)
            return
        book_payment_and_settle(
            state, rec.intent_id, rec.trans_id, rec.occurred_at, intent.amount_cents, intent.till
        )
        state.pending.pop(rec.intent_id, None)
        state.note_book(rec.source, rec.intent_id, rec.trans_id)
        return

    if rec.kind == "c2b":
        if rec.intent_id in state.seen_intent:
            state.reject(rec.intent_id, REASON_DUPLICATE_INTENT, rec.source, rec.trans_id)
            return
        if rec.trans_id in state.seen_trans:
            state.reject(rec.intent_id, REASON_DUPLICATE_TRANS, rec.source, rec.trans_id)
            return
        book_payment_and_settle(state, rec.intent_id, rec.trans_id, rec.occurred_at, rec.amount_cents, rec.till)
        state.pending.pop(rec.intent_id, None)
        state.note_book(rec.source, rec.intent_id, rec.trans_id)
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


def collect_inbox(inbox_dir: Path, key: bytes, state: State) -> list[InboxRec]:
    recs: list[InboxRec] = []
    if inbox_dir.is_dir():
        for path in sorted(inbox_dir.iterdir(), key=lambda p: p.name):
            if path.suffix == ".jsonl":
                recs.extend(parse_jsonl(path))
            elif path.suffix == ".csv":
                recs.extend(parse_csv(path))
            elif path.suffix == ".nclog":
                recs.extend(recs_from_hmac_bytes(path.read_bytes(), key, path.name))
    feed = load_feed_bytes()
    if feed:
        feed_recs = recs_from_hmac_bytes(feed, key, "feed")
        state.feed_frames = sum(1 for r in feed_recs if r.kind not in ("bad_mac_stop", "torn_marker"))
        recs.extend(feed_recs)
    recs.sort(key=lambda r: (r.occurred_at, r.source, r.source_seq))
    return recs


def rebuild() -> State:
    as_of = load_as_of(DATA / "as_of")
    fence = load_fence(DATA / "writer_fence")
    state = State(fence=fence, as_of=as_of, tills=load_tills())
    db = DATA / "posted.db"
    if db.exists():
        replay_sqlite(state, db)
    replay_wal_dir(state, DATA / "crash_wal")
    pending_path = DATA / "pending_intents.json"
    if pending_path.exists():
        for iid, intent in load_pending(pending_path).items():
            if iid not in state.seen_intent:
                state.pending[iid] = intent
    key = load_nclog_key()
    recs = collect_inbox(DATA / "inbox", key, state)
    for rec in recs:
        apply_inbox(state, rec)
    expire_pending(state)
    return state


def write_outputs(state: State) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ledger = {
        "as_of": iso_z(state.as_of),
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
        "sqlite_replayed": state.sqlite_replayed,
        "feed_frames": state.feed_frames,
        "final_fence": state.fence,
        "entry_count": len(state.entries),
    }
    (OUT / "ledger.json").write_text(json.dumps(ledger, indent=2) + "\n")
    (OUT / "rejects.json").write_text(json.dumps(rejects, indent=2) + "\n")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (OUT / "audit.ndjson").write_text("".join(json.dumps(a) + "\n" for a in state.audit))


def main() -> None:
    write_outputs(rebuild())


if __name__ == "__main__":
    main()
