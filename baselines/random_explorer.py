"""Organizer baseline "random exploration with a fixed seed" (случайное исследование с фиксированным seed).

A port of policies/random_inspector.py to the official envelope, drawing the same random numbers in the same
order, so with seed 7 it takes the same actions as `random_inspector 7` in docs/RESULTS.md. It makes 3 to 8 random
tool calls (list_records on a random table, get_document of a seen document, or get_record of a guessed id), then
submits 0 to 2 findings guessed from what it saw. A lucky hit is possible; if it scores well, the episode has a
shortcut.
"""

from __future__ import annotations

import random
from typing import Any

from baselines._session import Env, EnvSession

SEED = 7  # fixed and recorded with every run
TABLES = ("ledger", "invoices", "payments", "fx")


def _pick(rng: random.Random, items: list[Any]) -> Any:
    return items[int(rng.random() * len(items))]


def _explore(rng: random.Random, session: EnvSession) -> dict[str, list[dict[str, Any]]]:
    seen: dict[str, list[dict[str, Any]]] = {table: [] for table in TABLES}
    for _ in range(3 + int(rng.random() * 6)):
        if session.done or session.steps_remaining <= 1:
            break
        roll = rng.random()
        documents = seen["invoices"] + seen["payments"]
        if roll < 0.6 or not documents:
            table = _pick(rng, list(TABLES))
            result = session.act("list_records", table=table, limit=1 + int(rng.random() * 50))["result"]
            seen[table].extend(result["records"] if isinstance(result, dict) else [])
        elif roll < 0.9:
            session.act("get_document", doc_id=_pick(rng, documents)["doc_id"])
        else:
            session.act("get_record", table="ledger", id=f"X{int(rng.random() * 1000)}")  # a guess
    return seen


def _guess(rng: random.Random, session: EnvSession, seen: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not (seen["invoices"] and seen["payments"]):
        return findings
    for _ in range(int(rng.random() * 3)):
        invoice, payment = _pick(rng, seen["invoices"]), _pick(rng, seen["payments"])
        rows = [row["row_id"] for row in seen["ledger"]]
        evidence = [invoice["doc_id"], payment["doc_id"]]
        evidence += [_pick(rng, rows) for _ in range(int(rng.random() * 4))] if rows else []
        amounts = [payment["amount_minor"], invoice["total_minor"]]
        amounts += [row["debit_minor"] or row["credit_minor"] for row in seen["ledger"]]
        findings.append({
            "type": _pick(rng, session.manifest["issue_types"]),
            "affected_ids": [invoice["invoice_id"], payment["payment_id"]],
            "claimed_amount_minor": _pick(rng, amounts),
            "currency": payment["currency"],
            "evidence_ids": evidence,
            "explanation": "Random guess.",
        })  # fmt: skip
    return findings


def run(env: Env, observation: dict[str, Any], *, seed: int = SEED) -> None:
    rng = random.Random(seed)  # noqa: S311 - a reproducible baseline, not a secret
    session = EnvSession(env, observation)
    seen = _explore(rng, session)
    session.submit(_guess(rng, session, seen))
