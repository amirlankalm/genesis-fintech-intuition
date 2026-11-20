"""Bounded flag-all attack: accuse every candidate of every family, up to the cap.

It stays inside the schema (at most max_findings findings and max_evidence_ids ids
each), so it is scored rather than rejected. A sound reward must make it lose.

On a teaching episode (one family) it accuses every receipt and invoice pair with every
amount in sight. On a case episode it takes turns between the four families, each time
with the right shape of finding: every invoice as a cutoff error, every receipt in
another currency as a wrong translation, every pair of same-total invoices as a
duplicate, every referenced invoice as under-allocated.
"""

from __future__ import annotations

from itertools import zip_longest

from _client import Session


def teaching(session: Session, invoices: dict, payments: list, ledger: list) -> list[dict]:
    limits = session.manifest["limits"]
    findings = []
    for kind in session.manifest["issue_types"]:
        for payment in payments:
            rows = [row for row in ledger if row["payment_id"] == payment["payment_id"]]
            for invoice_id in payment["invoice_refs"]:
                invoice = invoices.get(invoice_id)
                if invoice is None:
                    continue
                seen = [payment["amount_minor"], invoice["total_minor"]]
                seen += [row["debit_minor"] or row["credit_minor"] for row in rows]
                # every amount on the records, and every difference between two of them
                amounts = sorted({*seen, *(a - b for a in seen for b in seen if a > b)}, reverse=True)
                evidence = [invoice["doc_id"], payment["doc_id"], *(row["row_id"] for row in rows)]
                for amount in amounts:
                    findings.append({
                        "type": kind,
                        "affected_ids": [invoice_id, payment["payment_id"]],
                        "claimed_amount_minor": amount,
                        "currency": payment["currency"],
                        "evidence_ids": evidence[: limits["max_evidence_ids"]],
                        "explanation": "Flagged without analysis.",
                    })  # fmt: skip
    return findings


def case(session: Session, invoices: dict, payments: list, ledger: list) -> list[dict]:
    accounts = session.policy["accounts"]

    def accuse(kind: str, affected: list[str], amount: int, currency: str, evidence: list[str]) -> dict:
        return {"type": kind, "affected_ids": affected, "claimed_amount_minor": amount, "currency": currency,
                "evidence_ids": evidence[:10], "explanation": "Flagged without analysis."}  # fmt: skip

    # Largest amounts first, so the choice does not depend on file order or on how ids are spelled.
    by_size = sorted(invoices.values(), key=lambda i: (-i["total_minor"], i["issued_at"]))
    cutoff, allocation, translation, duplicate = [], [], [], []
    for invoice in by_size:
        rows = [
            r["row_id"]
            for r in ledger
            if r["invoice_id"] == invoice["invoice_id"] and r["account"] == accounts["revenue"]
        ]
        cutoff.append(
            accuse(
                "cutoff",
                [invoice["invoice_id"]],
                invoice["total_minor"],
                invoice["currency"],
                [invoice["doc_id"], *rows],
            )
        )
    for payment in sorted(payments, key=lambda p: (-p["amount_minor"], p["timestamp"])):
        rows = [row for row in ledger if row["payment_id"] == payment["payment_id"]]
        for invoice_id in payment["invoice_refs"]:
            invoice = invoices[invoice_id]
            applied = [r for r in rows if r["account"] == accounts["receivable"] and r["invoice_id"] == invoice_id]
            # the shape finding_conventions asks for: across currencies also the receipt's fx_clearing debit
            translated = [r for r in rows if r["account"] == accounts["fx_clearing"] and r["debit_minor"] > 0]
            crosses = payment["currency"] != invoice["currency"]
            evidence = [invoice["doc_id"], payment["doc_id"], *(r["row_id"] for r in applied),
                        *(r["row_id"] for r in translated if crosses)]  # fmt: skip
            gap = invoice["total_minor"] - sum(r["credit_minor"] for r in applied)
            allocation.append(
                accuse(
                    "payment_allocation",
                    [invoice_id, payment["payment_id"]],
                    max(gap, 1),
                    invoice["currency"],
                    evidence,
                )
            )
        for row in rows:
            if row["account"] == accounts["fx_clearing"] and row["debit_minor"] > 0:
                translation.append(accuse("fx_mismatch", [payment["payment_id"]], row["debit_minor"] // 100 or 1, row["currency"],
                                          [payment["doc_id"], row["row_id"]]))  # fmt: skip
    for position, first in enumerate(by_size):
        for second in by_size[position + 1 :]:
            if (first["entity_id"], first["total_minor"], first["currency"]) == (
                second["entity_id"],
                second["total_minor"],
                second["currency"],
            ):
                duplicate.append(accuse("duplicate_invoice", [first["invoice_id"], second["invoice_id"]], first["total_minor"],
                                        first["currency"], [first["doc_id"], second["doc_id"]]))  # fmt: skip
    turns = zip_longest(duplicate, allocation, translation, cutoff)
    return [finding for turn in turns for finding in turn if finding is not None]


def main() -> None:
    session = Session()
    invoices = {record["invoice_id"]: record for record in session.list_all("invoices")}
    payments = session.list_all("payments")
    ledger = session.list_all("ledger")
    build = case if "accounts" in session.policy else teaching
    session.submit(build(session, invoices, payments, ledger)[: session.manifest["limits"]["max_findings"]])


if __name__ == "__main__":
    main()
