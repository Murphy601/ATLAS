#!/usr/bin/env python3
"""Build the unique /app/data dump. Run from the task root during authoring."""

from __future__ import annotations

import csv
import gzip
import hashlib
import hmac
import json
import random
import sqlite3
import struct
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "solution"))
from settle import TIMEOUT, fee_cents, vat_cents  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "environment" / "data"
NAIROBI = ZoneInfo("Africa/Nairobi")
UTC = timezone.utc
AS_OF = datetime(2026, 3, 11, 15, 0, 0, tzinfo=UTC)
T0 = datetime(2026, 3, 11, 7, 0, 0, tzinfo=UTC)

TRANS_ALPH = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
NCLOG_KEY = b"nyota-clear-nclog-v1\n"
FEED_TOKEN = "nclive-clear-prod-3-20260311"
TILL_A = "441122"
TILL_B = "882211"


def hmac_pack(objs: list[dict], torn_tail: bytes | None = None) -> bytes:
    buf = bytearray()
    for o in objs:
        body = {k: v for k, v in o.items() if k != "_gzip"}
        raw = json.dumps(body, separators=(",", ":")).encode()
        if o.get("_gzip"):
            raw = b"NCZG" + gzip.compress(raw, mtime=0)
        mac = hmac.new(NCLOG_KEY, raw, hashlib.sha256).digest()
        buf.extend(struct.pack(">I", len(raw)))
        buf.extend(mac)
        buf.extend(raw)
    if torn_tail is not None:
        buf.extend(torn_tail)
    return bytes(buf)


def trans_id(rng: random.Random, n: int) -> str:
    return "NC" + "".join(rng.choice(TRANS_ALPH) for _ in range(8)) + f"{n:04d}"


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def nairobi_str(dt: datetime) -> str:
    local = dt.astimezone(NAIROBI)
    if local.microsecond:
        return local.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return local.strftime("%Y-%m-%d %H:%M:%S")


def kes_amount(cents: int, thousands: bool) -> str:
    kes = cents / 100
    if thousands:
        return f"{kes:,.2f}"
    return f"{kes:.2f}"


def lp_pack(objs: list[dict], torn_tail: bytes | None = None) -> bytes:
    buf = bytearray()
    for o in objs:
        raw = json.dumps(o, separators=(",", ":")).encode()
        buf.extend(struct.pack(">I", len(raw)))
        buf.extend(raw)
    if torn_tail is not None:
        buf.extend(torn_tail)
    return bytes(buf)


def main() -> None:
    rng = random.Random(20260311)
    inbox = DATA / "inbox"
    wal_dir = DATA / "crash_wal"
    inbox.mkdir(parents=True, exist_ok=True)
    wal_dir.mkdir(parents=True, exist_ok=True)

    intents: list[dict] = []
    jsonl_rows: list[dict] = []
    csv_rows: list[dict] = []
    nclog_objs: list[dict] = []
    wal_entries: list[dict] = []

    amounts = [
        5000,
        10000,
        12000,
        14706,
        15000,
        19900,
        25000,
        33333,
        50100,
        88000,
        125000,
        249999,
    ]

    def add_intent(n: int, amount: int, fence: int, opened: datetime, till: str = TILL_A) -> str:
        iid = f"int_{n:04d}"
        intents.append(
            {
                "intent_id": iid,
                "opened_at": iso(opened),
                "amount_cents": amount,
                "till": till,
                "fence": fence,
            }
        )
        return iid

    n = 0

    n += 1
    opened = T0 + timedelta(minutes=5)
    iid = add_intent(n, 10000, 7, opened)
    jsonl_rows.append(
        {
            "kind": "stk_callback",
            "intent_id": iid,
            "trans_id": "NLJ7RT61SV",
            "fence": 7,
            "occurred_at": iso(opened + timedelta(seconds=20)),
            "amount_cents": 999999,
            "till": TILL_A,
            "result_code": 0,
        }
    )

    n += 1
    opened = T0 + timedelta(minutes=6)
    iid = add_intent(n, 15000, 7, opened)
    jsonl_rows.append(
        {
            "kind": "stk_callback",
            "intent_id": iid,
            "trans_id": "EQ47EXACT01",
            "fence": 7,
            "occurred_at": iso(opened + TIMEOUT),
            "amount_cents": 15000,
            "till": TILL_A,
            "result_code": 0,
        }
    )

    n += 1
    opened = T0 + timedelta(minutes=7)
    iid = add_intent(n, 25000, 7, opened)
    jsonl_rows.append(
        {
            "kind": "stk_callback",
            "intent_id": iid,
            "trans_id": "TO47001LATE",
            "fence": 7,
            "occurred_at": iso(opened + TIMEOUT + timedelta(milliseconds=1)),
            "amount_cents": 25000,
            "till": TILL_A,
            "result_code": 0,
        }
    )

    n += 1
    opened = T0 + timedelta(minutes=8)
    iid = add_intent(n, 88000, 6, opened)
    jsonl_rows.append(
        {
            "kind": "stk_callback",
            "intent_id": iid,
            "trans_id": "STALEFENCE6",
            "fence": 6,
            "occurred_at": iso(opened + timedelta(seconds=3)),
            "amount_cents": 88000,
            "till": TILL_A,
            "result_code": 0,
        }
    )

    n += 1
    opened = T0 + timedelta(minutes=9)
    iid_a = add_intent(n, 33333, 7, opened)
    n += 1
    opened_b = T0 + timedelta(minutes=9, seconds=4)
    iid_b = add_intent(n, 33333, 7, opened_b)
    jsonl_rows.append(
        {
            "kind": "stk_callback",
            "intent_id": iid_a,
            "trans_id": "DUPTRANS001",
            "fence": 7,
            "occurred_at": iso(opened + timedelta(seconds=2)),
            "amount_cents": 33333,
            "till": TILL_A,
            "result_code": 0,
        }
    )
    jsonl_rows.append(
        {
            "kind": "stk_callback",
            "intent_id": iid_b,
            "trans_id": "DUPTRANS001",
            "fence": 7,
            "occurred_at": iso(opened_b + timedelta(seconds=2)),
            "amount_cents": 33333,
            "till": TILL_A,
            "result_code": 0,
        }
    )

    n += 1
    opened = T0 + timedelta(minutes=10)
    iid = add_intent(n, 19900, 7, opened)
    jsonl_rows.append(
        {
            "kind": "stk_callback",
            "intent_id": iid,
            "trans_id": "FAIL1032AAA",
            "fence": 7,
            "occurred_at": iso(opened + timedelta(seconds=8)),
            "amount_cents": 19900,
            "till": TILL_A,
            "result_code": 1032,
        }
    )

    n += 1
    opened = T0 + timedelta(minutes=2)
    iid = add_intent(n, 50100, 7, opened)
    fee = fee_cents(50100, 85, 120)
    vat = vat_cents(fee)
    net = 50100 - fee - vat
    occurred = opened + timedelta(seconds=11)
    wal_entries.append(
        {
            "type": "entry",
            "intent_id": iid,
            "trans_id": "WALREPLAY01",
            "occurred_at": iso(occurred),
            "fence": 7,
            "lines": [{"account": "cash", "cents": 50100}, {"account": "escrow", "cents": -50100}],
        }
    )
    wal_entries.append(
        {
            "type": "entry",
            "intent_id": iid,
            "trans_id": "WALREPLAY01",
            "occurred_at": iso(occurred),
            "fence": 7,
            "lines": [
                {"account": "escrow", "cents": 50100},
                {"account": "vendor_payable", "cents": -net},
                {"account": "fee_income", "cents": -fee},
                {"account": "vat_payable", "cents": -vat},
            ],
        }
    )
    jsonl_rows.append(
        {
            "kind": "stk_callback",
            "intent_id": iid,
            "trans_id": "WALREPLAY01",
            "fence": 7,
            "occurred_at": iso(occurred),
            "amount_cents": 50100,
            "till": TILL_A,
            "result_code": 0,
        }
    )
    wal_0008 = list(wal_entries)

    n += 1
    c2b_time = T0 + timedelta(hours=2, minutes=17)
    iid = add_intent(n, 25000, 7, c2b_time - timedelta(seconds=1))
    csv_rows.append(
        {
            "Receipt": "R-9001",
            "Time": nairobi_str(c2b_time),
            "AmountKES": "250.00",
            "Till": TILL_A,
            "TransID": "QCV7C2B250A",
            "Intent": iid,
            "Fence": "7",
            "Type": "C2B",
        }
    )

    n += 1
    add_intent(n, 125000, 7, T0 + timedelta(minutes=1))

    # int_0011: till B C2B, 110 bps / min 200
    n += 1
    t_b = T0 + timedelta(hours=2, minutes=30)
    iid = add_intent(n, 10000, 7, t_b - timedelta(seconds=1), till=TILL_B)
    csv_rows.append(
        {
            "Receipt": "R-8822",
            "Time": nairobi_str(t_b),
            "AmountKES": "100.00",
            "Till": TILL_B,
            "TransID": "TILLB100FEE",
            "Intent": iid,
            "Fence": "7",
            "Type": "C2B",
        }
    )

    # int_0012: thousands-comma KES on till A
    n += 1
    t_comma = T0 + timedelta(hours=2, minutes=45)
    iid = add_intent(n, 125000, 7, t_comma - timedelta(seconds=1))
    csv_rows.append(
        {
            "Receipt": "R-COMMA",
            "Time": nairobi_str(t_comma),
            "AmountKES": "1,250.00",
            "Till": TILL_A,
            "TransID": "COMMA125000",
            "Intent": iid,
            "Fence": "7",
            "Type": "C2B",
        }
    )

    # int_0013: gzip nclog STK on disk
    n += 1
    opened = T0 + timedelta(hours=1, minutes=5)
    iid = add_intent(n, 20000, 7, opened)
    nclog_objs.append(
        {
            "kind": "stk_callback",
            "intent_id": iid,
            "trans_id": "GZDISK00013",
            "fence": 7,
            "occurred_at": iso(opened + timedelta(seconds=11)),
            "amount_cents": 888888,
            "till": TILL_A,
            "result_code": 0,
            "_gzip": True,
        }
    )

    # int_0014: C2B we reverse later
    n += 1
    t_rev = T0 + timedelta(hours=2, minutes=20)
    iid_rev = add_intent(n, 14706, 7, t_rev - timedelta(seconds=1))
    csv_rows.append(
        {
            "Receipt": "R-REV0",
            "Time": nairobi_str(t_rev),
            "AmountKES": "147.06",
            "Till": TILL_A,
            "TransID": "NC4M68AB7H8091",
            "Intent": iid_rev,
            "Fence": "7",
            "Type": "C2B",
        }
    )

    # int_0015: second WAL file only (not sqlite)
    n += 1
    opened15 = T0 + timedelta(minutes=3)
    iid15 = add_intent(n, 12000, 7, opened15)
    fee15 = fee_cents(12000, 85, 120)
    vat15 = vat_cents(fee15)
    net15 = 12000 - fee15 - vat15
    occurred15 = opened15 + timedelta(seconds=8)
    wal_extra = [
        {
            "type": "entry",
            "intent_id": iid15,
            "trans_id": "WALREPLAY02",
            "occurred_at": iso(occurred15),
            "fence": 7,
            "lines": [{"account": "cash", "cents": 12000}, {"account": "escrow", "cents": -12000}],
        },
        {
            "type": "entry",
            "intent_id": iid15,
            "trans_id": "WALREPLAY02",
            "occurred_at": iso(occurred15),
            "fence": 7,
            "lines": [
                {"account": "escrow", "cents": 12000},
                {"account": "vendor_payable", "cents": -net15},
                {"account": "fee_income", "cents": -fee15},
                {"account": "vat_payable", "cents": -vat15},
            ],
        },
    ]
    jsonl_rows.append(
        {
            "kind": "stk_callback",
            "intent_id": iid15,
            "trans_id": "WALREPLAY02",
            "fence": 7,
            "occurred_at": iso(occurred15),
            "amount_cents": 12000,
            "till": TILL_A,
            "result_code": 0,
        }
    )

    for i in range(100):
        n += 1
        amount = amounts[i % len(amounts)]
        fence = 7
        opened = T0 + timedelta(minutes=12 + i, seconds=rng.randint(0, 40))
        till = TILL_B if i % 11 == 0 else TILL_A
        iid = add_intent(n, amount, fence, opened, till=till)
        tid = trans_id(rng, n)
        delay = rng.choice([3, 5, 9, 12, 20, 30, 40, 46, 47, 48, 90])
        rc = 0 if i % 17 != 0 else rng.choice([1, 1032, 2001])
        obj = {
            "kind": "stk_callback",
            "intent_id": iid,
            "trans_id": tid,
            "fence": fence,
            "occurred_at": iso(opened + timedelta(seconds=delay)),
            "amount_cents": amount,
            "till": till,
            "result_code": rc,
        }
        if i % 2 == 0:
            if i % 6 == 0:
                obj["_gzip"] = True
            nclog_objs.append(obj)
        else:
            jsonl_rows.append(obj)

    for i in range(40):
        n += 1
        amount = amounts[(i + 3) % len(amounts)]
        opened = T0 + timedelta(hours=3, minutes=i)
        till = TILL_B if i % 9 == 0 else TILL_A
        iid = add_intent(n, amount, 7, opened, till=till)
        csv_rows.append(
            {
                "Receipt": f"R-{10000 + i}",
                "Time": nairobi_str(opened + timedelta(seconds=5)),
                "AmountKES": kes_amount(amount, thousands=(amount >= 100000)),
                "Till": till,
                "TransID": trans_id(rng, 8000 + n),
                "Intent": iid,
                "Fence": "7" if i != 13 else "5",
                "Type": "C2B",
            }
        )

    n += 1
    opened = T0 + timedelta(hours=5, minutes=40)
    iid = add_intent(n, 19900, 8, opened)
    jsonl_rows.append(
        {
            "kind": "stk_callback",
            "intent_id": iid,
            "trans_id": "FENCEEIGHT1",
            "fence": 8,
            "occurred_at": iso(opened + timedelta(seconds=4)),
            "amount_cents": 19900,
            "till": TILL_A,
            "result_code": 0,
        }
    )

    n += 1
    opened = T0 + timedelta(hours=4, minutes=2)
    iid = add_intent(n, 12000, 7, opened)
    jsonl_rows.append(
        {
            "kind": "stk_callback",
            "intent_id": iid,
            "trans_id": "TWOSHOTS001",
            "fence": 7,
            "occurred_at": iso(opened + timedelta(seconds=6)),
            "amount_cents": 12000,
            "till": TILL_A,
            "result_code": 0,
        }
    )
    jsonl_rows.append(
        {
            "kind": "stk_callback",
            "intent_id": iid,
            "trans_id": "TWOSHOTS002",
            "fence": 7,
            "occurred_at": iso(opened + timedelta(seconds=9)),
            "amount_cents": 12000,
            "till": TILL_A,
            "result_code": 0,
        }
    )

    (DATA / "pending_intents.json").write_text(json.dumps({"intents": intents}, indent=2) + "\n")
    (DATA / "writer_fence").write_text("7\n")
    (DATA / "as_of").write_text("2026-03-11T15:00:00.000Z\n")
    (DATA / "nclog.key").write_bytes(NCLOG_KEY)
    (DATA / "feed.token").write_text(FEED_TOKEN + "\n")
    (DATA / "tills.json").write_text(
        json.dumps(
            {
                TILL_A: {
                    "timezone": "Africa/Nairobi",
                    "fee_bps": 85,
                    "fee_min_cents": 120,
                    "vat_rate": "0.16",
                },
                TILL_B: {
                    "timezone": "Africa/Nairobi",
                    "fee_bps": 110,
                    "fee_min_cents": 200,
                    "vat_rate": "0.16",
                },
            },
            indent=2,
        )
        + "\n"
    )

    torn = struct.pack(">I", 80) + b'{"type":"entry","intent_id":"int_torn"'
    for leftover in wal_dir.glob("*"):
        leftover.unlink()
    (wal_dir / "0001.wal").write_bytes(lp_pack(wal_0008))
    (wal_dir / "0002.wal").write_bytes(lp_pack(wal_extra, torn_tail=torn))

    db_path = DATA / "posted.db"
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(str(db_path))
    con.execute(
        "CREATE TABLE posted (intent_id TEXT, trans_id TEXT, occurred_at TEXT, fence INTEGER, lines_json TEXT)"
    )
    for we in wal_entries:
        con.execute(
            "INSERT INTO posted VALUES (?,?,?,?,?)",
            (
                we["intent_id"],
                we["trans_id"],
                we["occurred_at"],
                we.get("fence", 7),
                json.dumps(we["lines"]),
            ),
        )
    con.commit()
    con.close()

    rng.shuffle(jsonl_rows)
    jsonl_path = inbox / "stk-2026-03-11.jsonl"
    lines = [json.dumps(r, separators=(",", ":")) for r in jsonl_rows]
    lines.insert(17, "{this is not json")
    jsonl_path.write_text("\n".join(lines) + "\n")

    csv_rows.append(
        {
            "Receipt": "R-REV1",
            "Time": nairobi_str(T0 + timedelta(hours=5, minutes=10)),
            "AmountKES": "147.06",
            "Till": TILL_A,
            "TransID": "NC4M68AB7H8091",
            "Intent": iid_rev,
            "Fence": "7",
            "Type": "REVERSAL",
        }
    )
    csv_rows.append(
        {
            "Receipt": "R-REV2",
            "Time": nairobi_str(T0 + timedelta(hours=5, minutes=12)),
            "AmountKES": "147.06",
            "Till": TILL_A,
            "TransID": "NC4M68AB7H8091",
            "Intent": iid_rev,
            "Fence": "7",
            "Type": "REVERSAL",
        }
    )
    csv_rows.append(
        {
            "Receipt": "R-REV3",
            "Time": nairobi_str(T0 + timedelta(hours=5, minutes=15)),
            "AmountKES": "1.00",
            "Till": TILL_A,
            "TransID": "NOSUCHTRANS9",
            "Intent": "int_rev_ghost",
            "Fence": "7",
            "Type": "REVERSAL",
        }
    )

    csv_path = inbox / "mpesa_c2b.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["Receipt", "Time", "AmountKES", "Till", "TransID", "Intent", "Fence", "Type"],
        )
        w.writeheader()
        w.writerows(csv_rows)

    # int_skip: happy STK on the feed AFTER a bad MAC — must not book
    n += 1
    opened_skip = T0 + timedelta(hours=1, minutes=40)
    iid_skip = add_intent(n, 88000, 7, opened_skip)
    skip_obj = {
        "kind": "stk_callback",
        "intent_id": iid_skip,
        "trans_id": "SKIPAFTERMAC",
        "fence": 7,
        "occurred_at": iso(opened_skip + timedelta(seconds=6)),
        "amount_cents": 88000,
        "till": TILL_A,
        "result_code": 0,
    }

    disk_part = nclog_objs[:12]
    feed_before = nclog_objs[12:]
    feed_after = [skip_obj]
    (inbox / "handoff.nclog").write_bytes(hmac_pack(disk_part))
    feed_dir = ROOT / "environment" / "feed"
    feed_dir.mkdir(parents=True, exist_ok=True)
    poison = json.dumps(
        {"kind": "stk_callback", "intent_id": "int_poison", "trans_id": "BADMACFRAME", "fence": 7},
        separators=(",", ":"),
    ).encode()
    feed_blob = bytearray(hmac_pack(feed_before))
    feed_blob.extend(struct.pack(">I", len(poison)))
    feed_blob.extend(b"\x00" * 32)
    feed_blob.extend(poison)
    feed_blob.extend(hmac_pack(feed_after))
    feed_blob.extend(struct.pack(">I", 40) + b'{"kind":"stk')
    (feed_dir / "payload.nclog").write_bytes(bytes(feed_blob))
    (feed_dir / "feed.token").write_text(FEED_TOKEN + "\n")

    (DATA / "SHIFT_NOTES.txt").write_text(
        "clear-prod-3 fell over around 18:00 EAT. Fence file still said 7, take that with salt. "
        "Tail never flushed. 882211 is not the 85 book. I keep mixing them up.\n"
    )

    print(
        f"intents={len(intents)} jsonl={len(jsonl_rows)} csv={len(csv_rows)} "
        f"nclog_disk={len(disk_part)} nclog_feed_before_mac={len(feed_before)} wal8={len(wal_0008)} wal_extra={len(wal_extra)}"
    )
    print(
        "pinned fees A:",
        {a: (fee_cents(a, 85, 120), vat_cents(fee_cents(a, 85, 120))) for a in (10000, 15000, 25000, 50100, 125000)},
    )
    print("till B 10000:", fee_cents(10000, 110, 200), vat_cents(fee_cents(10000, 110, 200)))


if __name__ == "__main__":
    main()
