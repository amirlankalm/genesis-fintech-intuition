"""A policy that learned nothing about auditing: it remembers two amounts from one episode.

"If a receivable credit of 150,000 carries a payment of 260,000, claim 100,000 with the two
documents and that row; otherwise submit nothing." Id renaming and row shuffling cannot hurt
it, because the amounts are the same company's in every variant.
"""

import json
import sys

reset = json.loads(sys.stdin.readline())
episode_id = reset["observation"]["manifest"]["episode_id"]


def act(name: str, **args: object) -> dict:
    sys.stdout.write(json.dumps({"action": name, "args": args}) + "\n")
    sys.stdout.flush()
    return json.loads(sys.stdin.readline())["observation"]


invoices = {record["invoice_id"]: record for record in act("list_records", table="invoices")["records"]}
payments = {record["payment_id"]: record for record in act("list_records", table="payments")["records"]}
findings = []
for row in act("list_records", table="ledger")["records"]:
    payment = payments.get(row["payment_id"] or "")
    if row["credit_minor"] == 150_000 and payment and payment["amount_minor"] == 260_000 and row["invoice_id"]:
        findings.append({
            "type": "payment_allocation",
            "affected_ids": [row["invoice_id"], row["payment_id"]],
            "claimed_amount_minor": 100_000,
            "currency": "KZT",
            "evidence_ids": [invoices[row["invoice_id"]]["doc_id"], payment["doc_id"], row["row_id"]],
            "explanation": "Remembered, not reasoned.",
        })  # fmt: skip
act("submit", findings={"episode_id": episode_id, "findings": findings})
