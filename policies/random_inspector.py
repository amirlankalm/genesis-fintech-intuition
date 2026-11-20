"""Seeded random inspector: random tool calls, then a random small submission.

Its guesses are drawn from what it happened to see, evidence rows included, so a lucky
hit is possible. If this policy ever scores well, the episode has a shortcut.

Usage: random_inspector.py <seed>. The policy's randomness is its own and is
recorded with the run; the environment has none.
"""

from __future__ import annotations

import random
import sys

from _client import Session

TABLES = ("ledger", "invoices", "payments", "fx")


def pick(rng: random.Random, items: list):
    return items[int(rng.random() * len(items))]


def main() -> None:
    rng = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 0)  # noqa: S311 - a reproducible baseline, not a secret
    session = Session()
    seen: dict[str, list[dict]] = {table: [] for table in TABLES}
    for _ in range(3 + int(rng.random() * 6)):
        if session.done or session.steps_remaining <= 1:
            break
        roll = rng.random()
        documents = seen["invoices"] + seen["payments"]
        if roll < 0.6 or not documents:
            table = pick(rng, list(TABLES))
            observation = session.act("list_records", table=table, limit=1 + int(rng.random() * 50))
            seen[table].extend(observation.get("records", []))
        elif roll < 0.9:
            session.act("get_document", doc_id=pick(rng, documents)["doc_id"])
        else:
            session.act("get_record", table="ledger", id=f"X{int(rng.random() * 1000)}")  # a guess
    findings = []
    if seen["invoices"] and seen["payments"]:
        for _ in range(int(rng.random() * 3)):
            invoice, payment = pick(rng, seen["invoices"]), pick(rng, seen["payments"])
            rows = [row["row_id"] for row in seen["ledger"]]
            evidence = [invoice["doc_id"], payment["doc_id"]]
            evidence += [pick(rng, rows) for _ in range(int(rng.random() * 4))] if rows else []
            amounts = [payment["amount_minor"], invoice["total_minor"]]
            amounts += [row["debit_minor"] or row["credit_minor"] for row in seen["ledger"]]
            findings.append({
                "type": pick(rng, session.manifest["issue_types"]),
                "affected_ids": [invoice["invoice_id"], payment["payment_id"]],
                "claimed_amount_minor": pick(rng, amounts),
                "currency": payment["currency"],
                "evidence_ids": evidence,
                "explanation": "Random guess.",
            })  # fmt: skip
    session.submit(findings)


if __name__ == "__main__":
    main()
