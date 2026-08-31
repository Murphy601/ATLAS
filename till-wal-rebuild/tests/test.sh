#!/usr/bin/env bash
mkdir -p /logs/verifier
chmod 700 /logs/verifier
printf '0' > /logs/verifier/reward.txt
set +e
pytest /tests/test_ledger.py -q --ctrf /logs/verifier/ctrf.json
rc=$?
set -e
if [ "$rc" -eq 0 ]; then
  printf '1' > /logs/verifier/reward.txt
else
  printf '0' > /logs/verifier/reward.txt
fi
exit 0
