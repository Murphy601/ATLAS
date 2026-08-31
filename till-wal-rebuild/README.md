Crash dump for the NyotaClear till writer on clear-prod-3.

I generated `environment/data` myself — 136 intents, csv, jsonl, HMAC nclog (some frames NCZG+gzip), a torn WAL, posted.db — and the leftover nclog bytes live in `environment/feed/payload.nclog`. The image starts the feed process on :9377 from its entrypoint so the platform can overwrite CMD and the daemon is still there. `tests/golden` is just `solution/settle.py` pointed at that payload with `NYOTA_FEED_FILE`; same bytes the HTTP pages concatenate to. If you change the dump, rerun the solver that way and replace golden. Don't edit the golden files by hand.

Disk nclog is the first 12 frames. Everything after that is on the feed. posted.db already has the two WAL legs, so replaying both without skipping double-books int_0008. Till 882211 is 110 bps, floor 200. CSV `1,250.00` is 125000 cents.

`cheat/fake_balanced.py` is me trying to game it: empty books that still look like the schema. That dies on feed_frames / sqlite / the reversal / till B.

Do not put a second copy of the instruction on disk. `instruction.md` is the spec; `SHIFT_NOTES.txt` is gossip.
