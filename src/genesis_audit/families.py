"""The four error families as published rules over public records.

Every function here reads the public half of an episode and its policy, nothing
else: no latent history, no provenance, no injection label. The generator uses
these detectors to compute truth from the books it has just mutated; a policy
that applies the same published rules to what the tools return reaches the same
answer. The rules and conventions are implemented by Team Intuition according to
the Genesis Hackathon case specification and official check definitions.

The families are judged independently. One record may take part in issues of
different families; within a family one discrepancy is one issue.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Any

from . import SCHEMA_VERSION, canon, money
from .errors import EpisodeError
from .store import DRAFT_LIMITS, PublicEpisode, fx_key, receipt_order_conflicts

ALLOCATION = "payment_allocation"
DUPLICATE = "duplicate_invoice"
FX = "fx_mismatch"
CUTOFF = "cutoff"
FAMILIES = (DUPLICATE, ALLOCATION, FX, CUTOFF)  # the order of manifest.issue_types and of truth

ACCOUNTS: Mapping[str, str] = {
    "receivable": "accounts_receivable",
    "revenue": "revenue",
    "bank": "bank",
    "unapplied": "unapplied_receipts",
    "fx_clearing": "fx_clearing",
}
# The one evidence universe (the case's "existing, accessible evidence"): what the env, score_episode and
# validate_truth accept, PublicEpisode.accessible_ids.
_FURTHER_EVIDENCE = (
    "Further evidence ids may be added if a tool returns a record or document for them: a ledger row_id, a "
    "document doc_id, an invoice_id, a payment_id or an fx key (date|source_currency|target_currency)."
)

POLICY: Mapping[str, Any] = {
    # case-draft-2 (20 Nov 2026): the allocation evidence of a receipt in another currency than the invoice also
    # cites the receipt's fx_clearing debit, so the amount follows from the cited records alone; further evidence
    # may be any id a tool returns a record or document for. case-draft-1 is no longer published.
    "policy_version": "case-draft-2",
    "accounts": ACCOUNTS,
    "time": {
        "company_offset": "manifest.period_start",
        "note": (
            "Compare timestamps as instants. The company's local time is the UTC offset written on "
            "manifest.period_start; no daylight-saving change happens inside an episode. A timestamp is inside "
            "the period when period_start <= instant <= period_end, before it when earlier and after it when "
            "later. A local calendar date is the date of the instant at the company's offset, whatever "
            "offset the record itself was written with."
        ),
    },
    "posting": {
        "note": (
            "Each invoice record is posted once: one accounts_receivable debit and one revenue credit for "
            "its total, in its currency, both carrying its invoice_id. A receipt is one bank debit for the "
            "document amount in the document currency, carrying its payment_id, then credits to "
            "accounts_receivable (one row per referenced invoice it settles) and to unapplied_receipts. These "
            "rows carry the instant of the payment document. A "
            "refund returns unapplied credit of a receipt in the invoice currency: a debit to "
            "unapplied_receipts and a credit to bank, later than the receipt, both carrying the payment_id of "
            "the receipt it returns. Rows with neither an invoice_id nor a "
            "payment_id are other journal entries and take no part in any rule below."
        ),
    },
    "duplicates": {
        "policy": "identical_obligation",
        "note": (
            "Two or more invoice records describe one obligation recorded more than once when their "
            "entity_id, currency, issued_at instant, due_at instant and line_items (the list as written, in "
            "order) are all identical. "
            "Records that differ in any of these are separate obligations, however similar the amounts."
        ),
    },
    "allocation": {
        "policy": "referenced_invoice_up_to_open_balance",
        "bank_account": ACCOUNTS["bank"],
        "receivable_account": ACCOUNTS["receivable"],
        "unapplied_account": ACCOUNTS["unapplied"],
        "note": (
            "A receipt is allocated to each invoice in its invoice_refs, in order, up to that invoice's "
            "open balance when the receipt arrives. Only an excess over the open balance stays in "
            "unapplied_receipts as customer credit. Receipts are taken in order of their payment timestamp. An "
            "invoice's open balance is its total minus what this policy required earlier receipts to allocate "
            "to it. An invoice has its full open balance from its record alone: when it was posted plays no "
            "part. The amount a receipt brings is measured in the invoice currency: the document amount "
            "when the currencies are equal, otherwise the translated amount recorded as the fx_clearing "
            "debit of that receipt. A receipt with no invoice_refs has nothing to allocate."
        ),
    },
    "fx": {
        "date_policy": "payment_date",
        "rate_direction": "target_per_source",
        "rounding": "half_up",
        "clearing_account": ACCOUNTS["fx_clearing"],
        "note": (
            "A receipt in another currency than its invoices is translated into the invoice currency at the "
            "fx.csv rate dated on the receipt's local calendar date. One of the two currencies is always the "
            "base currency, and fx.csv quotes each pair in one direction only. A rate is target units per "
            "one source unit: multiply when the receipt currency is the row's source_currency, divide when "
            "it is the row's target_currency. Work in major units, then round once, half up, to the minor "
            "units of the invoice currency. The books show the translation as a credit to fx_clearing for the "
            "document amount in the receipt currency and a debit to fx_clearing for the translated amount in "
            "the invoice currency."
        ),
    },
    "cutoff": {
        "policy": "invoice_issued_at",
        "note": (
            "Revenue belongs to the period that contains the invoice's issued_at. The revenue row of an "
            "invoice must be timestamped on the same side of the period as issued_at: before it, inside it, "
            "or after it. A posting made earlier or later than issued_at on the same side is not an error."
        ),
    },
    "overlap": {
        "note": (
            "Each rule is applied to the records independently. Allocation is measured against the "
            "translated amount that was recorded, so a wrong translation is one fx_mismatch and not also an "
            "allocation shortfall. A duplicate record whose revenue row is also on the wrong side of the "
            "period is a duplicate_invoice and a cutoff: two rules broken, two issues."
        ),
    },
    "finding_conventions": {
        DUPLICATE: {
            "meaning": "One obligation was recorded as two or more invoice records.",
            "affected_ids": "The invoice_id of every record in the group, in any order.",
            "claimed_amount_minor": (
                "The invoice total times (records in the group minus one): the amount recorded in excess, as "
                "a positive integer in minor units of the invoice currency."
            ),
            "evidence_ids": f"The doc_id of every invoice record in the group. {_FURTHER_EVIDENCE}",
        },
        ALLOCATION: {
            "meaning": "A proven receipt was allocated to its referenced invoice for less than the policy requires.",
            "affected_ids": "The invoice_id and the payment_id, in any order.",
            "claimed_amount_minor": (
                "Required allocation minus recorded allocation for that invoice and payment, as a positive "
                "integer in minor units of the invoice currency."
            ),
            "evidence_ids": (
                "The invoice doc_id, the payment doc_id and the row_id of every accounts_receivable row that "
                "carries both that invoice_id and that payment_id (there may be none). When the receipt is in "
                "another currency than the invoice, also the row_id of the receipt's fx_clearing debit (the "
                f"recorded translation, what the receipt brings in the invoice currency). {_FURTHER_EVIDENCE}"
            ),
        },
        FX: {
            "meaning": "The recorded translation of a receipt differs from the translation the policy requires.",
            "affected_ids": "The payment_id.",
            "claimed_amount_minor": (
                "The absolute difference between the recorded and the required translated amount, as a "
                "positive integer in minor units of the invoice currency. Direction is not encoded."
            ),
            "evidence_ids": (
                "The payment doc_id, the id of the fx row the policy selects (date|source_currency|"
                f"target_currency) and the row_id of the receipt's fx_clearing debit. {_FURTHER_EVIDENCE}"
            ),
        },
        CUTOFF: {
            "meaning": "An invoice's revenue row is on another side of the reporting period than its issued_at.",
            "affected_ids": "The invoice_id.",
            "claimed_amount_minor": "The invoice total, as a positive integer in minor units of the invoice currency.",
            "evidence_ids": f"The invoice doc_id and the row_id of its revenue row. {_FURTHER_EVIDENCE}",
        },
    },
}

TEACHING_POLICY: Mapping[str, Any] = {
    "policy_version": "teaching-1",
    "fx": {
        "date_policy": "payment_date",
        "rate_direction": "target_per_source",
        "rounding": "half_up",
        "note": (
            "A foreign-currency amount is translated to the base currency at the fx.csv rate dated on the "
            "payment's local calendar date. A rate is target units per one source unit."
        ),
    },
    "cutoff": {
        "policy": "invoice_issued_at",
        "note": "Revenue belongs to the period that contains the invoice issued_at, read in the company timezone.",
    },
    "allocation": {
        "policy": "referenced_invoice_up_to_open_balance",
        "bank_account": ACCOUNTS["bank"],
        "receivable_account": ACCOUNTS["receivable"],
        "unapplied_account": ACCOUNTS["unapplied"],
        "note": (
            "A bank receipt is allocated to each invoice in its invoice_refs, in order, up to that invoice's "
            "open balance when the receipt arrives. Only an excess over the open balance stays in "
            "unapplied_receipts as customer credit. Receipts are taken in order of their payment timestamp. An "
            "invoice's open balance is its total minus what this policy required earlier receipts to allocate "
            "to it."
        ),
    },
    "finding_conventions": {
        ALLOCATION: {
            "meaning": "A proven receipt was allocated to its referenced invoice for less than the policy requires.",
            "affected_ids": "The invoice_id and the payment_id, in any order.",
            "claimed_amount_minor": (
                "Required allocation minus recorded allocation for that invoice and payment, as a positive "
                "integer in minor units of the invoice currency."
            ),
            "evidence_ids": (
                "The invoice doc_id, the payment doc_id and the row_id of every accounts_receivable row that "
                "carries both that invoice_id and that payment_id. Further record ids may be added."
            ),
        }
    },
}

CASE_SCHEMA_VERSION = "genesis-fintech-draft-2026-11-12/case-1"
# What each published policy version fixes. An episode is one of these or it is not loaded: its own files
# cannot name another version, drop a block, rewrite a rule, narrow the task or loosen the amounts.
CONTRACTS: Mapping[str, Mapping[str, Any]] = {
    TEACHING_POLICY["policy_version"]: {
        "policy": TEACHING_POLICY,
        "issue_types": [ALLOCATION],
        "schema_version": SCHEMA_VERSION,
    },
    POLICY["policy_version"]: {"policy": POLICY, "issue_types": list(FAMILIES), "schema_version": CASE_SCHEMA_VERSION},
}


def validate_contract(episode: PublicEpisode) -> None:
    """Refuse an episode whose policy or manifest is not exactly what a published policy version fixes."""
    version = episode.policy.get("policy_version") if isinstance(episode.policy, Mapping) else None
    contract = CONTRACTS.get(version) if isinstance(version, str) else None
    if contract is None:
        raise EpisodeError("policy.json names no published policy version")
    manifest = episode.manifest
    checks = (
        (episode.policy == contract["policy"], f"policy.json is not the published policy {version}"),
        (
            manifest["schema_version"] == contract["schema_version"],
            f"schema_version does not belong to policy {version}",
        ),
        (
            manifest["issue_types"] == contract["issue_types"],
            f"an episode under {version} declares exactly {contract['issue_types']}",
        ),
        (dict(manifest["limits"]) == DRAFT_LIMITS, f"an episode uses the draft's budget and caps: {DRAFT_LIMITS}"),
        (manifest["rounding"] == {"permitted": ["half_up"], "default": "half_up"}, "an episode rounds half up"),
        (
            not any(manifest["amount_tolerance_minor"].values()),
            "a shipped policy version has exact amounts: tolerance 0",
        ),
    )
    for holds, message in checks:
        if not holds:
            raise EpisodeError(message)


def when(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp)


def account_names(policy: Mapping[str, Any]) -> Mapping[str, str]:
    """Account names from the policy. The teaching policy names only the three allocation accounts."""
    if "accounts" in policy:
        return policy["accounts"]
    block = policy["allocation"]
    return {"receivable": block["receivable_account"], "bank": block["bank_account"],
            "unapplied": block["unapplied_account"], "revenue": ACCOUNTS["revenue"]}  # fmt: skip


@dataclass(frozen=True)
class Books:
    """The public records, indexed once. Nothing here is private."""

    episode: PublicEpisode
    names: Mapping[str, str]
    invoices: Mapping[str, Mapping[str, Any]]
    by_invoice: Mapping[str, tuple[Mapping[str, Any], ...]]
    by_payment: Mapping[str, tuple[Mapping[str, Any], ...]]
    start: datetime
    end: datetime
    offset: tzinfo

    @property
    def payments(self) -> tuple[Mapping[str, Any], ...]:
        return self.episode.tables["payments"]

    @property
    def base(self) -> str:
        return self.episode.manifest["base_currency"]

    def exponent(self, currency: str) -> int:
        return self.episode.manifest["currencies"][currency]["exponent"]

    def side(self, timestamp: str) -> str:
        """Where an instant lies relative to the reporting period: before, in or after."""
        instant = when(timestamp)
        return "before" if instant < self.start else "after" if instant > self.end else "in"

    def local_date(self, timestamp: str) -> str:
        return when(timestamp).astimezone(self.offset).date().isoformat()

    def invoice_currency(self, payment: Mapping[str, Any]) -> str:
        """The one currency of the invoices a receipt references; its own currency if it references none."""
        currencies = {self.invoices[ref]["currency"] for ref in payment["invoice_refs"]}
        if len(currencies) > 1:
            raise EpisodeError(f"payment {payment['payment_id']}: referenced invoices are in different currencies")
        return currencies.pop() if currencies else payment["currency"]

    def rows(self, payment_id: str, account: str, side: str) -> list[Mapping[str, Any]]:
        return [r for r in self.by_payment.get(payment_id, ()) if r["account"] == self.names[account] and r[side] > 0]

    def rate_row(self, payment: Mapping[str, Any]) -> Mapping[str, Any]:
        """The fx row the policy selects for a cross-currency receipt. Exactly one must exist."""
        pair = {payment["currency"], self.invoice_currency(payment)}
        if self.base not in pair or len(pair) != 2:
            raise EpisodeError(
                f"payment {payment['payment_id']}: a translation must have the base currency on one side"
            )
        day = self.local_date(payment["timestamp"])
        found = [row for row in self.episode.tables["fx"]
                 if row["date"] == day and {row["source_currency"], row["target_currency"]} == pair]  # fmt: skip
        if len(found) != 1:
            raise EpisodeError(
                f"payment {payment['payment_id']}: {len(found)} published rates for {sorted(pair)} on {day}; "
                "the translation would depend on a fact the records do not hold"
            )
        return found[0]

    def required_translation(self, payment: Mapping[str, Any]) -> int:
        """The amount the fx policy requires, in minor units of the invoice currency."""
        row, target = self.rate_row(payment), self.invoice_currency(payment)
        convert = money.convert_minor if row["source_currency"] == payment["currency"] else money.convert_minor_inverse
        return convert(payment["amount_minor"], self.exponent(payment["currency"]), row["rate"],
                       self.exponent(target), self.episode.policy["fx"]["rounding"])  # fmt: skip

    def received(self, payment: Mapping[str, Any]) -> int:
        """What a receipt brings, in the invoice currency: its amount, or its recorded translation."""
        if self.invoice_currency(payment) == payment["currency"]:
            return payment["amount_minor"]
        if "fx_clearing" not in self.names:
            raise EpisodeError("cross-currency allocation is outside the teaching slice")
        translated = self.rows(payment["payment_id"], "fx_clearing", "debit_minor")
        if len(translated) != 1:
            raise EpisodeError(f"payment {payment['payment_id']}: needs exactly one fx_clearing debit")
        return translated[0]["debit_minor"]


def index(episode: PublicEpisode) -> Books:
    by_invoice: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    by_payment: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in episode.tables["ledger"]:
        if row["invoice_id"] is not None:
            by_invoice[row["invoice_id"]].append(row)
        if row["payment_id"] is not None:
            by_payment[row["payment_id"]].append(row)
    start = when(episode.manifest["period_start"])
    offset = start.tzinfo
    if offset is None:  # the loader has already refused this
        raise EpisodeError("manifest.period_start needs a UTC offset")
    return Books(
        episode=episode,
        names=account_names(episode.policy),
        invoices={invoice["invoice_id"]: invoice for invoice in episode.tables["invoices"]},
        by_invoice={key: tuple(rows) for key, rows in by_invoice.items()},
        by_payment={key: tuple(rows) for key, rows in by_payment.items()},
        start=start,
        end=when(episode.manifest["period_end"]),
        offset=offset,
    )


def _issue(kind: str, affected: list[str], amount: int, currency: str, evidence: list[str]) -> dict[str, Any]:
    return {"type": kind, "affected_ids": sorted(affected), "expected_amount_minor": amount, "currency": currency,
            "acceptable_evidence_sets": [sorted(evidence)]}  # fmt: skip


def detect_duplicates(books: Books) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for invoice in books.invoices.values():
        key = (invoice["entity_id"], invoice["currency"], when(invoice["issued_at"]), when(invoice["due_at"]),
               canon.dumps(invoice["line_items"]))  # fmt: skip
        groups[key].append(invoice)
    return [
        _issue(DUPLICATE, [i["invoice_id"] for i in group], group[0]["total_minor"] * (len(group) - 1),
               group[0]["currency"], [i["doc_id"] for i in group])
        for group in groups.values() if len(group) > 1
    ]  # fmt: skip


def detect_allocation(books: Books) -> list[dict[str, Any]]:
    """Allocation shortfalls under the declared policy. Open balances follow what the policy required."""
    if receipt_order_conflicts(books.payments):
        raise EpisodeError("two receipts for one invoice share a timestamp: their order is undefined")
    open_balance = {invoice_id: invoice["total_minor"] for invoice_id, invoice in books.invoices.items()}
    issues = []
    # Ties that remain are between receipts for different invoices, whose order cannot matter;
    # the id only makes the iteration order independent of file order.
    for payment in sorted(books.payments, key=lambda p: (when(p["timestamp"]), p["payment_id"])):
        if not payment["invoice_refs"]:
            continue
        remaining, currency = books.received(payment), books.invoice_currency(payment)
        # Across currencies the receipt brings its recorded translation: that row is evidence too.
        translation = (
            [r["row_id"] for r in books.rows(payment["payment_id"], "fx_clearing", "debit_minor")]
            if currency != payment["currency"]
            else []
        )
        for invoice_id in payment["invoice_refs"]:
            invoice = books.invoices[invoice_id]
            required = min(remaining, open_balance[invoice_id])
            rows = [r for r in books.rows(payment["payment_id"], "receivable", "credit_minor")
                    if r["invoice_id"] == invoice_id]  # fmt: skip
            recorded = sum(r["credit_minor"] for r in rows)
            if recorded > required:
                raise EpisodeError(
                    "over-allocation: more was applied than the policy allows, which no convention here covers"
                )
            if recorded < required:
                evidence = [invoice["doc_id"], payment["doc_id"], *(r["row_id"] for r in rows), *translation]
                issues.append(
                    _issue(ALLOCATION, [invoice_id, payment["payment_id"]], required - recorded, currency, evidence)
                )
            open_balance[invoice_id] -= required
            remaining -= required
    return issues


def detect_fx(books: Books) -> list[dict[str, Any]]:
    issues = []
    for payment in books.payments:
        target = books.invoice_currency(payment)
        if target == payment["currency"]:
            continue
        posted, required = books.received(payment), books.required_translation(payment)
        if posted != required:
            clearing = books.rows(payment["payment_id"], "fx_clearing", "debit_minor")[0]
            evidence = [payment["doc_id"], fx_key(books.rate_row(payment)), clearing["row_id"]]
            issues.append(_issue(FX, [payment["payment_id"]], abs(posted - required), target, evidence))
    return issues


def revenue_row(books: Books, invoice_id: str) -> Mapping[str, Any]:
    rows = [r for r in books.by_invoice.get(invoice_id, ()) if r["account"] == books.names["revenue"]]
    if len(rows) != 1:
        raise EpisodeError(f"invoice {invoice_id}: needs exactly one revenue row, found {len(rows)}")
    return rows[0]


def detect_cutoff(books: Books) -> list[dict[str, Any]]:
    issues = []
    for invoice_id, invoice in books.invoices.items():
        row = revenue_row(books, invoice_id)
        if books.side(row["timestamp"]) != books.side(invoice["issued_at"]):
            evidence = [invoice["doc_id"], row["row_id"]]
            issues.append(_issue(CUTOFF, [invoice_id], invoice["total_minor"], invoice["currency"], evidence))
    return issues


DETECTORS = {DUPLICATE: detect_duplicates, ALLOCATION: detect_allocation, FX: detect_fx, CUTOFF: detect_cutoff}


def detect(episode: PublicEpisode) -> list[dict[str, Any]]:
    """Every issue the published rules find in the public records, for the families the manifest declares."""
    validate_books(episode)
    books = index(episode)
    issues = []
    for family in FAMILIES:
        if family in episode.manifest["issue_types"]:
            issues += sorted(DETECTORS[family](books), key=lambda issue: issue["affected_ids"])
    unknown = sorted(set(episode.manifest["issue_types"]) - set(FAMILIES))
    if unknown:
        raise EpisodeError(f"no published rule for issue types: {unknown}")
    return issues


# ------------------------------------------------------------------ posting structure


def scan_steps(episode: PublicEpisode) -> int:
    """Tool calls needed to read every public record once, at the page limit."""
    page = episode.page_limit()
    return sum(max(1, -(-len(rows) // page)) for rows in episode.tables.values())


def validate_books(episode: PublicEpisode) -> None:
    """The posting structure every rule relies on. A violation is a broken episode, not an issue.

    Balanced books can still be wrong: these identities hold before and after every injected error,
    and say nothing about whether an allocation, a rate, a period or a record is right. They exist so
    that the four rules are the only ways the books can be wrong, and each is decidable.
    """
    if "accounts" not in episode.policy:
        return  # the teaching policy: its own builder checks its identities
    books = index(episode)
    names, limits = books.names, episode.manifest["limits"]

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise EpisodeError(message)

    require(scan_steps(episode) + 1 <= limits["max_steps"],
            f"reading every record takes {scan_steps(episode)} steps: no room left to submit")  # fmt: skip
    pairs = [(row["source_currency"], row["target_currency"]) for row in episode.tables["fx"]]
    require(not any((target, source) in pairs for source, target in pairs), "fx.csv quotes a pair in both directions")
    # The contract of a case episode is fixed by its version. A manifest or a policy file that weakens it (a
    # rewritten rule, a huge tolerance, a missing family) makes another game, and is refused.
    require(episode.policy == POLICY, f"policy.json is not the published policy {POLICY['policy_version']}")
    require(episode.manifest["issue_types"] == list(FAMILIES), f"a case episode declares exactly {list(FAMILIES)}")
    require(dict(limits) == DRAFT_LIMITS, f"a case episode uses the draft's budget and caps: {DRAFT_LIMITS}")
    require(
        episode.manifest["rounding"] == {"permitted": ["half_up"], "default": "half_up"},
        "a case episode rounds half up",
    )
    require(
        not any(episode.manifest["amount_tolerance_minor"].values()), "a case episode has exact amounts: tolerance 0"
    )

    for invoice_id, invoice in books.invoices.items():
        where = f"invoice {invoice_id}"
        issue_rows = [r for r in books.by_invoice.get(invoice_id, ()) if r["payment_id"] is None]
        debit = [r for r in issue_rows if r["account"] == names["receivable"] and r["debit_minor"] > 0]
        credit = [r for r in issue_rows if r["account"] == names["revenue"] and r["credit_minor"] > 0]
        require(len(issue_rows) == 2 and len(debit) == 1 and len(credit) == 1,
                f"{where}: must be posted once, as one receivable debit and one revenue credit")  # fmt: skip
        require(debit[0]["debit_minor"] == credit[0]["credit_minor"] == invoice["total_minor"],
                f"{where}: posting differs from the invoice total")  # fmt: skip
        require(debit[0]["currency"] == credit[0]["currency"] == invoice["currency"], f"{where}: posting currency")
        require(when(debit[0]["timestamp"]) == when(credit[0]["timestamp"]), f"{where}: posting rows differ in time")
        settled = [r for r in books.by_invoice.get(invoice_id, ()) if r["payment_id"] is not None]
        require(all(r["account"] == names["receivable"] and r["credit_minor"] > 0 for r in settled),
                f"{where}: only receivable credits may carry both an invoice_id and a payment_id")  # fmt: skip

    for payment in books.payments:
        payment_id, where = payment["payment_id"], f"payment {payment['payment_id']}"
        rows = books.by_payment.get(payment_id, ())
        require(len({books.invoices[ref]["entity_id"] for ref in payment["invoice_refs"]}) <= 1,
                f"{where}: references invoices of more than one customer")  # fmt: skip
        require(all(r["account"] in (names["bank"], names["receivable"], names["unapplied"], names["fx_clearing"])
                    for r in rows), f"{where}: a row on an account receipts do not use")  # fmt: skip
        banked = books.rows(payment_id, "bank", "debit_minor")
        require(len(banked) == 1 and banked[0]["debit_minor"] == payment["amount_minor"]
                and banked[0]["currency"] == payment["currency"], f"{where}: needs one bank debit for the document amount")  # fmt: skip
        target = books.invoice_currency(payment)
        out, into = (books.rows(payment_id, "fx_clearing", side) for side in ("credit_minor", "debit_minor"))
        if target == payment["currency"]:
            require(not out and not into, f"{where}: a same-currency receipt has no fx_clearing rows")
        else:
            require(len(out) == 1 and out[0]["credit_minor"] == payment["amount_minor"]
                    and out[0]["currency"] == payment["currency"], f"{where}: fx_clearing credit")  # fmt: skip
            require(len(into) == 1 and into[0]["currency"] == target, f"{where}: fx_clearing debit")
            books.rate_row(payment)  # must exist and be unique
        allocations = books.rows(payment_id, "receivable", "credit_minor")
        refs = [r["invoice_id"] for r in allocations]
        require(set(refs) <= set(payment["invoice_refs"]) and len(set(refs)) == len(refs),
                f"{where}: receivable credits must name its referenced invoices, one row each")  # fmt: skip
        parked = books.rows(payment_id, "unapplied", "credit_minor")
        require(all(r["currency"] == target for r in (*allocations, *parked)), f"{where}: settlement currency")
        settled = sum(r["credit_minor"] for r in (*allocations, *parked))
        require(settled == books.received(payment), f"{where}: allocations plus unapplied differ from the receipt")
        returned = books.rows(payment_id, "unapplied", "debit_minor")
        paid_out = books.rows(payment_id, "bank", "credit_minor")
        refunded = sum(r["debit_minor"] for r in returned)
        require(refunded == sum(r["credit_minor"] for r in paid_out), f"{where}: refund rows do not agree")
        require(refunded <= sum(r["credit_minor"] for r in parked), f"{where}: refund exceeds the unapplied credit")
        require(
            not returned or target == payment["currency"], f"{where}: a refund of a translated receipt is not covered"
        )
        require(all(r["currency"] == payment["currency"] and when(r["timestamp"]) > when(payment["timestamp"])
                    for r in (*returned, *paid_out)), f"{where}: a refund is in the receipt's currency and later than it")  # fmt: skip
        require(all(when(r["timestamp"]) == when(payment["timestamp"]) for r in (*banked, *out, *into, *allocations, *parked)),
                f"{where}: receipt rows must carry the instant of the payment document")  # fmt: skip
        require(len(rows) == len(banked) + len(out) + len(into) + len(allocations) + len(parked) + len(returned)
                + len(paid_out), f"{where}: a row that fits no posting rule")  # fmt: skip


def verify_truth(episode: PublicEpisode, truth: Sequence[Any]) -> None:
    """Refuse a truth file that is not what the published rules find in the public records.

    Truth is derived, never trusted: an answer key with an edited amount, an extra evidence set or a
    missing issue describes some other books. `truth` is a sequence of `TruthIssue`.
    """
    derived = sorted(
        (issue["type"], tuple(issue["affected_ids"]), issue["expected_amount_minor"], issue["currency"],
         tuple(sorted(tuple(ids) for ids in issue["acceptable_evidence_sets"])))
        for issue in detect(episode)
    )  # fmt: skip
    stated = sorted(
        (issue.type, tuple(sorted(issue.affected_ids)), issue.expected_amount_minor, issue.currency,
         tuple(sorted(tuple(sorted(ids)) for ids in issue.acceptable_evidence_sets)))
        for issue in truth
    )  # fmt: skip
    if derived != stated:
        raise EpisodeError(
            f"truth.json is not what the published rules find in the public records: {len(stated)} issue(s) stated, "
            f"{len(derived)} derived, {len(set(derived) & set(stated))} in common"
        )
