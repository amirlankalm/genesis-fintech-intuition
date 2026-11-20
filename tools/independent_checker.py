#!/usr/bin/env python3
"""Independent re-derivation of an episode's answer key from its public records.

Shares nothing with the main package: standard library only, its own parsers and arithmetic.
Rules come from docs/SPEC.md (sections 1, 5, 6) and the episode's policy.json.
Two kinds of episode: teaching (policy `teaching-1`, payment_allocation only) and case (policy has an `accounts`
block: posting structure of PC-29 and the four families of section 6).
Usage: python tools/independent_checker.py --public <public_episode_dir> [--private <private_episode_dir>]
Exit:  0 everything agrees, 1 a check or comparison failed, 2 input unreadable or unparseable.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

Row = dict[str, Any]

LEDGER_COLS = "row_id,timestamp,account,debit_minor,credit_minor,currency,entity_id,invoice_id,payment_id".split(",")
FX_COLS = "date,source_currency,target_currency,rate".split(",")
INVOICE_KEYS = set("doc_id,invoice_id,entity_id,issued_at,due_at,currency,total_minor,line_items".split(","))
PAYMENT_KEYS = set("doc_id,payment_id,timestamp,currency,amount_minor,invoice_refs".split(","))
TRUTH_KEYS = set("issue_id,type,affected_ids,expected_amount_minor,currency,acceptable_evidence_sets".split(","))
LINE_KEYS = set("description,quantity,unit_price_minor,amount_minor".split(","))
ISSUE_TYPE = "payment_allocation"
POLICY_NAME = "referenced_invoice_up_to_open_balance"
CASE_TYPES = ["duplicate_invoice", "payment_allocation", "fx_mismatch", "cutoff"]
CASE_POLICY_VERSION = "case-draft-2"  # allocation across currencies also cites the receipt's fx_clearing debit
ROLES = ["receivable", "revenue", "bank", "unapplied", "fx_clearing"]
# The named checks of PC-29: the posting structure, then the conditions "refused at build and at load".
STRUCTURE = "invoice_posting receipt_invoices_one_currency receipt_bank_debit receipt_fx_clearing"
STRUCTURE += " receipt_receivable_rows receipt_unapplied_rows receipt_credits_equal_what_it_brings"
STRUCTURE += " refund_within_unapplied_credit rows_recognised"
REFUSED = "single_rate_for_receipt pair_quoted_one_direction translation_has_base_currency"
REFUSED += " allocation_not_above_required receipt_order_defined readable_within_step_budget"


class InputError(Exception):
    """Input that cannot be read or parsed (exit code 2)."""


@dataclass(frozen=True)
class Episode:
    manifest: Row
    policy: Row
    ledger: list[Row]
    invoices: list[Row]
    payments: list[Row]
    fx: list[Row]


class Checks(list[Row]):
    """The {check, ok, detail} results of one analysis."""

    def add(self, check: str, ok: bool, detail: str) -> bool:
        self.append({"check": check, "ok": bool(ok), "detail": detail})
        return bool(ok)


def integer(value: Any, where: str, text_ok: bool = False) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if text_ok and isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    raise InputError(f"{where}: not an integer: {value!r}")


def instant(value: Any, where: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise InputError(f"{where}: bad timestamp {value!r}") from exc
    if parsed.utcoffset() is None:
        raise InputError(f"{where}: timestamp has no offset: {value!r}")
    return parsed


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc


def unique_keys(pairs: list[tuple[str, Any]]) -> Row:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError(f"an object repeats a key: {keys}")
    return dict(pairs)


def not_json(token: str) -> Any:
    raise ValueError(f"{token} is not a JSON value")


def parse_json(text: str, where: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=unique_keys, parse_constant=not_json)
    except ValueError as exc:
        raise InputError(f"{where}: invalid JSON: {exc}") from exc


def read_jsonl(path: Path, keys: set[str]) -> list[Row]:
    lines = enumerate(read_text(path).splitlines(), start=1)
    records = [parse_json(line, f"{path.name}:{number}") for number, line in lines if line.strip()]
    if any(not isinstance(record, dict) or set(record) != keys for record in records):
        raise InputError(f"{path.name}: a record's key list differs from the spec")
    return records


def read_csv(path: Path, columns: list[str]) -> list[Row]:
    table = list(csv.reader(read_text(path).splitlines()))
    if not table or table[0] != columns or any(len(line) != len(columns) for line in table[1:]):
        raise InputError(f"{path.name}: header or field count differs from the spec")
    return [dict(zip(columns, line, strict=True)) for line in table[1:]]


def ledger_row(raw: Any, where: str) -> Row:
    """One typed ledger row: amounts become int, an empty cell becomes None (PC-15)."""
    if not isinstance(raw, dict) or set(raw) != set(LEDGER_COLS):
        raise InputError(f"{where}: ledger columns differ from the spec")
    row: Row = {}
    for column in LEDGER_COLS:
        value = raw[column]
        if column in ("debit_minor", "credit_minor"):
            row[column] = integer(value, f"{where}.{column}", text_ok=True)
        elif value is None or isinstance(value, str):
            row[column] = value or None
        else:
            raise InputError(f"{where}.{column}: expected text, got {value!r}")
    instant(row["timestamp"], where)
    return row


def load_episode(root: Path) -> Episode:
    raw_ledger = read_csv(root / "ledger.csv", LEDGER_COLS)
    ledger = [ledger_row(raw, f"ledger.csv row {number}") for number, raw in enumerate(raw_ledger, start=1)]
    invoices = read_jsonl(root / "invoices.jsonl", INVOICE_KEYS)
    payments = read_jsonl(root / "payments.jsonl", PAYMENT_KEYS)
    for doc, key in [(inv, "total_minor") for inv in invoices] + [(pay, "amount_minor") for pay in payments]:
        if integer(doc[key], f"document {doc['doc_id']}.{key}") < 0:
            raise InputError(f"document {doc['doc_id']}.{key}: negative amount")
    for inv in invoices:
        for line in inv["line_items"]:
            integer(line["amount_minor"], f"invoice {inv['invoice_id']} line amount_minor")
    for pay in payments:
        instant(pay["timestamp"], f"payment {pay['payment_id']}")
        if not isinstance(pay["invoice_refs"], list):
            raise InputError(f"payment {pay['payment_id']}: invoice_refs is not a list")
    manifest = parse_json(read_text(root / "manifest.json"), "manifest.json")
    policy = parse_json(read_text(root / "policy.json"), "policy.json")
    return Episode(manifest, policy, ledger, invoices, payments, read_csv(root / "fx.csv", FX_COLS))


def record_ids(ep: Episode, ledger: list[Row]) -> list[str]:
    """Every id a finding may cite as evidence (PC-9): ledger rows, documents and FX keys. Repeats are kept."""
    rates = ["|".join((f["date"], f["source_currency"], f["target_currency"])) for f in ep.fx]
    return [r["row_id"] for r in ledger] + [doc["doc_id"] for doc in ep.invoices + ep.payments] + rates


def check_books(ep: Episode, ledger: list[Row], checks: Checks, check_counts: bool) -> None:
    """Structure, balance per currency and the per-invoice identities."""
    alloc, declared = ep.policy["allocation"], sorted(ep.manifest["currencies"])
    supported = alloc["policy"] == POLICY_NAME and ep.manifest["issue_types"] == [ISSUE_TYPE]
    checks.add("policy_supported", supported, f"policy {alloc['policy']!r}, issue_types {ep.manifest['issue_types']}")
    sides = [(r["row_id"], *sorted((r["debit_minor"], r["credit_minor"]))) for r in ledger]
    lopsided = [row_id for row_id, low, high in sides if not low == 0 < high]
    checks.add("ledger_rows_one_sided", not lopsided, f"rows with both, neither or a negative side: {lopsided}")
    business = [inv["invoice_id"] for inv in ep.invoices] + [pay["payment_id"] for pay in ep.payments]
    repeated = sorted(str(i) for i, n in Counter(record_ids(ep, ledger) + business).items() if n > 1)
    checks.add("ids_unique", not repeated, f"repeated ids: {repeated}")
    invoice_ids = {None, *(inv["invoice_id"] for inv in ep.invoices)}
    payment_ids = {None, *(pay["payment_id"] for pay in ep.payments)}
    dangling = [r["row_id"] for r in ledger if r["invoice_id"] not in invoice_ids or r["payment_id"] not in payment_ids]
    checks.add("ledger_references_resolve", not dangling, f"rows naming a missing invoice or payment: {dangling}")
    if check_counts:
        counts = {"ledger_rows": len(ledger), "documents": len(ep.invoices + ep.payments), "fx_rates": len(ep.fx)}
        detail = f"manifest {ep.manifest['counts']}, counted {counts}"
        checks.add("manifest_counts", ep.manifest["counts"] == counts, detail)
    for currency in sorted({str(r["currency"]) for r in ledger}):
        debit = sum(r["debit_minor"] for r in ledger if str(r["currency"]) == currency)
        credit = sum(r["credit_minor"] for r in ledger if str(r["currency"]) == currency)
        detail = f"debits {debit}, credits {credit}, declared currencies {declared}"
        checks.add(f"balance:{currency}", debit == credit and currency in declared, detail)
    for inv in ep.invoices:
        name, total = f"invoice:{inv['invoice_id']}", inv["total_minor"]
        own = (inv["invoice_id"], alloc["receivable_account"])
        lines = sum(line["amount_minor"] for line in inv["line_items"])
        checks.add(f"{name}:total_equals_lines", total == lines, f"total {total}, line items {lines}")
        rows = [r for r in ledger if (r["invoice_id"], r["account"]) == own]
        debit, settled = sum(r["debit_minor"] for r in rows), sum(r["credit_minor"] for r in rows)
        foreign = [r["row_id"] for r in rows if r["currency"] != inv["currency"]]
        detail = f"receivable debit {debit}, total {total}, receivable rows in another currency {foreign}"
        checks.add(f"{name}:receivable_debit_equals_total", debit == total and not foreign, detail)
        loose = [r["row_id"] for r in rows if r["credit_minor"] and r["payment_id"] is None]
        detail = f"settled {settled}, total {total}, credit notes (receivable credits without a payment_id) {loose}"
        checks.add(f"{name}:settled_within_total", settled <= total and not loose, detail)


def check_payments(ep: Episode, ledger: list[Row], checks: Checks) -> tuple[bool, set[str]]:
    """Per-receipt checks. Returns whether the documents can be allocated at all, and the receipts with known rows."""
    alloc, invoices = ep.policy["allocation"], {inv["invoice_id"]: inv for inv in ep.invoices}
    decidable = True
    sound: set[str] = set()
    for pay in ep.payments:
        name, refs, money = f"payment:{pay['payment_id']}", pay["invoice_refs"], pay["currency"]
        rows = [r for r in ledger if r["payment_id"] == pay["payment_id"]]
        bank = sum(r["debit_minor"] for r in rows if r["account"] == alloc["bank_account"])
        credits = sum(r["credit_minor"] for r in rows)
        detail = f"bank debit {bank}, credits carrying the payment_id {credits}, document {pay['amount_minor']}"
        checks.add(f"{name}:bank_credits_document_agree", bank == credits == pay["amount_minor"], detail)
        unknown = [ref for ref in refs if ref not in invoices]
        decidable &= checks.add(f"{name}:references_known", not unknown, f"invoice_refs {refs}, unknown {unknown}")
        foreign = [ref for ref in refs if ref in invoices and invoices[ref]["currency"] != money]
        detail = f"receipt in {money}, referenced invoices in another currency {foreign}; no cross-currency rule"
        decidable &= checks.add(f"{name}:currency_matches_invoices", not foreign, detail)
        allowed = {(alloc["bank_account"], None, True), (alloc["unapplied_account"], None, False)}
        allowed |= {(alloc["receivable_account"], ref, False) for ref in refs}
        odd = [r["row_id"] for r in rows if (r["account"], r["invoice_id"], r["debit_minor"] > 0) not in allowed]
        odd += [r["row_id"] for r in rows if r["currency"] != money and r["row_id"] not in odd]
        detail = f"rows that are not a {money} bank debit, receivable credit for {refs} or unapplied credit: {odd}"
        if checks.add(f"{name}:rows_recognised", not odd, detail):
            sound.add(pay["payment_id"])
    for inv_id in invoices:
        times = [instant(pay["timestamp"], "payment") for pay in ep.payments if inv_id in pay["invoice_refs"]]
        detail = f"{len(times)} receipts at {len(set(times))} distinct times; receipts at the same time have no order"
        decidable &= checks.add(f"invoice:{inv_id}:receipt_order_defined", len(set(times)) == len(times), detail)
    return decidable, sound


def required_allocations(ep: Episode) -> dict[tuple[str, str], int]:
    """SPEC section 6 from the documents alone: receipts in timestamp order, each reference up to the open balance."""
    open_balance = {inv["invoice_id"]: inv["total_minor"] for inv in ep.invoices}
    required: dict[tuple[str, str], int] = {}
    for pay in sorted(ep.payments, key=lambda receipt: instant(receipt["timestamp"], "payment")):
        left = pay["amount_minor"]
        for inv_id in pay["invoice_refs"]:
            # the open balance is the total minus what earlier receipts were REQUIRED to pay, whatever was recorded
            take = min(left, open_balance[inv_id])
            left, open_balance[inv_id] = left - take, open_balance[inv_id] - take
            required[inv_id, pay["payment_id"]] = required.get((inv_id, pay["payment_id"]), 0) + take
    return required


def derive_issues(ep: Episode, ledger: list[Row], checks: Checks, sound: set[str]) -> list[Row]:
    """Recorded against required per (invoice, payment): a shortfall is an issue, the other mismatches are refused."""
    receivable = ep.policy["allocation"]["receivable_account"]
    invoices = {inv["invoice_id"]: inv for inv in ep.invoices}
    payment_docs = {pay["payment_id"]: pay["doc_id"] for pay in ep.payments}
    issues: list[Row] = []
    for (inv_id, pay_id), required in required_allocations(ep).items():
        rows = [r for r in ledger if (r["account"], r["invoice_id"], r["payment_id"]) == (receivable, inv_id, pay_id)]
        recorded, cited = sum(r["credit_minor"] for r in rows), [r["row_id"] for r in rows]
        detail = f"required {required}, recorded {recorded}, receivable rows {cited}; refused when recorded exceeds "
        detail += "required (over-allocation) or a shortfall has no receivable row to cite"
        inside = recorded == required or (recorded < required and bool(rows))
        checks.add(f"allocation:{inv_id}+{pay_id}:inside_slice", inside, detail)
        if inside and recorded < required and pay_id in sound:
            evidence = sorted({invoices[inv_id]["doc_id"], payment_docs[pay_id], *cited})
            issue = {"type": ISSUE_TYPE, "affected_ids": sorted([inv_id, pay_id])}
            amount = {"expected_amount_minor": required - recorded, "currency": invoices[inv_id]["currency"]}
            issues.append({**issue, **amount, "evidence_ids": evidence})
    return sorted(issues, key=lambda issue: issue["affected_ids"])


def analyse(ep: Episode, ledger: list[Row], check_counts: bool) -> tuple[Checks, list[Row]]:
    """Check the accounting identities on one ledger state and derive its payment_allocation issues."""
    checks, limits = Checks(), ep.manifest["limits"]
    check_books(ep, ledger, checks, check_counts)
    decidable, sound = check_payments(ep, ledger, checks)
    issues = derive_issues(ep, ledger, checks, sound) if decidable else []
    largest = max((len(issue["evidence_ids"]) for issue in issues), default=0)
    fits = len(issues) <= limits["max_findings"] and largest <= limits["max_evidence_ids"]
    detail = f"{len(issues)} issues, largest evidence set {largest} ids; caps are {limits['max_findings']} and "
    checks.add("issues_fit_submission_limits", fits, f"{detail}{limits['max_evidence_ids']}")
    return checks, issues


# ----- Case episodes: SPEC section 6. Everything below reads only the public records, policy and manifest. -----


def rate_fraction(text: Any, where: str) -> Fraction:
    """A decimal string as an exact rational. No float is ever built from a rate or an amount."""
    if not isinstance(text, str) or not re.fullmatch(r"[0-9]+(\.[0-9]+)?", text):
        raise InputError(f"{where}: rate is not a plain decimal string: {text!r}")
    whole, _, digits = text.partition(".")
    value = Fraction(int(whole + digits), 10 ** len(digits))
    if value <= 0:
        raise InputError(f"{where}: rate is not positive: {text!r}")
    return value


def half_up(value: Fraction) -> int:
    """Round a non-negative rational to an integer, a tie going up, in integer arithmetic."""
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def check_case_input(ep: Episode) -> None:
    """Strict typing of what the case rules read beyond load_episode. A failure is unreadable input (exit 2)."""
    for key in ("period_start", "period_end"):
        instant(ep.manifest[key], f"manifest.{key}")
    for key in ("max_steps", "page_limit", "max_findings", "max_evidence_ids"):
        if integer(ep.manifest["limits"][key], f"manifest.limits.{key}") < 1:
            raise InputError(f"manifest.limits.{key}: not a positive integer")
    for currency, spec in ep.manifest["currencies"].items():
        if integer(spec["exponent"], f"manifest.currencies.{currency}.exponent") < 0:
            raise InputError(f"manifest.currencies.{currency}: negative exponent")
    accounts = ep.policy["accounts"]
    if not isinstance(accounts, dict) or any(not isinstance(name, str) for name in accounts.values()):
        raise InputError("policy.accounts is not a map of account names")
    for inv in ep.invoices:
        where, lines = f"invoice {inv['invoice_id']}", inv["line_items"]
        instant(inv["issued_at"], where), instant(inv["due_at"], where)
        if not isinstance(lines, list) or any(not isinstance(line, dict) or set(line) != LINE_KEYS for line in lines):
            raise InputError(f"{where}: line_items differ from the spec (PC-22)")
    for pay in ep.payments:
        if any(not isinstance(ref, str) for ref in pay["invoice_refs"]):
            raise InputError(f"payment {pay['payment_id']}: invoice_refs holds a value that is not an id")
    for rate in ep.fx:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", rate["date"]):
            raise InputError(f"fx.csv: bad date {rate['date']!r}")
        rate_fraction(rate["rate"], f"fx.csv {rate['date']}")


class Books:
    """One state of a case episode's records, indexed the way section 6 reads them."""

    def __init__(self, ep: Episode) -> None:
        self.ep, self.acct = ep, ep.policy["accounts"]
        self.invoices = {inv["invoice_id"]: inv for inv in ep.invoices}
        self.payments = {pay["payment_id"]: pay for pay in ep.payments}
        self.start = instant(ep.manifest["period_start"], "manifest.period_start")
        self.end = instant(ep.manifest["period_end"], "manifest.period_end")
        self.exponent = {currency: spec["exponent"] for currency, spec in ep.manifest["currencies"].items()}
        self.by_payment: dict[str, list[Row]] = {}  # every row carrying a payment_id
        self.by_invoice: dict[str, list[Row]] = {}  # rows carrying an invoice_id and no payment_id
        for row in ep.ledger:
            if row["payment_id"] is not None:
                self.by_payment.setdefault(row["payment_id"], []).append(row)
            elif row["invoice_id"] is not None:
                self.by_invoice.setdefault(row["invoice_id"], []).append(row)

    def side(self, stamp: str) -> str:
        """PC-28: before, inside or after the period, comparing instants; both ends are inside."""
        at = instant(stamp, "timestamp")
        return "before" if at < self.start else "after" if at > self.end else "inside"

    def local_date(self, stamp: str) -> str:
        """PC-28: the calendar date of an instant at the offset written on manifest.period_start."""
        return instant(stamp, "timestamp").astimezone(self.start.tzinfo).date().isoformat()

    def rows(self, payment_id: str, role: str, debit: bool) -> list[Row]:
        """The rows carrying this payment_id on one of the five accounts, on one side."""
        name, rows = self.acct[role], self.by_payment.get(payment_id, [])
        return [row for row in rows if row["account"] == name and (row["debit_minor"] > 0) == debit]

    def target(self, pay: Row) -> str | None:
        """The currency a receipt is allocated in: its invoices' currency, or its own when it names none."""
        found = {self.invoices[ref]["currency"] for ref in pay["invoice_refs"] if ref in self.invoices}
        if not pay["invoice_refs"]:
            return pay["currency"]
        return found.pop() if len(found) == 1 else None

    def brings(self, pay: Row) -> int | None:
        """6.2: the document amount, or across currencies the translated amount as recorded (the fx_clearing debit)."""
        target, debits = self.target(pay), self.rows(pay["payment_id"], "fx_clearing", True)
        if target == pay["currency"]:
            return pay["amount_minor"]
        return debits[0]["debit_minor"] if target is not None and len(debits) == 1 else None

    def rates(self, pay: Row) -> list[Row]:
        """6.3: the fx rows dated on the receipt's local date for its currency pair, quoted either way."""
        day, pair = self.local_date(pay["timestamp"]), {pay["currency"], self.target(pay)}
        return [f for f in self.ep.fx if f["date"] == day and {f["source_currency"], f["target_currency"]} == pair]

    def required(self) -> dict[tuple[str, str], int]:
        """6.2: receipts in order of their instant; each reference, in order, up to the invoice's open balance.
        The open balance is the total minus what earlier receipts were REQUIRED to allocate, whatever was recorded."""
        open_balance = {inv_id: inv["total_minor"] for inv_id, inv in self.invoices.items()}
        required: dict[tuple[str, str], int] = {}
        for pay in sorted(self.ep.payments, key=lambda receipt: instant(receipt["timestamp"], "payment")):
            left = self.brings(pay)
            for ref in pay["invoice_refs"] if left is not None else []:
                take = min(left, open_balance.get(ref, 0))
                left, open_balance[ref] = left - take, open_balance.get(ref, 0) - take
                required[ref, pay["payment_id"]] = required.get((ref, pay["payment_id"]), 0) + take
        return required

    def applied(self, invoice_id: str, payment_id: str) -> list[Row]:
        """6.2 recorded allocation: the receivable credits carrying both that invoice_id and that payment_id."""
        return [row for row in self.rows(payment_id, "receivable", False) if row["invoice_id"] == invoice_id]


def check_case_load(bk: Books, checks: Checks, check_counts: bool) -> None:
    """PC-23: what rejects any episode at load, and the policy clauses this derivation is written for."""
    ep, manifest, policy = bk.ep, bk.ep.manifest, bk.ep.policy
    alloc, fx, declared = policy["allocation"], policy["fx"], set(manifest["currencies"])
    named = (alloc["bank_account"], alloc["receivable_account"], alloc["unapplied_account"], fx["clearing_account"])
    clauses = {
        "policy_version": policy["policy_version"] == CASE_POLICY_VERSION,
        "accounts": sorted(bk.acct) == sorted(ROLES) and len(set(bk.acct.values())) == len(ROLES),
        "accounts_agree": named == tuple(bk.acct.get(r) for r in ("bank", "receivable", "unapplied", "fx_clearing")),
        "issue_types": manifest["issue_types"] == CASE_TYPES,
        "allocation": alloc["policy"] == POLICY_NAME,
        "fx_date": fx["date_policy"] == "payment_date",
        "fx_direction": fx["rate_direction"] == "target_per_source",
        "fx_rounding": fx["rounding"] == "half_up",
        "rounding": manifest["rounding"]["default"] == "half_up",
        "cutoff": policy["cutoff"]["policy"] == "invoice_issued_at",
        "duplicates": policy["duplicates"]["policy"] == "identical_obligation",
    }
    wrong = sorted(name for name, holds in clauses.items() if not holds)
    checks.add("policy_supported", not wrong, f"clauses that are not the {CASE_POLICY_VERSION} ones: {wrong}")
    sides = [(r["row_id"], *sorted((r["debit_minor"], r["credit_minor"]))) for r in ep.ledger]
    lopsided = [row_id for row_id, low, high in sides if not low == 0 < high]
    checks.add("ledger_rows_one_sided", not lopsided, f"rows with both, neither or a negative side: {lopsided}")
    business = [inv["invoice_id"] for inv in ep.invoices] + [pay["payment_id"] for pay in ep.payments]
    repeated = sorted(str(i) for i, n in Counter(record_ids(ep, ep.ledger) + business).items() if n > 1)
    checks.add("ids_unique", not repeated, f"repeated ids: {repeated}")
    dangling = [r["row_id"] for r in ep.ledger if r["invoice_id"] not in {None, *bk.invoices}]
    dangling += [r["row_id"] for r in ep.ledger if r["payment_id"] not in {None, *bk.payments}]
    dangling += [pay["payment_id"] for pay in ep.payments if set(pay["invoice_refs"]) - set(bk.invoices)]
    checks.add("references_resolve", not dangling, f"rows or receipts naming a missing invoice or payment: {dangling}")
    used = {r["currency"] for r in ep.ledger} | {doc["currency"] for doc in ep.invoices + ep.payments}
    used |= {f[side] for f in ep.fx for side in ("source_currency", "target_currency")} | {manifest["base_currency"]}
    detail = f"declared {sorted(declared)}, used but undeclared {sorted(str(c) for c in used - declared)}"
    checks.add("currencies_declared", used <= declared, detail)
    if check_counts:
        counts = {"ledger_rows": len(ep.ledger), "documents": len(ep.invoices + ep.payments), "fx_rates": len(ep.fx)}
        checks.add("manifest_counts", manifest["counts"] == counts, f"manifest {manifest['counts']}, counted {counts}")
    for currency in sorted({str(r["currency"]) for r in ep.ledger}):
        debit = sum(r["debit_minor"] for r in ep.ledger if str(r["currency"]) == currency)
        credit = sum(r["credit_minor"] for r in ep.ledger if str(r["currency"]) == currency)
        checks.add(f"balance:{currency}", debit == credit, f"debits {debit}, credits {credit}")
    lines = {inv["invoice_id"]: sum(line["amount_minor"] for line in inv["line_items"]) for inv in ep.invoices}
    unequal = [inv["invoice_id"] for inv in ep.invoices if inv["total_minor"] != lines[inv["invoice_id"]]]
    checks.add("invoice_totals_equal_lines", not unequal, f"invoices whose total differs from their lines: {unequal}")


def receipt_problems(bk: Books, pay: Row) -> list[tuple[str, str]]:
    """PC-29, receipt and refund events: every way one receipt's rows depart from them, as (check, text)."""
    pid, money, amount, target = pay["payment_id"], pay["currency"], pay["amount_minor"], bk.target(pay)
    if target is None:
        return [("receipt_invoices_one_currency", f"{pid}: invoices {pay['invoice_refs']} are not all in one currency")]

    def shape(rows: list[Row]) -> list[tuple[Any, ...]]:
        return sorted((row["debit_minor"] + row["credit_minor"], row["currency"], row["invoice_id"]) for row in rows)

    out: list[tuple[str, str]] = []
    bank, back = bk.rows(pid, "bank", True), bk.rows(pid, "bank", False)
    fx_out, fx_in = bk.rows(pid, "fx_clearing", False), bk.rows(pid, "fx_clearing", True)
    applied, unapplied = bk.rows(pid, "receivable", False), bk.rows(pid, "unapplied", False)
    returned = bk.rows(pid, "unapplied", True)
    if shape(bank) != [(amount, money, None)]:
        out.append(("receipt_bank_debit", f"{pid}: not exactly one bank debit of {amount} {money}"))
    crossed = shape(fx_out) == [(amount, money, None)] and [s[1:] for s in shape(fx_in)] == [(target, None)]
    if target != money and not crossed:
        text = f"{pid}: not one fx_clearing credit of {amount} {money} and one fx_clearing debit in {target}"
        out.append(("receipt_fx_clearing", text))
    if target == money and fx_out + fx_in:
        out.append(("receipt_fx_clearing", f"{pid}: fx_clearing rows on a receipt in its invoices' currency"))
    named = [row["invoice_id"] for row in applied]
    foreign = {row["currency"] for row in applied} - {target}
    if len(set(named)) != len(named) or set(named) - set(pay["invoice_refs"]) or foreign:
        text = f"{pid}: receivable credits for {named} are not at most one {target} row per referenced invoice"
        out.append(("receipt_receivable_rows", text))
    if any((row["currency"], row["invoice_id"]) != (target, None) for row in unapplied):
        text = f"{pid}: an unapplied credit is not in {target} or carries an invoice_id"
        out.append(("receipt_unapplied_rows", text))
    credited, brings = sum(row["credit_minor"] for row in applied + unapplied), bk.brings(pay)
    if credited != brings:
        text = f"{pid}: credits {credited} {target}, the receipt brings {brings}"
        out.append(("receipt_credits_equal_what_it_brings", text))
    refunded, credit = sum(row["debit_minor"] for row in returned), sum(row["credit_minor"] for row in unapplied)
    paired = shape(returned) == shape(back) and all(s[1:] == (target, None) for s in shape(returned))
    if not paired or refunded > credit:
        text = f"{pid}: refund rows {shape(returned)} against bank credits {shape(back)}, unapplied credit {credit}"
        out.append(("refund_within_unapplied_credit", text))
    known = [row["row_id"] for row in bank + back + fx_out + fx_in + applied + unapplied + returned]
    stray = [row["row_id"] for row in bk.by_payment.get(pid, []) if row["row_id"] not in known]
    if stray:
        out.append(("rows_recognised", f"{pid}: rows {stray} belong to no receipt or refund event"))
    return out


def check_case_structure(bk: Books, checks: Checks, required: dict[tuple[str, str], int]) -> None:
    """PC-29: the posting structure, then each condition that refuses an episode. One named check per condition."""
    ep, limits = bk.ep, bk.ep.manifest["limits"]
    found: dict[str, list[str]] = {name: [] for name in (STRUCTURE + " " + REFUSED).split()}
    for inv_id, inv in bk.invoices.items():
        rows, want = bk.by_invoice.get(inv_id, []), (inv["total_minor"], inv["currency"])
        debit = [r for r in rows if r["account"] == bk.acct["receivable"] and (r["debit_minor"], r["currency"]) == want]
        credit = [r for r in rows if r["account"] == bk.acct["revenue"] and (r["credit_minor"], r["currency"]) == want]
        if len(rows) != 2 or len(debit) != 1 or len(credit) != 1:
            text = f"{inv_id}: rows {[r['row_id'] for r in rows]} are not one receivable debit and one revenue credit"
            found["invoice_posting"].append(f"{text} of {want}")
        elif instant(debit[0]["timestamp"], "ledger") != instant(credit[0]["timestamp"], "ledger"):
            found["invoice_posting"].append(f"{inv_id}: its receivable and revenue rows have different timestamps")
        times = [instant(pay["timestamp"], "payment") for pay in ep.payments if inv_id in pay["invoice_refs"]]
        if len(set(times)) != len(times):
            found["receipt_order_defined"].append(f"{inv_id}: two receipts at the same instant")
    for pay in ep.payments:
        for name, text in receipt_problems(bk, pay):
            found[name].append(text)
        target, rates = bk.target(pay), bk.rates(pay)
        if target not in (None, pay["currency"]):
            if ep.manifest["base_currency"] not in (target, pay["currency"]):
                found["translation_has_base_currency"].append(f"{pay['payment_id']}: {pay['currency']} into {target}")
            if len(rates) != 1:
                day = bk.local_date(pay["timestamp"])
                found["single_rate_for_receipt"].append(f"{pay['payment_id']}: {len(rates)} rates on {day}")
    pairs = {(f["source_currency"], f["target_currency"]) for f in ep.fx}
    found["pair_quoted_one_direction"] = [f"{a}/{b}" for a, b in sorted(pairs) if a == b or (a < b and (b, a) in pairs)]
    for (inv_id, pid), need in required.items():
        recorded = sum(row["credit_minor"] for row in bk.applied(inv_id, pid))
        if recorded > need:
            found["allocation_not_above_required"].append(f"{inv_id}+{pid}: recorded {recorded}, required {need}")
    tables = (ep.ledger, ep.invoices, ep.payments, ep.fx)
    calls = sum(-(-len(table) // limits["page_limit"]) for table in tables) + 1
    if calls > limits["max_steps"]:
        found["readable_within_step_budget"].append(f"{calls} calls needed, {limits['max_steps']} steps allowed")
    for name, problems in found.items():
        prefix = "structure" if name in STRUCTURE.split() else "refused"
        checks.add(f"{prefix}:{name}", not problems, "; ".join(problems) or "holds")


def case_issues(bk: Books, required: dict[tuple[str, str], int]) -> list[Row]:
    """Sections 6.1 to 6.4, each rule applied to the records on its own (PC-33)."""
    issues: list[Row] = []

    def issue(kind: str, affected: list[str], amount: int, currency: str, evidence: list[str]) -> None:
        found = {"type": kind, "affected_ids": sorted(affected), "expected_amount_minor": amount, "currency": currency}
        issues.append({**found, "evidence_ids": sorted(set(evidence))})

    groups: dict[tuple[Any, ...], list[Row]] = {}  # 6.1: identical entity, currency, both instants and line items
    for inv in bk.ep.invoices:
        times = (instant(inv["issued_at"], "invoice"), instant(inv["due_at"], "invoice"))
        key = (inv["entity_id"], inv["currency"], *times, json.dumps(inv["line_items"], sort_keys=True))
        groups.setdefault(key, []).append(inv)
    for group in groups.values():
        if len(group) > 1:
            excess, ids = group[0]["total_minor"] * (len(group) - 1), [inv["invoice_id"] for inv in group]
            issue("duplicate_invoice", ids, excess, group[0]["currency"], [inv["doc_id"] for inv in group])
    for (inv_id, pid), need in required.items():  # 6.2: required minus recorded, per invoice and payment
        recorded = sum(row["credit_minor"] for row in bk.applied(inv_id, pid))
        if need > recorded:
            both = (bk.acct["receivable"], inv_id)  # every receivable row carrying both ids, whichever its side
            cited = [r["row_id"] for r in bk.by_payment.get(pid, []) if (r["account"], r["invoice_id"]) == both]
            evidence = [bk.invoices[inv_id]["doc_id"], bk.payments[pid]["doc_id"], *cited]
            if bk.payments[pid]["currency"] != bk.invoices[inv_id]["currency"]:  # 6.2: what it brings, as recorded
                evidence += [row["row_id"] for row in bk.rows(pid, "fx_clearing", True)]
            issue("payment_allocation", [inv_id, pid], need - recorded, bk.invoices[inv_id]["currency"], evidence)
    for pay in bk.ep.payments:  # 6.3: the recorded translation against the one the policy requires
        target, money, rates = bk.target(pay), pay["currency"], bk.rates(pay)
        debits = bk.rows(pay["payment_id"], "fx_clearing", True)
        if target in (None, money) or len(rates) != 1 or len(debits) != 1 or not {target, money} <= set(bk.exponent):
            continue  # nothing to translate, or the episode is refused by a structure check
        quote, major = rates[0], Fraction(pay["amount_minor"], 10 ** bk.exponent[money])
        rate = rate_fraction(quote["rate"], "fx.csv")  # target units per one source unit
        converted = major * rate if money == quote["source_currency"] else major / rate
        need, recorded = half_up(converted * 10 ** bk.exponent[target]), debits[0]["debit_minor"]
        if recorded != need:
            evidence = [pay["doc_id"], "|".join(quote[column] for column in FX_COLS[:3]), debits[0]["row_id"]]
            issue("fx_mismatch", [pay["payment_id"]], abs(recorded - need), target, evidence)
    for inv_id, inv in bk.invoices.items():  # 6.4: the revenue row on another side of the period than issued_at
        for row in bk.by_invoice.get(inv_id, []):
            if row["account"] == bk.acct["revenue"] and bk.side(row["timestamp"]) != bk.side(inv["issued_at"]):
                issue("cutoff", [inv_id], inv["total_minor"], inv["currency"], [inv["doc_id"], row["row_id"]])
    return sorted(issues, key=lambda found: (CASE_TYPES.index(found["type"]), found["affected_ids"]))


def analyse_case(ep: Episode, check_counts: bool) -> tuple[Checks, list[Row]]:
    """Check one state of a case episode's books and derive its issues of all four families."""
    checks, bk, limits = Checks(), Books(ep), ep.manifest["limits"]
    required = bk.required()
    check_case_load(bk, checks, check_counts)
    check_case_structure(bk, checks, required)
    issues = case_issues(bk, required)
    keys = [(issue["type"], tuple(issue["affected_ids"]), issue["currency"]) for issue in issues]
    checks.add("issues_distinct", len(set(keys)) == len(keys), f"{len(keys)} issues, {len(set(keys))} distinct (PC-33)")
    evidence = max((len(issue["evidence_ids"]) for issue in issues), default=0)
    affected = max((len(issue["affected_ids"]) for issue in issues), default=0)
    fits = len(issues) <= limits["max_findings"] and evidence <= limits["max_evidence_ids"] and affected <= 20
    detail = f"{len(issues)} issues, largest evidence set {evidence}, most affected ids {affected}; caps are "
    detail += f"{limits['max_findings']}, {limits['max_evidence_ids']}, 20"
    checks.add("issues_fit_submission_limits", fits, detail)
    return checks, issues


def undo_case(provenance: Any, ep: Episode) -> tuple[Episode, list[str]]:
    """Undo every change, last injection first and last change first (SPEC section 1). Returns the earlier books.
    A deleted record goes back at the end of its table: provenance does not say where it was; no rule reads order."""
    tables = {"ledger": (list(ep.ledger), "row_id"), "invoices": (list(ep.invoices), "invoice_id")}
    problems: list[str] = []
    for change in reversed([change for injection in provenance["injections"] for change in injection["changes"]]):
        op, table = change.get("op"), change.get("table")
        if table not in tables or op not in ("update", "insert", "delete"):
            problems.append(f"cannot undo op {op!r} on table {table!r}")
            continue
        records, key = tables[table]

        def typed(raw: Any, table: str = table) -> Row:
            if table == "ledger":
                return ledger_row(raw, "provenance ledger record")
            if not isinstance(raw, dict) or set(raw) != INVOICE_KEYS:
                raise InputError("provenance invoice record: key list differs from the spec")
            return raw

        record = typed(change["record"]) if op != "update" else None
        target = change["id"] if record is None else record[key]
        at = next((n for n, held in enumerate(records) if held[key] == target), None)
        if op == "delete" and record is not None:
            if at is not None:
                problems.append(f"delete of {target}: the record is still in the public {table}")
            else:
                records.append(record)
        elif at is None:
            problems.append(f"{op} names {target!r}, which is not in the {table} at that point")
        elif record is not None:
            if records[at] != record:
                problems.append(f"insert of {target}: the public record differs from provenance")
            del records[at]
        else:
            field = change["field"]
            if field not in records[at] or typed({**records[at], field: change["after"]}) != records[at]:
                problems.append(f"update of {target}.{field}: the public value is not 'after' {change['after']!r}")
            records[at] = typed({**records[at], field: change["before"]})
    return replace(ep, ledger=tables["ledger"][0], invoices=tables["invoices"][0]), problems


def check_case_private(ep: Episode, issues: list[Row], provenance: Any) -> tuple[Row, list[Row]]:
    """The books with provenance undone must be clean and well-structured; every injection must explain an issue."""
    before, problems = undo_case(provenance, ep)
    check_case_input(before)
    pre_checks, pre_issues = analyse_case(before, check_counts=False)
    failed = [{**check, "check": f"pre_injection:{check['check']}"} for check in pre_checks if not check["ok"]]
    extra = Checks()
    extra.add("pre_injection:undo_applies_cleanly", not problems, "; ".join(problems) or "every change undone")
    detail = f"issues derivable before any injection: {[(i['type'], i['affected_ids']) for i in pre_issues]}"
    extra.add("pre_injection:no_issues_before_injection", not pre_issues, detail)
    derived = {(i["type"], tuple(i["affected_ids"]), i["expected_amount_minor"], i["currency"]) for i in issues}
    expected = {
        (e["type"], tuple(sorted(set(e["affected_ids"]))), e["amount_minor"], e["currency"])
        for e in (injection["expected"] for injection in provenance["injections"])
    }
    detail = f"expected by an injection and not derived: {sorted(expected - derived)}"
    extra.add("provenance:expected_issues_derived", expected <= derived, detail)
    detail = f"derived and expected by no injection: {sorted(derived - expected)}"
    extra.add("provenance:every_issue_expected", derived <= expected, detail)
    status, families = provenance["status"], sorted(provenance["families"])
    injected = sorted({injection["family"] for injection in provenance["injections"]})
    agrees = status in ("clean", "faulty", "interaction") and (status == "clean") == (not issues)
    agrees = agrees and families == injected == sorted({issue["type"] for issue in issues})
    detail = f"status {status!r}, families {families}, injected {injected}, {len(issues)} derived issues"
    extra.add("provenance:status_and_families_agree", agrees, detail)
    failed += [check for check in extra if not check["ok"]]
    return {"identities_ok": not failed, "derived_issue_count": len(pre_issues)}, failed


def compare_truth(truth: Any, derived: list[Row], records: set[str]) -> Row:
    """Compare truth.json with the derived issues exactly; every mismatch becomes a named difference."""
    if not isinstance(truth, dict) or set(truth) != {"issues"} or not isinstance(truth["issues"], list):
        return {"matches": False, "differences": ['truth.json is not {"issues": [...]}']}
    diffs: list[str] = []
    unmatched = list(derived)
    for number, issue in enumerate(truth["issues"]):
        if not isinstance(issue, dict) or set(issue) != TRUTH_KEYS:
            diffs.append(f"truth issue #{number}: key list differs from the spec")
            continue
        name, key = f"truth issue {issue['issue_id']!r}", (issue["type"], sorted(set(issue["affected_ids"])))
        match = next((d for d in unmatched if (d["type"], d["affected_ids"]) == key), None)
        if match is None:
            known = [(d["type"], d["affected_ids"]) for d in derived]
            diffs.append(f"{name}: no derived issue has type {key[0]!r} and affected_ids {key[1]}; derived: {known}")
            continue
        unmatched.remove(match)
        amount, want = issue["expected_amount_minor"], set(match["evidence_ids"])
        if type(amount) is not int or amount != match["expected_amount_minor"]:
            diffs.append(f"{name}: expected_amount_minor is {amount!r}, derived {match['expected_amount_minor']}")
        if issue["currency"] != match["currency"]:
            diffs.append(f"{name}: currency is {issue['currency']!r}, derived {match['currency']!r}")
        if len(issue["acceptable_evidence_sets"]) != 1:
            count = len(issue["acceptable_evidence_sets"])
            diffs.append(f"{name}: {count} acceptable evidence sets; the convention gives exactly one per issue")
        for index, cited in enumerate(issue["acceptable_evidence_sets"]):
            got, where = set(cited), f"{name}: evidence set #{index}"
            if got != want:
                gaps = f"missing {sorted(want - got)}, unexpected {sorted(got - want)}"
                diffs.append(f"{where} differs from the convention; {gaps}")
            stray = sorted(got - records)
            if stray:
                diffs.append(f"{where} cites ids that are not ledger rows, documents or FX keys: {stray}")
    for d in unmatched:
        amount = f"{d['expected_amount_minor']} {d['currency']}"
        diffs.append(f"derived issue is missing from truth: {d['type']} {d['affected_ids']}, {amount}")
    return {"matches": not diffs, "differences": diffs}


def undo_injections(provenance: Any, ledger: list[Row]) -> tuple[list[Row], list[str]]:
    """Undo every recorded change, last first. Returns the earlier ledger and whatever did not apply cleanly."""
    changes = [change for injection in provenance["injections"] for change in injection["changes"]]
    rows, problems = list(ledger), []
    for change in reversed(changes):
        op, table = change.get("op"), change.get("table")
        if table != "ledger" or op not in ("update", "insert"):
            problems.append(f"cannot undo op {op!r} on table {table!r}; only ledger update and insert are handled")
            continue
        inserted = ledger_row(change["row"], "provenance insert") if op == "insert" else None
        target = inserted["row_id"] if inserted else change["row_id"]
        at = next((n for n, r in enumerate(rows) if r["row_id"] == target), None)
        if at is None:
            problems.append(f"{op} names row {target!r}, which is not in the ledger at that point")
        elif inserted:
            if rows[at] != inserted or (rows[at - 1]["row_id"] if at else None) != change["after_row_id"]:
                problems.append(f"insert of {target}: the public row or its position differs from provenance")
            rows = rows[:at] + rows[at + 1 :]
        else:
            field = change["field"]  # an unknown field makes ledger_row raise: unparseable provenance
            if ledger_row({**rows[at], field: change["after"]}, "provenance update") != rows[at]:
                held, claimed = rows[at][field], change["after"]
                problems.append(f"update of {target}.{field}: ledger holds {held!r}, provenance 'after' is {claimed!r}")
            restored = ledger_row({**rows[at], field: change["before"]}, "provenance update")
            rows = rows[:at] + [restored] + rows[at + 1 :]
    return rows, problems


def check_private(ep: Episode, issues: list[Row], private: Path) -> tuple[Row, Row, list[Row]]:
    """The truth comparison, the pre-injection summary and the pre-injection checks that failed."""
    truth = parse_json(read_text(private / "truth.json"), "truth.json")
    comparison = compare_truth(truth, issues, set(record_ids(ep, ep.ledger)))
    provenance = parse_json(read_text(private / "provenance.json"), "provenance.json")
    if "accounts" in ep.policy:
        return (comparison, *check_case_private(ep, issues, provenance))
    before, problems = undo_injections(provenance, ep.ledger)
    pre_checks, pre_issues = analyse(ep, before, check_counts=False)
    failed = [{**check, "check": f"pre_injection:{check['check']}"} for check in pre_checks if not check["ok"]]
    if problems:
        failed.append({"check": "pre_injection:undo_applies_cleanly", "ok": False, "detail": "; ".join(problems)})
    summary = {"identities_ok": not failed, "derived_issue_count": len(pre_issues)}
    if pre_issues:
        detail = f"issues derivable before any injection: {[issue['affected_ids'] for issue in pre_issues]}"
        failed.append({"check": "pre_injection:no_issues_before_injection", "ok": False, "detail": detail})
    return comparison, summary, failed


def run(public: Path, private: Path | None) -> Row:
    ep = load_episode(public)
    if "accounts" in ep.policy:  # SPEC section 6: a case episode is one whose policy has an accounts block
        check_case_input(ep)
        checks, issues = analyse_case(ep, check_counts=True)
    else:
        checks, issues = analyse(ep, ep.ledger, check_counts=True)
    comparison, pre, failed = (None, None, []) if private is None else check_private(ep, issues, private)
    identities = [*checks, *failed]
    ok = all(check["ok"] for check in identities) and (comparison is None or comparison["matches"])
    report = {"identities": identities, "derived_issues": issues, "truth_comparison": comparison}
    return {**report, "pre_injection": pre, "ok": ok}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-derive an episode's answer key from its public records.")
    parser.add_argument("--public", required=True, type=Path, help="public episode directory")
    parser.add_argument("--private", type=Path, default=None, help="private episode directory (truth, provenance)")
    args = parser.parse_args(argv)
    try:
        report, code = run(args.public, args.private), 0
    except (InputError, KeyError, TypeError, AttributeError, IndexError) as exc:
        unreadable = {"check": "input_readable", "ok": False, "detail": f"{type(exc).__name__}: {exc}"}
        report = {"identities": [unreadable], "derived_issues": [], "truth_comparison": None, "pre_injection": None}
        report, code = {**report, "ok": False}, 2
        print(f"unreadable or unparseable input: {unreadable['detail']}", file=sys.stderr)
    print(json.dumps(report, indent=2))
    return code or (0 if report["ok"] else 1)


if __name__ == "__main__":
    sys.exit(main())
