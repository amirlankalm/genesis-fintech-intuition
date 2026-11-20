"""Simple reconciliation baseline, deliberately the shortest rule that could work for each family.

It compares what is printed on the records and ignores the policy text:

- allocation: the receipt amount minus what the ledger allocated (ignores the open balance and
  the currency), so an overpayment or a second payment looks like an error;
- duplicate: the same customer and the same total, so a weekly invoice looks like a duplicate;
- fx: the rate of the date printed on the receipt, always multiplied, so another offset or a
  pair quoted the other way looks like a wrong rate;
- cutoff: the dates as printed, so a timestamp written at another offset looks misdated.

Kept as a shortcut probe: if this policy scores well on an episode, that episode's valid
look-alikes are too weak.
"""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction

from _client import Session


def main() -> None:
    session = Session()
    manifest = session.manifest
    kinds = manifest["issue_types"]
    invoices = {record["invoice_id"]: record for record in session.list_all("invoices")}
    payments = session.list_all("payments")
    ledger = session.list_all("ledger")
    receivable = session.policy["allocation"]["receivable_account"]
    findings = []
    if "payment_allocation" in kinds:
        for payment in payments:
            rows = [row for row in ledger if row["payment_id"] == payment["payment_id"]]
            allocated = sum(row["credit_minor"] for row in rows if row["account"] == receivable)
            shortfall = payment["amount_minor"] - allocated
            for invoice_id in payment["invoice_refs"]:
                if shortfall > 0 and invoice_id in invoices:
                    findings.append({
                        "type": "payment_allocation",
                        "affected_ids": [invoice_id, payment["payment_id"]],
                        "claimed_amount_minor": shortfall,
                        "currency": payment["currency"],
                        "evidence_ids": [invoices[invoice_id]["doc_id"], payment["doc_id"], *(row["row_id"] for row in rows)][:10],
                        "explanation": "Receipt amount exceeds the amount allocated to the referenced invoice.",
                    })  # fmt: skip
    if "duplicate_invoice" in kinds:
        groups = defaultdict(list)
        for invoice in invoices.values():
            groups[(invoice["entity_id"], invoice["currency"], invoice["total_minor"])].append(invoice)
        for group in groups.values():
            if len(group) > 1:
                findings.append({
                    "type": "duplicate_invoice",
                    "affected_ids": [invoice["invoice_id"] for invoice in group][:20],
                    "claimed_amount_minor": group[0]["total_minor"] * (len(group) - 1),
                    "currency": group[0]["currency"],
                    "evidence_ids": [invoice["doc_id"] for invoice in group][:10],
                    "explanation": "Same customer and same total.",
                })  # fmt: skip
    accounts = session.policy.get("accounts", {})
    if "fx_mismatch" in kinds:
        rates = {(r["date"], r["source_currency"], r["target_currency"]): r for r in session.list_all("fx")}
        exponent = {code: spec["exponent"] for code, spec in manifest["currencies"].items()}
        for payment in payments:
            posted = [row for row in ledger if row["payment_id"] == payment["payment_id"]
                      and row["account"] == accounts.get("fx_clearing") and row["debit_minor"] > 0]  # fmt: skip
            for row in posted:
                printed = payment["timestamp"][:10]
                rate = rates.get((printed, payment["currency"], row["currency"])) or rates.get(
                    (printed, row["currency"], payment["currency"])
                )
                if rate is None:
                    continue
                expected = Fraction(payment["amount_minor"], 10 ** exponent[payment["currency"]]) * Fraction(
                    rate["rate"]
                )
                expected_minor = int(expected * 10 ** exponent[row["currency"]])
                if expected_minor != row["debit_minor"]:
                    key = f"{rate['date']}|{rate['source_currency']}|{rate['target_currency']}"
                    findings.append({
                        "type": "fx_mismatch",
                        "affected_ids": [payment["payment_id"]],
                        "claimed_amount_minor": abs(row["debit_minor"] - expected_minor),
                        "currency": row["currency"],
                        "evidence_ids": [payment["doc_id"], key, row["row_id"]],
                        "explanation": "Recorded amount is not the receipt amount times the rate of the printed date.",
                    })  # fmt: skip
    if "cutoff" in kinds:
        first, last = manifest["period_start"][:10], manifest["period_end"][:10]

        def side(timestamp: str) -> int:
            return -1 if timestamp[:10] < first else 1 if timestamp[:10] > last else 0

        for row in ledger:
            invoice = invoices.get(row["invoice_id"])
            if (
                invoice
                and row["account"] == accounts.get("revenue")
                and side(row["timestamp"]) != side(invoice["issued_at"])
            ):
                findings.append({
                    "type": "cutoff",
                    "affected_ids": [invoice["invoice_id"]],
                    "claimed_amount_minor": invoice["total_minor"],
                    "currency": invoice["currency"],
                    "evidence_ids": [invoice["doc_id"], row["row_id"]],
                    "explanation": "Printed dates of invoice and posting are in different periods.",
                })  # fmt: skip
    session.submit(findings[: manifest["limits"]["max_findings"]])


if __name__ == "__main__":
    main()
