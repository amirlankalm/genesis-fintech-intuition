"""Submits, then keeps sending actions and a second submission."""

import json
import sys

reset = json.loads(sys.stdin.readline())
episode_id = reset["observation"]["manifest"]["episode_id"]
submit = json.dumps({"action": "submit", "args": {"findings": {"episode_id": episode_id, "findings": []}}})
listing = json.dumps({"action": "list_records", "args": {"table": "ledger"}})
try:
    for line in (submit, listing, submit, listing):
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
except BrokenPipeError:
    pass
