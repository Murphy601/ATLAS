NyotaClear till-journal rebuild after a torn WAL on clear-prod-3.

`environment/data` is a synthetic crash dump (132 intents, csv + jsonl + two length-prefixed binaries). `tests/golden/*.json` is the frozen output of `solution/settle.py` run against that dump; do not hand-edit the golden files — regenerate them from the solver if the corpus changes. Bulk STK rows stay on fence 7 and the fence-8 bump is late in `occurred_at` order so a higher fence does not mass-stale earlier records. Rebuild expiry only fires for intents that were never rejected, so pinned cases do not stack `stale_fence` and `timeout` on the same intent.

`cheat/` is a probe, not part of the solver: `fake_balanced.py` writes a zeroed but schema-shaped ledger. The tests reject that without a full inbox replay.
