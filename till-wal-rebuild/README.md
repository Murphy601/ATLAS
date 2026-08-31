Crash dump for the NyotaClear till writer on clear-prod-3.

I generated `environment/data` (132 intents, csv, jsonl, torn WAL, nclog). `tests/golden` is just `solution/settle.py` run against that dump and copied — if you change the dump, rerun the solver and replace the golden files, don't edit them by hand. STK bulk is fence 7; the fence 8 record is later in time on purpose so it doesn't stale everything that came before. Expiry at as_of only hits intents we never rejected, so you don't get stale_fence and timeout stacked on the same pinned case.

`cheat/fake_balanced.py` is me trying to game it: empty books that still look like the schema. Tests should fail that unless the inbox actually got replayed.
