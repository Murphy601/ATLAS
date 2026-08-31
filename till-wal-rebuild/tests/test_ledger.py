from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

import pytest

ART = Path("/app/output")
GOLD = Path("/tests/golden")

FEE_BPS = 85
FEE_MIN = 120
VAT = Decimal("0.16")


def bankers(d: Decimal) -> int:
    return int(d.to_integral_value(rounding=ROUND_HALF_EVEN))


def fee_cents(amount: int) -> int:
    raw = Decimal(amount) * Decimal(FEE_BPS) / Decimal(10000)
    return max(bankers(raw), FEE_MIN)


def vat_on_fee(fee: int) -> int:
    return bankers(Decimal(fee) * VAT)


def load_art():
    ledger = json.loads((ART / "ledger.json").read_text())
    rejects = json.loads((ART / "rejects.json").read_text())
    summary = json.loads((ART / "summary.json").read_text())
    return ledger, rejects, summary


def load_gold():
    ledger = json.loads((GOLD / "ledger.json").read_text())
    rejects = json.loads((GOLD / "rejects.json").read_text())
    summary = json.loads((GOLD / "summary.json").read_text())
    return ledger, rejects, summary


def intent_books(ledger: dict) -> dict[str, list[tuple[str, int]]]:
    out: dict[str, list[tuple[str, int]]] = {}
    for e in ledger["entries"]:
        lines = [(ln["account"], int(ln["cents"])) for ln in e["lines"]]
        out.setdefault(e["intent_id"], []).extend(lines)
    return out


def accepted_pairs(ledger: dict) -> set[tuple[str, str]]:
    return {(e["intent_id"], e["trans_id"]) for e in ledger["entries"]}


def reject_triples(rejects: dict) -> set[tuple[str, str, str]]:
    s = set()
    for r in rejects["rejects"]:
        s.add((r["intent_id"], r["reason"], r.get("trans_id") or ""))
    return s


@pytest.fixture(scope="module")
def art():
    assert (ART / "ledger.json").is_file()
    assert (ART / "rejects.json").is_file()
    assert (ART / "summary.json").is_file()
    return load_art()


@pytest.fixture(scope="module")
def gold():
    return load_gold()


def test_output_files_exist():
    assert (ART / "ledger.json").is_file()
    assert (ART / "rejects.json").is_file()
    assert (ART / "summary.json").is_file()
    assert (ART / "audit.ndjson").is_file()


def test_accounts_sum_to_zero(art):
    ledger, _, _ = art
    total = sum(int(v) for v in ledger["accounts"].values())
    assert total == 0


def test_each_entry_lines_sum_to_zero(art):
    ledger, _, _ = art
    assert ledger["entries"], "expected posted entries"
    for e in ledger["entries"]:
        s = sum(int(ln["cents"]) for ln in e["lines"])
        assert s == 0, e["entry_id"]


def test_escrow_ends_flat(art):
    ledger, _, _ = art
    assert int(ledger["accounts"]["escrow"]) == 0


def test_cash_equals_liability_credits(art):
    ledger, _, _ = art
    a = ledger["accounts"]
    cash = int(a["cash"])
    vendor = -int(a["vendor_payable"])
    fee = -int(a["fee_income"])
    vat = -int(a["vat_payable"])
    assert cash == vendor + fee + vat


def test_summary_accounts_match_ledger(art):
    ledger, _, summary = art
    a = ledger["accounts"]
    assert summary["cash_cents"] == a["cash"]
    assert summary["escrow_cents"] == a["escrow"]
    assert summary["vendor_cents"] == -a["vendor_payable"]
    assert summary["fee_cents"] == -a["fee_income"]
    assert summary["vat_cents"] == -a["vat_payable"]
    assert summary["final_fence"] == ledger["fence"]
    assert summary["entry_count"] == len(ledger["entries"])


def test_as_of_and_fence_match_gold(art, gold):
    ledger, _, summary = art
    g_ledger, _, g_sum = gold
    assert ledger["as_of"] == g_ledger["as_of"]
    assert ledger["fence"] == g_ledger["fence"] == 8
    assert summary["wal_replayed"] == g_sum["wal_replayed"] == 4
    assert summary["pending_expired"] == g_sum["pending_expired"] == 1


def test_account_totals_match_gold(art, gold):
    ledger, _, _ = art
    g_ledger, _, _ = gold
    assert ledger["accounts"] == g_ledger["accounts"]


def test_summary_counts_match_gold(art, gold):
    _, _, summary = art
    _, _, g_sum = gold
    for k in (
        "accepted_intents",
        "rejected",
        "cash_cents",
        "vendor_cents",
        "fee_cents",
        "vat_cents",
        "entry_count",
        "sqlite_replayed",
        "feed_frames",
        "wal_replayed",
    ):
        assert summary[k] == g_sum[k], k


def test_accepted_intent_trans_pairs_match_gold(art, gold):
    ledger, _, _ = art
    g_ledger, _, _ = gold
    assert accepted_pairs(ledger) == accepted_pairs(g_ledger)


def test_reject_intent_reason_trans_match_gold(art, gold):
    _, rejects, _ = art
    _, g_rej, _ = gold
    assert reject_triples(rejects) == reject_triples(g_rej)


def test_reject_sources_match_gold(art, gold):
    _, rejects, _ = art
    _, g_rej, _ = gold
    got = {(r["intent_id"], r["reason"], r["source"]) for r in rejects["rejects"]}
    exp = {(r["intent_id"], r["reason"], r["source"]) for r in g_rej["rejects"]}
    assert got == exp


def test_intent_0001_happy_stk_fee_floor(art):
    ledger, _, _ = art
    books = intent_books(ledger)
    assert "int_0001" in books
    c = Counter(books["int_0001"])
    assert c[("cash", 10000)] == 1
    assert c[("fee_income", -120)] == 1
    assert c[("vat_payable", -19)] == 1
    assert c[("vendor_payable", -9861)] == 1
    fee, vat = fee_cents(10000), vat_on_fee(fee_cents(10000))
    assert fee == 120 and vat == 19


def test_intent_0002_callback_exactly_47s_is_kept(art):
    ledger, rejects, _ = art
    assert "int_0002" in intent_books(ledger)
    reasons = [r["reason"] for r in rejects["rejects"] if r["intent_id"] == "int_0002"]
    assert "timeout" not in reasons
    c = Counter(intent_books(ledger)["int_0002"])
    assert c[("fee_income", -128)] == 1
    assert c[("vat_payable", -20)] == 1


def test_intent_0003_callback_after_47s_times_out(art):
    ledger, rejects, _ = art
    assert "int_0003" not in intent_books(ledger)
    hits = [r for r in rejects["rejects"] if r["intent_id"] == "int_0003"]
    assert any(r["reason"] == "timeout" for r in hits)
    assert any(r.get("trans_id") == "TO47001LATE" for r in hits)


def test_intent_0004_stale_fence_dropped(art):
    ledger, rejects, _ = art
    assert "int_0004" not in intent_books(ledger)
    hits = [r for r in rejects["rejects"] if r["intent_id"] == "int_0004"]
    assert any(r["reason"] == "stale_fence" and r.get("trans_id") == "STALEFENCE6" for r in hits)


def test_duplicate_trans_id_second_intent_rejected(art):
    ledger, rejects, _ = art
    books = intent_books(ledger)
    assert "int_0005" in books
    assert "int_0006" not in books
    hits = [r for r in rejects["rejects"] if r["intent_id"] == "int_0006"]
    assert any(r["reason"] == "duplicate_trans_id" and r.get("trans_id") == "DUPTRANS001" for r in hits)


def test_stk_failed_result_code_not_booked(art):
    ledger, rejects, _ = art
    assert "int_0007" not in intent_books(ledger)
    hits = [r for r in rejects["rejects"] if r["intent_id"] == "int_0007"]
    assert any(r["reason"] == "stk_failed" and r.get("trans_id") == "FAIL1032AAA" for r in hits)


def test_wal_replay_then_inbox_duplicate_intent(art):
    ledger, rejects, _ = art
    books = intent_books(ledger)
    assert "int_0008" in books
    c = Counter(books["int_0008"])
    assert c[("cash", 50100)] == 1
    hits = [r for r in rejects["rejects"] if r["intent_id"] == "int_0008"]
    assert any(r["reason"] == "duplicate_intent" for r in hits)


def test_c2b_csv_nairobi_amount_int_0009(art):
    ledger, _, _ = art
    books = intent_books(ledger)
    assert "int_0009" in books
    c = Counter(books["int_0009"])
    assert c[("cash", 25000)] == 1
    fee, vat = fee_cents(25000), vat_on_fee(fee_cents(25000))
    assert c[("fee_income", -fee)] == 1
    assert c[("vat_payable", -vat)] == 1


def test_intent_0010_expired_at_rebuild(art):
    ledger, rejects, summary = art
    assert "int_0010" not in intent_books(ledger)
    hits = [r for r in rejects["rejects"] if r["intent_id"] == "int_0010"]
    assert any(r["reason"] == "timeout" and r["source"] == "as_of" for r in hits)
    assert summary["pending_expired"] == 1


def test_second_callback_same_intent_duplicate(art):
    ledger, rejects, _ = art
    trans = {e["trans_id"] for e in ledger["entries"]}
    assert "TWOSHOTS001" in trans
    assert "TWOSHOTS002" not in trans
    hits = [r for r in rejects["rejects"] if r.get("trans_id") == "TWOSHOTS002"]
    assert any(r["reason"] == "duplicate_intent" for r in hits)


def test_garbage_jsonl_line_is_bad_record(art):
    _, rejects, _ = art
    hits = [r for r in rejects["rejects"] if r["reason"] == "bad_record"]
    assert len(hits) == 1
    assert hits[0]["intent_id"] == "?"
    assert hits[0]["source"] == "stk-2026-03-11.jsonl:18"


def test_callback_amount_is_ignored_for_stk(art):
    # int_0001 callback amount was 999999; booked amount must stay 10000
    ledger, _, _ = art
    c = Counter(intent_books(ledger)["int_0001"])
    assert c[("cash", 10000)] == 1
    assert c[("cash", 999999)] == 0


def test_no_torn_wal_payload_leaks_into_ledger(art):
    ledger, _, _ = art
    for e in ledger["entries"]:
        assert e["intent_id"] != "int_torn"
        assert "int_torn" not in e.get("intent_id", "")


def test_two_legs_then_optional_reversal(art, gold):
    ledger, _, summary = art
    _, _, g = gold
    by = Counter(e["intent_id"] for e in ledger["entries"])
    assert by["int_0001"] == 2
    assert by["int_0008"] == 2
    assert by["int_0014"] == 4  # booked then reversed
    assert summary["entry_count"] == g["entry_count"]


def test_c2b_reversal_and_ghost(art):
    _, rejects, _ = art
    assert any(r["reason"] == "already_reversed" and r.get("trans_id") == "NC4M68AB7H8091" for r in rejects["rejects"])
    assert any(r["reason"] == "unknown_trans_id" and r.get("trans_id") == "NOSUCHTRANS9" for r in rejects["rejects"])


def test_feed_frames_were_applied(art, gold):
    _, rejects, summary = art
    _, _, g = gold
    assert summary["feed_frames"] == g["feed_frames"]
    assert summary["feed_frames"] > 20
    assert any(r["source"].startswith("feed#") for r in rejects["rejects"])


def test_sqlite_checkpoint_skips_duplicate_wal(art):
    ledger, _, summary = art
    assert summary["sqlite_replayed"] == 2
    assert summary["wal_replayed"] == 4
    n = sum(1 for e in ledger["entries"] if e["intent_id"] == "int_0008")
    assert n == 2


def test_second_wal_file_is_replayed(art):
    ledger, rejects, summary = art
    assert "int_0015" in intent_books(ledger)
    c = Counter(intent_books(ledger)["int_0015"])
    assert c[("cash", 12000)] == 1
    hits = [r for r in rejects["rejects"] if r["intent_id"] == "int_0015"]
    assert any(r["reason"] == "duplicate_intent" for r in hits)


def test_feed_bad_mac_stops_the_stream(art):
    ledger, rejects, _ = art
    assert "SKIPAFTERMAC" not in {e["trans_id"] for e in ledger["entries"]}
    assert any(r["reason"] == "bad_mac" and r["source"] == "feed:mac" for r in rejects["rejects"])


def test_entry_ids_are_sha256_prefix(art):
    ledger, _, _ = art
    for e in ledger["entries"]:
        assert len(e["entry_id"]) == 16
        int(e["entry_id"], 16)


def test_audit_log_has_decisions(art):
    lines = (ART / "audit.ndjson").read_text().splitlines()
    assert len(lines) >= 50
    row = json.loads(lines[0])
    assert "decision" in row and "source" in row


def test_till_b_uses_110bps_floor_200(art):
    ledger, _, _ = art
    c = Counter(intent_books(ledger)["int_0011"])
    assert c[("cash", 10000)] == 1
    assert c[("fee_income", -200)] == 1
    assert c[("vat_payable", -32)] == 1
    assert c[("vendor_payable", -9768)] == 1


def test_csv_thousands_comma_amount(art):
    ledger, _, _ = art
    c = Counter(intent_books(ledger)["int_0012"])
    assert c[("cash", 125000)] == 1
    fee = fee_cents(125000)
    vat = vat_on_fee(fee)
    assert c[("fee_income", -fee)] == 1
    assert c[("vat_payable", -vat)] == 1


def test_gzip_nclog_frame_books_intent_amount(art):
    ledger, _, _ = art
    c = Counter(intent_books(ledger)["int_0013"])
    assert c[("cash", 20000)] == 1
    assert c[("cash", 888888)] == 0


def test_fee_bankers_rounding_on_15000(art):
    assert fee_cents(15000) == 128
    ledger, _, _ = art
    c = Counter(intent_books(ledger)["int_0002"])
    assert c[("fee_income", -128)] == 1


def test_reject_reason_histogram_matches_gold(art, gold):
    _, rejects, _ = art
    _, g_rej, _ = gold
    got = Counter(r["reason"] for r in rejects["rejects"])
    exp = Counter(r["reason"] for r in g_rej["rejects"])
    assert got == exp
