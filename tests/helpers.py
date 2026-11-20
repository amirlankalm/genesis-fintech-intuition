"""Shared builders for tests. The teaching episode's key is hard-coded here on purpose:
it is the hand calculation, independent of the code that derives truth."""

from __future__ import annotations

from typing import Any

FAULTY, CLEAN = "teaching_b", "teaching_b_clean"
FAULTY_ID, CLEAN_ID = "ep-4c1f09", "ep-a27d35"
EVIDENCE = ["D31", "D44", "L11"]  # invoice document, payment document, the allocation row


def finding(**overrides: Any) -> dict[str, Any]:
    """The one correct finding for the faulty teaching episode, with optional overrides."""
    base = {
        "type": "payment_allocation",
        "affected_ids": ["I7", "P9"],
        "claimed_amount_minor": 100_000,
        "currency": "KZT",
        "evidence_ids": list(EVIDENCE),
        "explanation": "P9 covers I7 in full (250,000 required); only 150,000 was allocated.",
    }
    return {**base, **overrides}


def submit_action(findings: list[dict[str, Any]], episode_id: str = FAULTY_ID) -> dict[str, Any]:
    return {"action": "submit", "args": {"findings": {"episode_id": episode_id, "findings": findings}}}


def list_action(table: str = "ledger", **args: Any) -> dict[str, Any]:
    return {"action": "list_records", "args": {"table": table, **args}}
