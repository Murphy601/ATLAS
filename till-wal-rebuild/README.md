Crash dump for the NyotaClear till writer on clear-prod-3.

I generated `environment/data` (136 intents, csv, jsonl, HMAC nclog with some NCZG gzip frames, torn WAL, posted.db, writer.conf) and `environment/feed/payload.nclog`. The main image ENTRYPOINT starts the paginated feed on :9377 so Harbor's `sleep infinity` CMD still leaves the daemon up. `tests/golden` is `solution/settle.py` with `NYOTA_FEED_FILE` pointed at that payload (same bytes the HTTP pages concatenate to). If you change the dump, rerun the solver the same way and replace golden.

Disk nclog is only the first 12 frames; the rest is on the feed. posted.db already has the two WAL legs so a naive double replay would double-book int_0008. Till 882211 is 110 bps / min 200. CSV `1,250.00` is 125000 cents.

`cheat/fake_balanced.py` still writes empty books. That cannot survive the feed_frames / sqlite / reversal / till-B checks.
