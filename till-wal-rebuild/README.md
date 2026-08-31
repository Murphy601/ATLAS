Crash dump for the NyotaClear till writer on clear-prod-3.

I generated `environment/data` myself: 136 intents, csv, jsonl, HMAC nclog (some frames NCZG+gzip), a torn WAL, posted.db. The leftover nclog bytes are in `environment/feed/payload.nclog`. The image starts `/opt/nyota-feed/serve.py` from its entrypoint so :9377 is up even if CMD is overwritten. To refresh golden files, run `solution/settle.py` with `NYOTA_DATA` pointed at `environment/data`, `NYOTA_OUT` at a temp dir, and `NYOTA_FEED_FILE` at that payload, then copy the four outputs over `tests/golden`. Do not edit golden by hand.

Disk nclog is the first 12 frames. The rest is on the feed. posted.db already has the two WAL legs, so replaying both without skipping double-books int_0008. Till 882211 is 110 bps, floor 200. CSV `1,250.00` is 125000 cents.

`cheat/fake_balanced.py` writes empty books that still look like the schema. That dies on feed_frames, sqlite, the reversal, and till B.

`instruction.md` is the only spec. `SHIFT_NOTES.txt` is gossip. Do not ship a second copy of the rules on disk.
