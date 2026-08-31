NyotaClear's till writer on clear-prod-3 died mid-shift. Rebuild the journal from what's still on disk. "Now" is the timestamp in `/app/data/as_of`. Do not use the machine clock.

You need `/app/data/writer_fence`, `/app/data/pending_intents.json`, `/app/data/crash_wal/writer.wal`, and everything under `/app/data/inbox/`. When you're done, write `/app/output/ledger.json`, `/app/output/rejects.json`, and `/app/output/summary.json`.

The fence file is a single integer. Inbox records with a smaller `fence` came from a writer we already kicked out — don't book them, reject with `stale_fence`. A higher fence means that's the new number; the file on disk can lag. Replay the WAL first, then the inbox, then expire whatever is still sitting in pending.

WAL and `handoff.nclog` are framed the same way: 4-byte big-endian length, then that many bytes of UTF-8 JSON. If you run out of bytes mid-frame, it's torn. Drop that record and stop. Don't go looking for the next one. Complete WAL records look like `{"type":"entry", ...}` with `intent_id`, `trans_id`, `occurred_at`, `lines`, and sometimes `fence`. Each complete record goes on the books. `wal_replayed` is how many of those you replayed. Not how many intents.

Inbox is three formats. `stk-2026-03-11.jsonl` is one object per line. A line that isn't JSON is a reject: reason `bad_record`, `intent_id` `"?"`. `mpesa_c2b.csv` header is `Receipt,Time,AmountKES,Till,TransID,Intent,Fence,Type`. CSV `Time` is Africa/Nairobi with no zone suffix. jsonl and nclog timestamps are already UTC with a `Z`. After parsing, apply inbox records by `occurred_at` ascending, then `source`, then the per-file sequence. `source` is `basename:line` for jsonl/csv (1-based; csv line 1 is the header, first data row is 2), `basename#n` for the nth complete nclog record, and `as_of` when you expire leftovers. Sequence is that line number or n.

Pending STK intents live in `pending_intents.json`. On a successful `stk_callback`, book the intent's `amount_cents`. Ignore the amount on the callback. That field has been wrong before. `result_code` other than 0 is `stk_failed` and the intent is done. If the callback is more than 47.000 seconds after `opened_at`, that's `timeout`. Equal to 47.000 seconds still counts. C2B books the CSV amount: `AmountKES` times 100, half-even to a cent. STK for an intent you don't have is `unknown_intent`. Once an intent or a `trans_id` is booked (WAL counts), a second hit is `duplicate_intent` or `duplicate_trans_id`. After the inbox, anything still pending that has been open more than 47.000 seconds vs `as_of`, and that you haven't already rejected, is `timeout` with source `as_of`.

Fee is 85 bps of the booked amount, half-even to a cent, never below 120 cents. VAT is 16% of that fee, same rounding. Not 16% of the till amount. Vendor net is amount minus fee minus VAT. Each successful payment is two entries. Cents are signed, debits positive, lines in an entry sum to 0:

cash +amount / escrow -amount, then escrow +amount / vendor_payable -net / fee_income -fee / vat_payable -vat.

`ledger.json` has `as_of` (UTC, milliseconds, trailing Z, same instant as the data file), `fence` when you finish, `accounts` for cash, escrow, vendor_payable, fee_income, vat_payable, and `entries` with `entry_id` (any unique string), `intent_id`, `trans_id`, `occurred_at`, `lines` as `{account, cents}`. `rejects.json` is `{"rejects":[...]}` with `intent_id`, `reason`, `source`, and `trans_id` when you have one. `summary.json` wants `accepted_intents`, `rejected`, `cash_cents`, `escrow_cents`, `vendor_cents` (positive money to vendors), `fee_cents`, `vat_cents`, `pending_expired`, `wal_replayed`, `final_fence`, `entry_count`. Vendor/fee/vat in the summary are magnitudes, not the signed account numbers.

`SHIFT_NOTES.txt` is from whoever was on call. Gossip. Not spec.

You have 10800 seconds to complete this task. Do not cheat by using online solutions or hints specific to this task.
