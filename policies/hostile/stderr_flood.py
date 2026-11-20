"""Writes a lot to stderr, then submits nothing."""

import json
import sys

reset = json.loads(sys.stdin.readline())
chunk = "e" * 1_048_576
for _ in range(64):
    sys.stderr.write(chunk)
episode_id = reset["observation"]["manifest"]["episode_id"]
print(json.dumps({"action": "submit", "args": {"findings": {"episode_id": episode_id, "findings": []}}}), flush=True)
