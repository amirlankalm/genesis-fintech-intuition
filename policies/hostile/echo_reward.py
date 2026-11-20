"""Submits nothing and reports on stderr exactly what the final message contained."""

import json
import sys

reset = json.loads(sys.stdin.readline())
episode_id = reset["observation"]["manifest"]["episode_id"]
sys.stdout.write(
    json.dumps({"action": "submit", "args": {"findings": {"episode_id": episode_id, "findings": []}}}) + "\n"
)
sys.stdout.flush()
sys.stderr.write(sys.stdin.readline())
