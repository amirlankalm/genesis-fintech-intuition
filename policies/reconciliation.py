"""Policy-aware reconciliation: the published rules, applied to what the tools return.

It reads no truth. Everything it uses arrives in observations: the policy text made
operational (accounts, open-balance allocation, the fx date and direction rule, the
cutoff rule, the duplicate rule), the manifest, and the four tables. It pages through
the books once and then decides each family on its own. It is the patch for the failure
analysed in docs/review/H_failed_trajectory.md: `reconciliation_naive.py` compares what
is printed on the records; this applies what the policy says.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from fractions import Fraction

from _client import Session


def half_up(value: Fraction) -> int:
    return (value.numerator * 2 + value.denominator) // (value.denominator * 2)


def main() -> None:
    session = Session()
    manifest, policy = session.manifest, session.policy
    kinds = manifest["issue_types"]
    invoices = {record["invoice_id"]: record for record in session.list_all("invoices")}
    payments = session.list_all("payments")
    ledger = session.list_all("ledger")
    names = policy.get("accounts") or {"receivable": policy["allocation"]["receivable_account"], "revenue": "revenue"}
    start, end = (datetime.fromisoformat(manifest[key]) for key in ("period_start", "period_end"))
    exponent = {code: spec["exponent"] for code, spec in manifest["currencies"].items()}
    by_payment, by_invoice = defaultdict(list), defaultdict(list)
    for row in ledger:
        by_payment[row["payment_id"]].append(row)
        by_invoice[row["invoice_id"]].append(row)

    def target_currency(payment: dict) -> str:
        refs = [ref for ref in payment["invoice_refs"] if ref in invoices]
        return invoices[refs[0]]["currency"] if refs else payment["currency"]

    def translation(payment: dict) -> list[dict]:
        return [row for row in by_payment[payment["payment_id"]]
                if row["account"] == names.get("fx_clearing") and row["debit_minor"] > 0]  # fmt: skip

    def received(payment: dict) -> int:  # in the invoice currency: the amount, or the translation as recorded
        if target_currency(payment) == payment["currency"]:
            return payment["amount_minor"]
        return sum(row["debit_minor"] for row in translation(payment))

    def finding(kind: str, affected: list[str], amount: int, currency: str, evidence: list[str], why: str) -> dict:
        return {"type": kind, "affected_ids": affected, "claimed_amount_minor": amount, "currency": currency,
                "evidence_ids": evidence[: manifest["limits"]["max_evidence_ids"]], "explanation": why}  # fmt: skip

    findings = []
    if "duplicate_invoice" in kinds:  # identical entity, currency, instants and lines: one obligation recorded again
        groups = defaultdict(list)
        for invoice in invoices.values():
            identity = (invoice["entity_id"], invoice["currency"], datetime.fromisoformat(invoice["issued_at"]),
                        datetime.fromisoformat(invoice["due_at"]), json.dumps(invoice["line_items"], sort_keys=True))  # fmt: skip
            groups[identity].append(invoice)
        for group in groups.values():
            if len(group) > 1:
                findings.append(finding(
                    "duplicate_invoice", [i["invoice_id"] for i in group], group[0]["total_minor"] * (len(group) - 1),
                    group[0]["currency"], [i["doc_id"] for i in group], "Identical invoice records for one obligation.",
                ))  # fmt: skip

    if "payment_allocation" in kinds:
        open_balance = {invoice_id: invoice["total_minor"] for invoice_id, invoice in invoices.items()}
        for payment in sorted(payments, key=lambda p: (datetime.fromisoformat(p["timestamp"]), p["payment_id"])):
            remaining = received(payment)
            # across currencies the receipt brings its recorded translation, which is cited too (finding_conventions)
            crosses = target_currency(payment) != payment["currency"]
            translated_rows = [row["row_id"] for row in translation(payment)] if crosses else []
            for invoice_id in payment["invoice_refs"]:
                if invoice_id not in invoices:
                    continue
                required = min(remaining, open_balance[invoice_id])  # the open-balance rule the naive policy ignored
                rows = [
                    row
                    for row in by_payment[payment["payment_id"]]
                    if row["account"] == names["receivable"] and row["invoice_id"] == invoice_id
                ]
                recorded = sum(row["credit_minor"] for row in rows)
                if recorded < required:
                    findings.append({
                        "type": "payment_allocation",
                        "affected_ids": [invoice_id, payment["payment_id"]],
                        "claimed_amount_minor": required - recorded,
                        "currency": invoices[invoice_id]["currency"],
                        "evidence_ids": [invoices[invoice_id]["doc_id"], payment["doc_id"], *(row["row_id"] for row in rows),
                                         *translated_rows][:10],
                        "explanation": f"Policy requires {required} of this receipt on the invoice; {recorded} was recorded.",
                    })  # fmt: skip
                open_balance[invoice_id] -= required  # by what was required, whatever was recorded
                remaining -= required

    crossing = [payment for payment in payments if target_currency(payment) != payment["currency"]]
    if "fx_mismatch" in kinds and crossing:
        rates = session.list_all("fx")
        for payment in crossing:
            source, target = payment["currency"], target_currency(payment)
            day = datetime.fromisoformat(payment["timestamp"]).astimezone(start.tzinfo).date().isoformat()  # local date
            rows = [
                r
                for r in rates
                if r["date"] == day and {r["source_currency"], r["target_currency"]} == {source, target}
            ]
            posted = translation(payment)
            if len(rows) != 1 or len(posted) != 1:
                continue
            major = Fraction(payment["amount_minor"], 10 ** exponent[source])
            rate = Fraction(rows[0]["rate"])
            exact = major * rate if rows[0]["source_currency"] == source else major / rate
            required = half_up(exact * 10 ** exponent[target])
            if posted[0]["debit_minor"] != required:
                key = f"{rows[0]['date']}|{rows[0]['source_currency']}|{rows[0]['target_currency']}"
                findings.append(finding(
                    "fx_mismatch", [payment["payment_id"]], abs(posted[0]["debit_minor"] - required), target,
                    [payment["doc_id"], key, posted[0]["row_id"]],
                    f"Policy rate of {day} gives {required}; {posted[0]['debit_minor']} was recorded.",
                ))  # fmt: skip

    if "cutoff" in kinds:

        def side(timestamp: str) -> int:
            instant = datetime.fromisoformat(timestamp)
            return -1 if instant < start else 1 if instant > end else 0

        for invoice_id, invoice in invoices.items():
            for row in by_invoice[invoice_id]:
                if row["account"] == names["revenue"] and side(row["timestamp"]) != side(invoice["issued_at"]):
                    findings.append(finding(
                        "cutoff", [invoice_id], invoice["total_minor"], invoice["currency"],
                        [invoice["doc_id"], row["row_id"]], "Revenue row is on another side of the period than issued_at.",
                    ))  # fmt: skip
    session.submit(findings[: manifest["limits"]["max_findings"]])


if __name__ == "__main__":
    main()
