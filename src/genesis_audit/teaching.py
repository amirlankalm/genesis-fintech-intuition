"""The teaching episode: one invented company, built causally.

Order of construction (nothing here is random):

1. a hand-specified latent history: invoices and bank receipts;
2. a clean ledger derived from that history under the declared allocation policy;
3. accounting identities checked on the clean ledger;
4. one typed mutation applied, with before/after values recorded as provenance. It
   moves value between rows that exist in the clean books too, so the faulty episode
   has no extra row, id or count to give it away;
5. truth recomputed from the mutated public records, not copied from the mutation label.

Teaching fixture only. It is not an official case fixture and the conventions in
POLICY are proposals, not contest rules.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION
from .errors import EpisodeError
from .families import TEACHING_POLICY, detect_allocation, index
from .prng import DEV_SECRET, keyed_hex
from .store import PublicEpisode, render_public, validate_public
from .truth import TruthIssue, validate_truth

ISSUE_TYPE = "payment_allocation"
ACCOUNT_RECEIVABLE = "accounts_receivable"
ACCOUNT_REVENUE = "revenue"
ACCOUNT_BANK = "bank"
ACCOUNT_UNAPPLIED = "unapplied_receipts"
BUILDER_VERSION = "teaching-fixture-builder/2"

LIMITS = {"max_steps": 100, "page_limit": 50, "max_findings": 30, "max_evidence_ids": 10, "max_explanation_chars": 1000}

LATENT: Mapping[str, Any] = {
    "base_currency": "KZT",
    "currencies": {"KZT": {"exponent": 2}, "USD": {"exponent": 2}},
    "timezone": "Asia/Almaty",
    "period_start": "2026-10-01T00:00:00+05:00",
    "period_end": "2026-10-31T23:59:59+05:00",
    "invoices": [
        {
            "doc_id": "D31", "invoice_id": "I7", "entity_id": "E4",
            "issued_at": "2026-10-05T10:00:00+05:00", "due_at": "2026-10-20T18:00:00+05:00", "currency": "KZT",
            "line_items": [
                {"description": "Robotics workshop session", "quantity": 5, "unit_price_minor": 50000, "amount_minor": 250000}
            ],
        },
        {
            "doc_id": "D12", "invoice_id": "I3", "entity_id": "E8",
            "issued_at": "2026-10-07T11:30:00+05:00", "due_at": "2026-10-28T18:00:00+05:00", "currency": "KZT",
            "line_items": [
                {"description": "Data-literacy course seat", "quantity": 2, "unit_price_minor": 125000, "amount_minor": 250000}
            ],
        },
    ],
    "payments": [
        {"doc_id": "D44", "payment_id": "P9", "timestamp": "2026-10-14T09:15:00+05:00", "currency": "KZT",
         "amount_minor": 260000, "invoice_refs": ["I7"]},
        {"doc_id": "D27", "payment_id": "P2", "timestamp": "2026-10-16T14:00:00+05:00", "currency": "KZT",
         "amount_minor": 150000, "invoice_refs": ["I3"]},
        {"doc_id": "D36", "payment_id": "P5", "timestamp": "2026-10-23T16:45:00+05:00", "currency": "KZT",
         "amount_minor": 120000, "invoice_refs": ["I3"]},
    ],
    "fx": [
        {"date": "2026-10-14", "source_currency": "USD", "target_currency": "KZT", "rate": "512.40"},
        {"date": "2026-10-16", "source_currency": "USD", "target_currency": "KZT", "rate": "513.85"},
        {"date": "2026-10-23", "source_currency": "USD", "target_currency": "KZT", "rate": "515.10"},
    ],
    # Row ids carry no meaning: not sequential, not grouped by event, and the rows the
    # error touches are neither the smallest nor the largest.
    "row_ids": {
        "issue:I7:receivable": "L21", "issue:I7:revenue": "L08",
        "issue:I3:receivable": "L15", "issue:I3:revenue": "L03",
        "pay:P9:bank": "L19", "pay:P9:receivable:I7": "L11", "pay:P9:unapplied": "L13",
        "pay:P2:bank": "L05", "pay:P2:receivable:I3": "L17",
        "pay:P5:bank": "L09", "pay:P5:receivable:I3": "L23", "pay:P5:unapplied": "L06",
    },
}  # fmt: skip

POLICY: Mapping[str, Any] = TEACHING_POLICY  # published in families.py, beside the case policy

# Evaluator-side names -> (public episode_id, injections). The public id reveals nothing, and the two
# variants show the policy the same manifest apart from that id: the mutation moves value between
# rows that exist in both, so not even the row count differs.
VARIANTS: Mapping[str, Mapping[str, Any]] = {
    "teaching_b": {
        "episode_id": "ep-4c1f09",
        "injections": [{"invoice_id": "I7", "payment_id": "P9", "applied_minor": 150000}],
    },
    "teaching_b_p5": {
        "episode_id": "ep-71b3e2",
        "injections": [{"invoice_id": "I3", "payment_id": "P5", "applied_minor": 60000}],
    },
    "teaching_b_both": {
        "episode_id": "ep-d05a9c",
        "injections": [
            {"invoice_id": "I7", "payment_id": "P9", "applied_minor": 150000},
            {"invoice_id": "I3", "payment_id": "P5", "applied_minor": 60000},
        ],
    },
    "teaching_b_clean": {"episode_id": "ep-a27d35", "injections": []},
}


def _when(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp)


def _row(row_id: str, timestamp: str, account: str, debit: int, credit: int, currency: str,
         entity_id: str | None, invoice_id: str | None, payment_id: str | None) -> dict[str, Any]:  # fmt: skip
    return {
        "row_id": row_id, "timestamp": timestamp, "account": account, "debit_minor": debit, "credit_minor": credit,
        "currency": currency, "entity_id": entity_id, "invoice_id": invoice_id, "payment_id": payment_id,
    }  # fmt: skip


def invoice_total(invoice: Mapping[str, Any]) -> int:
    return sum(item["amount_minor"] for item in invoice["line_items"])


def derive_clean_ledger(latent: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Post every invoice and receipt exactly as the declared allocation policy requires."""
    row_ids = latent["row_ids"]
    invoices = {invoice["invoice_id"]: invoice for invoice in latent["invoices"]}
    timeline = [(_when(i["issued_at"]), 0, i["invoice_id"], i) for i in latent["invoices"]]
    timeline += [(_when(p["timestamp"]), 1, p["payment_id"], p) for p in latent["payments"]]
    open_balance: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    for _, kind, key, event in sorted(timeline, key=lambda entry: entry[:3]):
        if kind == 0:
            total = invoice_total(event)
            open_balance[key] = total
            common = (event["currency"], event["entity_id"], key, None)
            rows.append(
                _row(row_ids[f"issue:{key}:receivable"], event["issued_at"], ACCOUNT_RECEIVABLE, total, 0, *common)
            )
            rows.append(_row(row_ids[f"issue:{key}:revenue"], event["issued_at"], ACCOUNT_REVENUE, 0, total, *common))
            continue
        entity = invoices[event["invoice_refs"][0]]["entity_id"] if event["invoice_refs"] else None
        stamp, currency, remaining = event["timestamp"], event["currency"], event["amount_minor"]
        rows.append(_row(row_ids[f"pay:{key}:bank"], stamp, ACCOUNT_BANK, remaining, 0, currency, entity, None, key))
        for invoice_id in event["invoice_refs"]:
            applied = min(remaining, open_balance[invoice_id])
            if applied > 0:
                row_id = row_ids[f"pay:{key}:receivable:{invoice_id}"]
                rows.append(_row(row_id, stamp, ACCOUNT_RECEIVABLE, 0, applied, currency, entity, invoice_id, key))
                open_balance[invoice_id] -= applied
                remaining -= applied
        if remaining > 0:
            rows.append(
                _row(
                    row_ids[f"pay:{key}:unapplied"], stamp, ACCOUNT_UNAPPLIED, 0, remaining, currency, entity, None, key
                )
            )
    return rows


def check_identities(rows: list[dict[str, Any]], latent: Mapping[str, Any]) -> None:
    """What must hold for this builder's books, before and after a partial-allocation mutation.

    Only the first check (debits equal credits) is an invariant of every valid episode, and the
    loader enforces it. The other two describe this family's clean and mutated books. A duplicate
    posting, for one, would break "receivable debit equals invoice total" on purpose: for that
    family the identity is the symptom, not an invariant.
    """
    for currency in latent["currencies"]:
        debit = sum(r["debit_minor"] for r in rows if r["currency"] == currency)
        credit = sum(r["credit_minor"] for r in rows if r["currency"] == currency)
        if debit != credit:
            raise EpisodeError(f"{currency}: debits {debit} != credits {credit}")
    for payment in latent["payments"]:
        mine = [r for r in rows if r["payment_id"] == payment["payment_id"]]
        banked = sum(r["debit_minor"] for r in mine if r["account"] == ACCOUNT_BANK)
        credited = sum(r["credit_minor"] for r in mine)
        if not banked == credited == payment["amount_minor"]:
            raise EpisodeError(f"payment {payment['payment_id']}: bank {banked}, credits {credited}, document differs")
    for invoice in latent["invoices"]:
        mine = [r for r in rows if r["invoice_id"] == invoice["invoice_id"] and r["account"] == ACCOUNT_RECEIVABLE]
        billed, settled = sum(r["debit_minor"] for r in mine), sum(r["credit_minor"] for r in mine)
        if billed != invoice_total(invoice) or settled > billed:
            raise EpisodeError(f"invoice {invoice['invoice_id']}: receivable {billed}, settled {settled}")


def inject_partial_allocation(
    rows: list[dict[str, Any]], latent: Mapping[str, Any], *, invoice_id: str, payment_id: str, applied_minor: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Typed mutation: apply only part of a receipt to its invoice and park the rest as unapplied.

    If the payment already has an unapplied row the value is added to it, so the row
    count does not change; otherwise one row is inserted.
    """
    positions = [
        index
        for index, row in enumerate(rows)
        if row["account"] == ACCOUNT_RECEIVABLE and row["invoice_id"] == invoice_id and row["payment_id"] == payment_id
    ]
    if len(positions) != 1:
        raise EpisodeError("partial_allocation needs exactly one allocation row for the invoice and payment")
    target = rows[positions[0]]
    before = target["credit_minor"]
    if isinstance(applied_minor, bool) or not isinstance(applied_minor, int) or not 0 < applied_minor < before:
        raise EpisodeError("partial_allocation must apply a positive amount smaller than the clean allocation")
    moved = before - applied_minor
    mutated = [dict(row) for row in rows]
    mutated[positions[0]]["credit_minor"] = applied_minor
    changes: list[dict[str, Any]] = [
        {"op": "update", "table": "ledger", "row_id": target["row_id"], "field": "credit_minor",
         "before": before, "after": applied_minor}
    ]  # fmt: skip
    parked = [
        i for i, row in enumerate(rows) if row["payment_id"] == payment_id and row["account"] == ACCOUNT_UNAPPLIED
    ]
    if parked:
        row = mutated[parked[0]]
        changes.append({"op": "update", "table": "ledger", "row_id": row["row_id"], "field": "credit_minor",
                        "before": row["credit_minor"], "after": row["credit_minor"] + moved})  # fmt: skip
        row["credit_minor"] += moved
    else:
        key = f"pay:{payment_id}:unapplied"
        if key not in latent["row_ids"]:
            raise EpisodeError(f"the latent history names no row id for {key}")
        inserted = _row(latent["row_ids"][key], target["timestamp"], ACCOUNT_UNAPPLIED, 0,
                        moved, target["currency"], target["entity_id"], None, payment_id)  # fmt: skip
        mutated.insert(positions[0] + 1, inserted)
        changes.append({"op": "insert", "table": "ledger", "after_row_id": target["row_id"], "row": inserted})
    change = {
        "family": ISSUE_TYPE,
        "mutation": "partial_allocation",
        "target": {"invoice_id": invoice_id, "payment_id": payment_id},
        "causal_note": "The clerk applied part of the receipt to the invoice and left the rest unapplied.",
        "changes": changes,
    }
    return mutated, change


def detect_allocation_issues(episode: PublicEpisode) -> list[dict[str, Any]]:
    """Recompute allocation shortfalls from public records alone, under the declared policy.

    One implementation of the rule serves every episode: `families.detect_allocation`.
    """
    return detect_allocation(index(episode))


def build_from(
    latent: Mapping[str, Any],
    episode_id: str,
    injections: Sequence[Mapping[str, Any]],
    *,
    secret: bytes = DEV_SECRET,
    variant: str = "custom",
) -> tuple[PublicEpisode, tuple[TruthIssue, ...], dict[str, Any]]:
    """Build one episode from a latent history: (public episode, truth, provenance).

    Private tokens (issue ids, the canary) are keyed with `secret` and say nothing
    about the answer. The secret never changes a public file.
    """
    rows = derive_clean_ledger(latent)
    check_identities(rows, latent)
    recorded = []
    for number, spec in enumerate(injections, start=1):
        rows, change = inject_partial_allocation(rows, latent, **spec)
        recorded.append({"injection_id": f"inj-{number}", **change})
    check_identities(rows, latent)
    keys = ("doc_id", "invoice_id", "entity_id", "issued_at", "due_at", "currency", "total_minor", "line_items")
    invoices = tuple(
        {key: {**invoice, "total_minor": invoice_total(invoice)}[key] for key in keys} for invoice in latent["invoices"]
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "episode_id": episode_id,
        "base_currency": latent["base_currency"],
        "period_start": latent["period_start"],
        "period_end": latent["period_end"],
        "timezone": latent["timezone"],
        "counts": {
            "ledger_rows": len(rows),
            "documents": len(invoices) + len(latent["payments"]),
            "fx_rates": len(latent["fx"]),
        },
        "currencies": latent["currencies"],
        "rounding": {"permitted": ["half_up"], "default": "half_up"},
        "amount_tolerance_minor": {code: 0 for code in latent["currencies"]},
        "issue_types": [ISSUE_TYPE],
        "limits": LIMITS,
    }
    public = PublicEpisode(
        manifest=manifest,
        policy=POLICY,
        tables={
            "ledger": tuple(rows),
            "invoices": invoices,
            "payments": tuple(latent["payments"]),
            "fx": tuple(latent["fx"]),
        },
    )
    validate_public(public)
    truth = tuple(
        TruthIssue(
            issue_id="truth-" + keyed_hex(secret, f"issue|{BUILDER_VERSION}|{episode_id}|{number}", 12),
            type=issue["type"],
            affected_ids=frozenset(issue["affected_ids"]),
            expected_amount_minor=issue["expected_amount_minor"],
            currency=issue["currency"],
            acceptable_evidence_sets=tuple(frozenset(ids) for ids in issue["acceptable_evidence_sets"]),
        )
        for number, issue in enumerate(detect_allocation_issues(public), start=1)
    )
    validate_truth(truth, public)
    # The detector never sees the injection. Each injected change must be found again, as that pair and that amount.
    detected = sorted((sorted(issue.affected_ids), issue.expected_amount_minor) for issue in truth)
    injected = sorted(
        (sorted(change["target"].values()), change["changes"][0]["before"] - change["changes"][0]["after"])
        for change in recorded
    )
    if detected != injected:
        raise EpisodeError(f"{variant}: injected {injected} but the detector derived {detected} from the records")
    provenance = {
        "builder": BUILDER_VERSION,
        "variant": variant,
        "canary": "canary-" + keyed_hex(secret, f"canary|{BUILDER_VERSION}|{episode_id}", 16),
        "injections": recorded,
    }
    return public, truth, provenance


def build(name: str, secret: bytes = DEV_SECRET) -> tuple[PublicEpisode, tuple[TruthIssue, ...], dict[str, Any]]:
    """Build one teaching variant."""
    variant = VARIANTS[name]
    return build_from(LATENT, variant["episode_id"], variant["injections"], secret=secret, variant=name)


def render(name: str, secret: bytes = DEV_SECRET) -> tuple[dict[str, str], dict[str, str]]:
    """File contents for a variant: (public files, private files)."""
    public, truth, provenance = build(name, secret)
    private = {
        "truth.json": json.dumps({"issues": [issue.to_json() for issue in truth]}, indent=2, ensure_ascii=True) + "\n",
        "provenance.json": json.dumps(provenance, indent=2, ensure_ascii=True) + "\n",
    }
    return render_public(public), private


def write_all(public_root: Path, private_root: Path, secret: bytes = DEV_SECRET) -> list[Path]:
    """Write every teaching variant. Returns the files written."""
    written = []
    for name in VARIANTS:
        public_files, private_files = render(name, secret)
        for root, files in ((public_root, public_files), (private_root, private_files)):
            directory = root / name
            directory.mkdir(parents=True, exist_ok=True)
            for filename, text in files.items():
                (directory / filename).write_text(text, encoding="utf-8")
                written.append(directory / filename)
    return written
