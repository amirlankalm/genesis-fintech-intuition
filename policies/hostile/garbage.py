"""Sends undecodable lines and an oversized line, none of them a submission, then a valid empty submit."""

import json
import sys

reset = json.loads(sys.stdin.readline())
episode_id = reset["observation"]["manifest"]["episode_id"]


def send(raw: str) -> dict:
    sys.stdout.write(raw + "\n")
    sys.stdout.flush()
    return json.loads(sys.stdin.readline())


replies = [
    send("this is not json"),
    send("[1, 2"),
    send('{"action": "list_records", "args": {"table": "ledger"}, "args": {}}'),  # duplicate key
    send('{"action": "get_document", "args": {"doc_id": NaN}}'),
    send("x" * 300_000),
    send(json.dumps({"action": "submit", "args": {"findings": {"episode_id": episode_id, "findings": []}}})),
]
sys.stderr.write(json.dumps([reply["observation"].get("error", {}).get("code") for reply in replies]))
