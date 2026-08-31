#!/usr/bin/env python3
"""Build the unique /app/data dump. Run from the task root during authoring."""

from __future__ import annotations

import csv
import json
import random
import struct
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Make sibling settle importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
from settle import FEE_MIN_CENTS, TIMEOUT, bankers, fee_cents, vat_cents  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "environment" / "data"
NAIROBI = ZoneInfo("Africa/Nairobi")
UTC = timezone.utc
AS_OF = datetime(2026, 3, 11, 15, 0, 0, tzinfo=UTC)  # 18:00 EAT
T0 = datetime(2026, 3, 11, 7, 0, 0, tzinfo=UTC)

TRANS_ALPH = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def trans_id(rng: random.Random, n: int) -> str:
    return "NC" + "".join(rng.choice(TRANS_ALPH) for _ in range(8)) + f"{n:04d}"


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def nairobi_str(dt: datetime) -> str:
    local = dt.astimezone(NAIROBI)
    if local.microsecond:
        return local.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return local.strftime("%Y-%m-%d %H:%M:%S")


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

    def add_intent(n: int, amount: int, fence: int, opened: datetime) -> str:
        iid = f"int_{n:04d}"
        intents.append(
            {
                "intent_id": iid,
                "opened_at": iso(opened),
                "amount_cents": amount,
                "till": "441122",
                "fence": fence,
            }
        )
        return iid

    n = 0

    # --- pinned cases used as spot checks ---
    # int_0001: happy STK, 20s later, fence 7, 10000 cents
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
            "till": "441122",
            "result_code": 0,
        }
    )

    # int_0002: callback exactly +47.000s — still good
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
            "till": "441122",
            "result_code": 0,
        }
    )

    # int_0003: callback +47.001s — timeout
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
            "till": "441122",
            "result_code": 0,
        }
    )

    # int_0004: stale fence 6
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
            "till": "441122",
            "result_code": 0,
        }
    )

    # int_0005 / int_0006: same TransID, second is duplicate_trans_id
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
            "till": "441122",
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
            "till": "441122",
            "result_code": 0,
        }
    )

    # int_0007: result_code 1032
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
            "till": "441122",
            "result_code": 1032,
        }
    )

    # int_0008: already in WAL; inbox repeats — duplicate_intent
    n += 1
    opened = T0 + timedelta(minutes=2)
    iid = add_intent(n, 50100, 7, opened)
    fee = fee_cents(50100)
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
            "till": "441122",
            "result_code": 0,
        }
    )

    # int_0009: C2B in CSV, Nairobi local time. 250.00 KES = 25000 cents
    n += 1
    c2b_time = T0 + timedelta(hours=2, minutes=17)
    iid = add_intent(n, 25000, 7, c2b_time - timedelta(seconds=1))
    csv_rows.append(
        {
            "Receipt": "R-9001",
            "Time": nairobi_str(c2b_time),
            "AmountKES": "250.00",
            "Till": "441122",
            "TransID": "QCV7C2B250A",
            "Intent": iid,
            "Fence": "7",
            "Type": "C2B",
        }
    )

    # int_0010: no callback, opened well before as_of — expire at rebuild
    n += 1
    add_intent(n, 125000, 7, T0 + timedelta(minutes=1))

    # bulk STK via nclog + jsonl
    for i in range(80):
        n += 1
        amount = amounts[i % len(amounts)]
        fence = 7
        opened = T0 + timedelta(minutes=12 + i, seconds=rng.randint(0, 40))
        iid = add_intent(n, amount, fence, opened)
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
            "till": "441122",
            "result_code": rc,
        }
        if i % 2 == 0:
            nclog_objs.append(obj)
        else:
            jsonl_rows.append(obj)

    # more C2B rows, including a Nairobi morning that is still 11 Mar UTC
    for i in range(40):
        n += 1
        amount = amounts[(i + 3) % len(amounts)]
        opened = T0 + timedelta(hours=3, minutes=i)
        iid = add_intent(n, amount, 7, opened)
        kes = f"{amount / 100:.2f}"
        csv_rows.append(
            {
                "Receipt": f"R-{10000 + i}",
                "Time": nairobi_str(opened + timedelta(seconds=5)),
                "AmountKES": kes,
                "Till": "441122",
                "TransID": trans_id(rng, 8000 + n),
                "Intent": iid,
                "Fence": "7" if i != 13 else "5",
                "Type": "C2B",
            }
        )

    # garbage jsonl line
    # (handled as a raw extra line when writing)

    # fence-8 record so final fence must bump
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
            "till": "441122",
            "result_code": 0,
        }
    )

    # duplicate intent double callback (fresh trans id)
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
            "till": "441122",
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
            "till": "441122",
            "result_code": 0,
        }
    )

    # write pending
    (DATA / "pending_intents.json").write_text(json.dumps({"intents": intents}, indent=2) + "\n")
    (DATA / "writer_fence").write_text("7\n")
    (DATA / "as_of").write_text("2026-03-11T15:00:00.000Z\n")

    # WAL with torn tail
    torn = struct.pack(">I", 80) + b'{"type":"entry","intent_id":"int_torn"'
    (wal_dir / "writer.wal").write_bytes(lp_pack(wal_entries, torn_tail=torn))

    # jsonl — shuffle within file a bit, keep garbage line
    rng.shuffle(jsonl_rows)
    jsonl_path = inbox / "stk-2026-03-11.jsonl"
    lines = [json.dumps(r, separators=(",", ":")) for r in jsonl_rows]
    lines.insert(17, "{this is not json")
    jsonl_path.write_text("\n".join(lines) + "\n")

    # csv
    csv_path = inbox / "mpesa_c2b.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["Receipt", "Time", "AmountKES", "Till", "TransID", "Intent", "Fence", "Type"],
        )
        w.writeheader()
        w.writerows(csv_rows)

    # nclog torn
    nclog_torn = struct.pack(">I", 40) + b'{"kind":"stk_callback","intent'
    (inbox / "handoff.nclog").write_bytes(lp_pack(nclog_objs, torn_tail=nclog_torn))

    notes = DATA / "SHIFT_NOTES.txt"
    notes.write_text(
        "clear-prod-3 died around 18:00 EAT. Fence file was 7 when I last looked; "
        "handoff.nclog was still writing. Do not trust Amount on STK callbacks — "
        "the intent is source of truth. CSV times are till-local (Nairobi).\n"
    )
    print(f"intents={len(intents)} jsonl={len(jsonl_rows)} csv={len(csv_rows)} nclog={len(nclog_objs)} wal={len(wal_entries)}")
    print("pinned fees:", {a: (fee_cents(a), vat_cents(fee_cents(a))) for a in (10000, 15000, 25000, 50100)})


if __name__ == "__main__":
    main()
