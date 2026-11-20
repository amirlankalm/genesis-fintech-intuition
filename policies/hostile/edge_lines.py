"""Probes the size and nesting bounds exactly, then submits nothing."""

import json
import sys

reset = json.loads(sys.stdin.readline())
episode_id = reset["observation"]["manifest"]["episode_id"]


def send(raw: str) -> dict:
    sys.stdout.write(raw + "\n")
    sys.stdout.flush()
    return json.loads(sys.stdin.readline())


def padded(size: int) -> str:
    """A get_record action whose JSON line is exactly `size` bytes."""
    empty = json.dumps({"action": "get_record", "args": {"table": "ledger", "id": ""}})
    return json.dumps({"action": "get_record", "args": {"table": "ledger", "id": "x" * (size - len(empty))}})


deep = "[" * 991 + "]" * 991
unicode_heavy = json.dumps({"action": "get_document", "args": {"doc_id": "\u00e9" * 50_000}}, ensure_ascii=False)
replies = [
    send(padded(262_144)),
    send(padded(262_145)),
    send(deep),
    send("[" * 17 + "]" * 17),
    send(unicode_heavy),
    send("null"),
    send(""),
]
send(json.dumps({"action": "submit", "args": {"findings": {"episode_id": episode_id, "findings": []}}}))
sys.stderr.write(json.dumps([reply["observation"].get("error", {}).get("code") for reply in replies]))
