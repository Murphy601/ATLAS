A plausible cheat is to emit a balanced zero ledger, or to replay only the two WAL records and skip the inbox.

Pinned intents, cash totals, till-B fees, gzip nclog, comma CSV amounts, and reject sources will not match if the inbox or feed is skipped. Empty-but-balanced books fail the posted-entry checks. A single unauthenticated GET to the feed is not enough.
