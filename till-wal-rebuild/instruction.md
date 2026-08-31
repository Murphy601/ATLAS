NyotaClear's till writer on clear-prod-3 died mid-shift. Rebuild the journal. "Now" is `/app/data/as_of`. Do not use the machine clock.

`/app/data/writer.conf` is the rebuild contract — replay order, nclog framing, feed protocol, CSV, STK window, fees, outputs. `/app/data/tills.json` is per-till timezone and fee/VAT. `/app/data/SHIFT_NOTES.txt` is gossip. You will also need `writer_fence`, `pending_intents.json`, `posted.db`, `crash_wal/writer.wal`, `nclog.key`, `feed.token`, and `inbox/`.

The nclog tail never flushed to disk. Pull it from the live feed using the protocol in writer.conf: token header, paginated JSON, base64 pages concatenated into one HMAC byte stream. Try `http://127.0.0.1:9377` first; a sidecar may also answer at `http://feed:9377`. If :9377 is dead, start `/opt/nyota-feed/serve.py`. A single GET is not the whole tail.

When you are done write `/app/output/ledger.json`, `/app/output/rejects.json`, `/app/output/summary.json`, and `/app/output/audit.ndjson`.

Replay posted.db first, then the WAL, then the merged inbox (disk + feed), then expire pending. WAL is still old length-prefixed JSON (`type=entry`). If a WAL frame repeats a `trans_id` already in the checkpoint, skip booking it but still count it in `wal_replayed`. `sqlite_replayed` is how many posted rows you applied.

nclog frames are not length-only: 4-byte big-endian length of the payload, then 32-byte HMAC-SHA256 of that payload using the raw bytes in `nclog.key`, then the payload. If the payload starts with `NCZG`, the rest is gzip of the JSON; the HMAC covers the `NCZG` prefix too. Bad HMAC: stop that stream, reject `bad_mac` with source `handoff.nclog:mac` or `feed:mac`, and do not skip ahead. A torn length/payload stops the stream with no extra reject. Feed frames use source `feed#n` (n from 1 over the concatenated stream). Disk nclog is `handoff.nclog#n`.

Inbox sort is `occurred_at`, then `source`, then sequence. jsonl is one object per line; a broken line is `bad_record` / intent_id `"?"`. CSV header `Receipt,Time,AmountKES,Till,TransID,Intent,Fence,Type`. `Time` is the till timezone. `AmountKES` is KES with optional thousands commas. `Type=C2B` books the CSV amount on that till's fee schedule. `Type=REVERSAL` looks up `TransID`: unknown is `unknown_trans_id`; already reversed is `already_reversed`; otherwise post the negated legs of whatever was booked for that TransID (do not recompute fee).

STK books the intent amount and ignores the callback amount. Use the pending intent's till for fees. `result_code` != 0 is `stk_failed`. Callback more than 47.000s after `opened_at` is `timeout`; equal to 47.000s still counts. Duplicates are `duplicate_intent` / `duplicate_trans_id`. Fence: smaller than current is `stale_fence`; a higher fence becomes current. Expire leftover pending vs `as_of` the same way, source `as_of`.

Fee and VAT come from `tills.json` for that till (bps of amount, half-even, never under `fee_min_cents`; VAT is `vat_rate` of that fee, half-even). Two legs per success, debits positive, lines sum to 0. `entry_id` is the first 16 hex chars of sha256 of `{"i":intent_id,"t":trans_id,"o":occurred_at,"l":[[account,cents],...]}` with no spaces.

`audit.ndjson` is one JSON object per decision, keys `source`, `decision` (`booked` or `reject`), `reason`, `intent_id`, `trans_id`. `summary.json` also needs `sqlite_replayed` and `feed_frames` (complete HMAC payloads parsed from the concatenated feed, not a trailing torn stub). Other summary fields: `accepted_intents`, `rejected`, `cash_cents`, `escrow_cents`, `vendor_cents`, `fee_cents`, `vat_cents`, `pending_expired`, `wal_replayed`, `final_fence`, `entry_count`.

You have 10800 seconds to complete this task. Do not cheat by using online solutions or hints specific to this task.
