"""Sends many actions and never reads a reply, so the evaluator's pipe to it fills up."""

import json
import sys
import time

line = json.dumps({"action": "list_records", "args": {"table": "ledger"}})
for _ in range(60):
    sys.stdout.write(line + "\n")
sys.stdout.flush()
time.sleep(600)
