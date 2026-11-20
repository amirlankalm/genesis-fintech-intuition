"""Submits, then streams maximal lines for as long as it is allowed to."""

import json
import sys

reset = json.loads(sys.stdin.readline())
episode_id = reset["observation"]["manifest"]["episode_id"]
print(json.dumps({"action": "submit", "args": {"findings": {"episode_id": episode_id, "findings": []}}}), flush=True)
line = "z" * 262_000 + "\n"
try:
    while True:
        sys.stdout.write(line)
except BrokenPipeError:
    pass
