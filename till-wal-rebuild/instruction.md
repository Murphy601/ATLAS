NyotaClear's till writer on clear-prod-3 died mid-shift. I need you to rebuild the journal from what's still on disk. Use the timestamp in `/app/data/as_of` as "now" — don't use the actual clock.

You'll want `/app/data/writer_fence`, `/app/data/pending_intents.json`, `/app/data/crash_wal/writer.wal`, and everything under `/app/data/inbox/`. Write three files when you're done: `/app/output/ledger.json`, `/app/output/rejects.json`, and `/app/output/summary.json`.

The fence file is one integer. Treat any inbox record with a smaller `fence` as a fenced-out writer: don't book it, reject it with `stale_fence`. If you see a higher fence, that's the new number; the file on disk can lag. Replay the WAL first, then the inbox, then expire whatever is still pending.

WAL and `handoff.nclog` use the same framing: 4-byte big-endian length, then that many bytes of UTF-8 JSON. If you run out of bytes in the middle of a frame, it's torn. Drop that record and stop reading the file. Don't hunt past it. Complete WAL records look like `{"type":"entry", ...}` with `intent_id`, `trans_id`, `occurred_at`, `lines`, sometimes `fence`. Put each complete record on the books. `wal_replayed` is how many of those you replayed, not how many intents that was.

Inbox is a mess of three formats. `stk-2026-03-11.jsonl` is one object per line; a line that isn't JSON is a reject (`bad_record`, `intent_id` `"?"`). `mpesa_c2b.csv` has the header `Receipt,Time,AmountKES,Till,TransID,Intent,Fence,Type`. CSV `Time` is Africa/Nairobi and it does not have a zone suffix. jsonl and nclog timestamps are UTC with `Z`. Once it's all parsed, apply inbox records by `occurred_at` ascending, then `source`, then the per-file sequence. `source` should be `basename:line` for jsonl/csv (lines start at 1; csv line 1 is the header, so the first data row is 2), `basename#n` for the nth complete nclog record, and `as_of` when you expire leftovers. Sequence is that line number or n.

Pending STK intents are in `pending_intents.json`. On a successful `stk_callback`, book the intent's `amount_cents`. I mean it — ignore the amount on the callback. We've had garbage in that field. `result_code` other than 0 is `stk_failed` and the intent is finished. If the callback comes more than 47.000 seconds after `opened_at`, that's `timeout`. Equal to 47.000 seconds is still in time. C2B books the CSV amount (`AmountKES` * 100, half-even to a cent). An STK callback for an intent you don't have is `unknown_intent`. Once you've booked an intent or a `trans_id` (WAL counts), a second hit is `duplicate_intent` or `duplicate_trans_id`. After the inbox pass, anything still pending that has been open more than 47.000 seconds vs `as_of`, and that you haven't already rejected, gets `timeout` with source `as_of`.

Fee is 85 bps of the booked amount, half-even to a cent, then never below 120 cents. VAT is 16% of that fee, same rounding. Not 16% of the till amount. Vendor net is amount minus fee minus VAT. Every successful payment is two entries. Cents are signed, debits positive, and the lines in an entry have to sum to 0:

cash +amount / escrow -amount, then escrow +amount / vendor_payable -net / fee_income -fee / vat_payable -vat.

`ledger.json`: `as_of` (UTC, milliseconds, trailing Z, same instant as the data file), `fence` after you're done, `accounts` with cash, escrow, vendor_payable, fee_income, vat_payable, and `entries` with `entry_id` (any unique string), `intent_id`, `trans_id`, `occurred_at`, `lines` as `{account, cents}`. `rejects.json` is `{"rejects":[...]}` each with `intent_id`, `reason`, `source`, and `trans_id` when you have one. `summary.json` needs `accepted_intents`, `rejected`, `cash_cents`, `escrow_cents`, `vendor_cents` (positive money to vendors), `fee_cents`, `vat_cents`, `pending_expired`, `wal_replayed`, `final_fence`, `entry_count`. Those vendor/fee/vat summary fields are magnitudes, not the signed T-account numbers.

There's a `SHIFT_NOTES.txt` from whoever was on call. Treat it as gossip, not spec.

You have 10800 seconds to complete this task. Do not cheat by using online solutions or hints specific to this task.
