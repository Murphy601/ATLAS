Crash dump for the NyotaClear till writer on clear-prod-3.

I generated `environment/data` myself. The leftover nclog bytes are in `environment/feed/payload.nclog`. The image starts the feed on :9377 from its entrypoint. `/app/writer/rebuild.py` is a stale on-box copy; it must not match golden. To refresh golden, run `solution/settle.py` with `NYOTA_DATA`, `NYOTA_OUT`, and `NYOTA_FEED_FILE` pointed at the payload, then copy the four outputs over `tests/golden`.

Two WAL files in `crash_wal`. A bad MAC sits in the middle of the feed stream; frames after it must not book. Till 882211 is 110 bps, floor 200.

`instruction.md` is the spec. `SHIFT_NOTES.txt` is gossip.
