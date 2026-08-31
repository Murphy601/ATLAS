A plausible cheat is to emit a balanced zero ledger, or to replay only the two WAL records and skip the inbox.

Pinned intents, cash totals, and reject sources will not match if the inbox is skipped. Empty-but-balanced books fail the posted-entry checks.
