"""From a latent company history to posted books, with a clerk's errors applied.

Order of construction:

1. a latent history (invoices, receipts, refunds, other entries, rates) written by hand or by `world.py`;
2. `derive` posts it exactly as the published policy requires: the clean books;
3. `derive` again with the clerk's errors, one more each time: the books as an erring clerk kept them;
4. the difference between two consecutive versions is recorded, with before and after values, as provenance;
5. truth is computed by `families.detect` from the final public records. It never sees the errors;
6. what the errors should have caused is compared with what the detector found. A mismatch refuses the episode.

Row and document order, and every id, come from keyed labels that say nothing about what a record is.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import tzinfo
from typing import Any

from . import canon, money
from .errors import EpisodeError
from .families import (
    ACCOUNTS,
    ALLOCATION,
    CASE_SCHEMA_VERSION,
    CUTOFF,
    DUPLICATE,
    FAMILIES,
    FX,
    POLICY,
    detect,
    validate_books,
    when,
)
from .prng import DEV_SECRET, KeyedStream, keyed_hex
from .store import (
    DRAFT_LIMITS,
    INVOICE_KEYS,
    LEDGER_COLUMNS,
    PAYMENT_KEYS,
    PublicEpisode,
    render_public,
    validate_public,
)
from .truth import TruthIssue, validate_truth

BUILDER_VERSION = "case-builder/1"
ID_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
ID_LENGTH = 6
LIMITS = dict(DRAFT_LIMITS)
ENVELOPE = {"ledger_rows": (200, 2000), "documents": (20, 200), "issues": (0, 12)}  # proposed sizes of the draft case

CAUSAL_NOTES = {
    DUPLICATE: "The same invoice was keyed in a second time and given a new number.",
    ALLOCATION: "The clerk applied less of the receipt to the invoice than the policy requires and left the rest unapplied.",
    FX: "The clerk translated the receipt at a rate the policy does not select.",
    CUTOFF: "The invoice was posted with a date on the other side of the period boundary.",
}


@dataclass(frozen=True)
class Derived:
    rows: tuple[Mapping[str, Any], ...]  # ledger rows with a private `key`, no row_id yet
    invoices: tuple[Mapping[str, Any], ...]  # invoice records with a private `key`
    effects: tuple[Mapping[str, Any], ...]  # what each error should cause, computed from the latent side
    allocations: tuple[tuple[str, str, int], ...]  # (payment_id, invoice_id, required) for every settled reference
    translations: tuple[tuple[str, str, int], ...]  # (payment_id, policy rate date, required amount)


def company_offset(world: Mapping[str, Any]) -> tzinfo:
    offset = when(world["period_start"]).tzinfo
    if offset is None:
        raise EpisodeError("period_start needs a UTC offset")
    return offset


def side(world: Mapping[str, Any], timestamp: str) -> str:
    instant = when(timestamp)
    return (
        "before" if instant < when(world["period_start"]) else "after" if instant > when(world["period_end"]) else "in"
    )


def invoice_total(invoice: Mapping[str, Any]) -> int:
    return sum(item["amount_minor"] for item in invoice["line_items"])


def policy_rate(world: Mapping[str, Any], payment: Mapping[str, Any], target: str) -> Mapping[str, Any]:
    """The rate row the fx policy selects: dated on the receipt's local calendar date."""
    day = when(payment["timestamp"]).astimezone(company_offset(world)).date().isoformat()
    pair = {payment["currency"], target}
    rows = [r for r in world["fx"] if r["date"] == day and {r["source_currency"], r["target_currency"]} == pair]
    if len(rows) != 1 or world["base_currency"] not in pair:
        raise EpisodeError(f"payment {payment['payment_id']}: no single published rate for {sorted(pair)} on {day}")
    return rows[0]


def translate(world: Mapping[str, Any], payment: Mapping[str, Any], target: str, rate: str, quoted_from: str) -> int:
    """Receipt amount in minor units of `target`, at `rate` quoted with `quoted_from` as its source currency."""
    exponent = {code: spec["exponent"] for code, spec in world["currencies"].items()}
    convert = money.convert_minor if quoted_from == payment["currency"] else money.convert_minor_inverse
    return convert(
        payment["amount_minor"], exponent[payment["currency"]], rate, exponent[target], POLICY["fx"]["rounding"]
    )


def _row(key: str, timestamp: str, account: str, debit: int, credit: int, currency: str,
         entity_id: str | None, invoice_id: str | None, payment_id: str | None) -> dict[str, Any]:  # fmt: skip
    return {
        "key": key, "timestamp": timestamp, "account": account, "debit_minor": debit, "credit_minor": credit,
        "currency": currency, "entity_id": entity_id, "invoice_id": invoice_id, "payment_id": payment_id,
    }  # fmt: skip


def derive(world: Mapping[str, Any], errors: Sequence[Mapping[str, Any]] = ()) -> Derived:
    """Post the history as the policy requires, except where an error says the clerk did otherwise."""
    offset = company_offset(world)
    invoices = [dict(invoice) for invoice in world["invoices"]]
    by_id = {invoice["invoice_id"]: invoice for invoice in invoices}
    copies: set[str] = set()
    applied_instead: dict[tuple[str, str], tuple[int, int]] = {}
    rate_instead: dict[str, tuple[int, str]] = {}
    effects: list[dict[str, Any] | None] = [None] * len(errors)

    def effect(kind: str, affected: list[str], amount: int, currency: str) -> dict[str, Any]:
        return {"type": kind, "affected_ids": sorted(affected), "amount_minor": amount, "currency": currency}

    for number, error in enumerate(errors):
        family = error["family"]
        if family == DUPLICATE:
            original, copy = by_id.get(error["invoice_id"]), error["copy"]
            if original is None or original["invoice_id"] in copies or copy["invoice_id"] in by_id:
                raise EpisodeError(
                    "duplicate_invoice needs an original that exists and is not itself part of a duplicate"
                )
            record = {**original, "key": "copy:" + copy["invoice_id"], **copy}
            invoices.append(record)
            by_id[record["invoice_id"]] = record
            copies.update((original["invoice_id"], record["invoice_id"]))
            effects[number] = effect(DUPLICATE, [original["invoice_id"], record["invoice_id"]],
                                     invoice_total(original), original["currency"])  # fmt: skip
        elif family == CUTOFF:
            invoice = by_id.get(error["invoice_id"])
            if invoice is None or side(world, error["posted_at"]) == side(world, invoice["issued_at"]):
                raise EpisodeError("cutoff must move an existing invoice's posting to another side of the period")
            invoice["posted_at"] = error["posted_at"]
            effects[number] = effect(CUTOFF, [invoice["invoice_id"]], invoice_total(invoice), invoice["currency"])
        elif family == ALLOCATION:
            applied_instead[(error["payment_id"], error["invoice_id"])] = (number, error["applied_minor"])
        elif family == FX:
            rate_instead[error["payment_id"]] = (number, error["rate"])
        else:
            raise EpisodeError(f"unknown error family: {family}")

    rows: list[dict[str, Any]] = []
    for invoice in invoices:
        total, key = invoice_total(invoice), invoice["invoice_id"]
        common = (invoice["currency"], invoice["entity_id"], key, None)
        rows.append(_row(f"issue:{key}:receivable", invoice["posted_at"], ACCOUNTS["receivable"], total, 0, *common))
        rows.append(_row(f"issue:{key}:revenue", invoice["posted_at"], ACCOUNTS["revenue"], 0, total, *common))

    open_balance = {key: invoice_total(invoice) for key, invoice in by_id.items()}
    entity_of: dict[str, str | None] = {}
    allocations: list[tuple[str, str, int]] = []
    translations: list[tuple[str, str, int]] = []
    for payment in sorted(world["payments"], key=lambda p: (when(p["timestamp"]), p["payment_id"])):
        key, refs = payment["payment_id"], payment["invoice_refs"]
        stamp = when(payment["timestamp"]).astimezone(offset).isoformat()
        entity = entity_of[key] = by_id[refs[0]]["entity_id"] if refs else None
        currencies = {by_id[ref]["currency"] for ref in refs}
        if len(currencies) > 1:
            raise EpisodeError(f"payment {key}: referenced invoices are in different currencies")
        target = currencies.pop() if currencies else payment["currency"]
        rows.append(
            _row(
                f"pay:{key}:bank",
                stamp,
                ACCOUNTS["bank"],
                payment["amount_minor"],
                0,
                payment["currency"],
                entity,
                None,
                key,
            )
        )
        received = payment["amount_minor"]
        if target != payment["currency"]:
            selected = policy_rate(world, payment, target)
            received = required = translate(world, payment, target, selected["rate"], selected["source_currency"])
            translations.append((key, selected["date"], required))
            if key in rate_instead:
                number, rate = rate_instead.pop(key)
                received = translate(world, payment, target, rate, selected["source_currency"])
                if received == required or received <= 0:
                    raise EpisodeError(f"fx_mismatch on {key}: the other rate gives the same amount, or none")
                effects[number] = effect(FX, [key], abs(received - required), target)
            rows.append(
                _row(
                    f"pay:{key}:clearing_out",
                    stamp,
                    ACCOUNTS["fx_clearing"],
                    0,
                    payment["amount_minor"],
                    payment["currency"],
                    entity,
                    None,
                    key,
                )
            )
            rows.append(
                _row(f"pay:{key}:clearing_in", stamp, ACCOUNTS["fx_clearing"], received, 0, target, entity, None, key)
            )
        remaining = parked = received
        for invoice_id in refs:
            applied = required = min(remaining, open_balance[invoice_id])
            if required > 0:
                allocations.append((key, invoice_id, required))
            if (key, invoice_id) in applied_instead:
                number, applied = applied_instead.pop((key, invoice_id))
                if isinstance(applied, bool) or not isinstance(applied, int) or not 0 <= applied < required:
                    raise EpisodeError(
                        f"payment_allocation on {key}/{invoice_id}: must apply less than the {required} required"
                    )
                effects[number] = effect(ALLOCATION, [invoice_id, key], required - applied, target)
            if applied > 0:
                rows.append(
                    _row(
                        f"pay:{key}:receivable:{invoice_id}",
                        stamp,
                        ACCOUNTS["receivable"],
                        0,
                        applied,
                        target,
                        entity,
                        invoice_id,
                        key,
                    )
                )
            open_balance[invoice_id] -= required
            remaining -= required
            parked -= applied
        if parked > 0:
            rows.append(
                _row(f"pay:{key}:unapplied", stamp, ACCOUNTS["unapplied"], 0, parked, target, entity, None, key)
            )
    if applied_instead or rate_instead:
        raise EpisodeError(
            f"errors name receipts that do not exist or need no translation: {[*applied_instead, *rate_instead]}"
        )

    payments = {payment["payment_id"]: payment for payment in world["payments"]}
    for refund in world.get("refunds", ()):
        key, payment = refund["payment_id"], payments[refund["payment_id"]]
        stamp = when(refund["timestamp"]).astimezone(offset).isoformat()
        common = (payment["currency"], entity_of[key], None, key)
        rows.append(_row(f"refund:{key}:unapplied", stamp, ACCOUNTS["unapplied"], refund["amount_minor"], 0, *common))
        rows.append(_row(f"refund:{key}:bank", stamp, ACCOUNTS["bank"], 0, refund["amount_minor"], *common))
    for entry in world.get("entries", ()):
        stamp = when(entry["timestamp"]).astimezone(offset).isoformat()
        common = (entry["currency"], entry.get("entity_id"), None, None)
        rows.append(_row(f"{entry['key']}:debit", stamp, entry["debit_account"], entry["amount_minor"], 0, *common))
        rows.append(_row(f"{entry['key']}:credit", stamp, entry["credit_account"], 0, entry["amount_minor"], *common))
    return Derived(tuple(rows), tuple(invoices), tuple(e for e in effects if e is not None),
                   tuple(allocations), tuple(translations))  # fmt: skip


class Labels:
    """Ids and file order from keyed labels: stable for a record's key, silent about what the record is."""

    def __init__(self, secret: bytes, world: Mapping[str, Any]) -> None:
        self._secret, self._tag = secret, world["tag"]
        self._known: dict[str, str] = dict(world.get("row_ids", {}))
        self._used = set(self._known.values())

    def row_id(self, key: str) -> str:
        if key not in self._known:
            salt = 0
            while True:
                label = "L" + KeyedStream(self._secret, f"id|{self._tag}|{key}|{salt}").token(ID_LENGTH, ID_ALPHABET)
                if label not in self._used:
                    break
                salt += 1
            self._known[key] = label
            self._used.add(label)
        return self._known[key]

    def order(self, key: str) -> str:
        return keyed_hex(self._secret, f"order|{self._tag}|{key}", 16)


def new_id(secret: bytes, tag: str, prefix: str, key: str, taken: set[str]) -> str:
    """A fresh id for a record the generator or an error invents."""
    salt = 0
    while True:
        label = prefix + KeyedStream(secret, f"id|{tag}|{key}|{salt}").token(ID_LENGTH, ID_ALPHABET)
        if label not in taken:
            taken.add(label)
            return label
        salt += 1


def tables(world: Mapping[str, Any], derived: Derived, labels: Labels) -> dict[str, tuple[dict[str, Any], ...]]:
    """Public tables for one version of the books. Each record keeps its private `key` first, for diffing."""
    ledger = [{"key": row["key"], "row_id": labels.row_id(row["key"]),
               **{column: row[column] for column in LEDGER_COLUMNS[1:]}} for row in derived.rows]  # fmt: skip
    ledger.sort(key=lambda row: (when(row["timestamp"]), row["row_id"]))
    invoices = [{"key": invoice["key"], **{k: {**invoice, "total_minor": invoice_total(invoice)}[k] for k in INVOICE_KEYS}}
                for invoice in sorted(derived.invoices, key=lambda i: labels.order(i["key"]))]  # fmt: skip
    payments = [{"key": payment["key"], **{k: payment[k] for k in PAYMENT_KEYS}}
                for payment in sorted(world["payments"], key=lambda p: labels.order(p["key"]))]  # fmt: skip
    fx = sorted(
        (dict(row) for row in world["fx"]), key=lambda r: (r["date"], r["source_currency"], r["target_currency"])
    )
    return {"ledger": tuple(ledger), "invoices": tuple(invoices), "payments": tuple(payments), "fx": tuple(fx)}


def _public(record: Mapping[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in record.items() if name != "key"}


def diff(
    before: Mapping[str, Sequence[Mapping[str, Any]]], after: Mapping[str, Sequence[Mapping[str, Any]]]
) -> list[dict[str, Any]]:
    """Every change between two versions of the books, with before and after values."""
    changes: list[dict[str, Any]] = []
    for table, id_field in (("invoices", "invoice_id"), ("ledger", "row_id")):
        old = {record["key"]: record for record in before[table]}
        new = {record["key"]: record for record in after[table]}
        for key in sorted(set(old) | set(new), key=lambda k: (old.get(k) or new[k])[id_field]):
            if key not in old:
                changes.append({"op": "insert", "table": table, "record": _public(new[key])})
            elif key not in new:
                changes.append({"op": "delete", "table": table, "record": _public(old[key])})
            else:
                changes.extend(
                    {"op": "update", "table": table, "id": old[key][id_field], "field": name,
                     "before": old[key][name], "after": new[key][name]}
                    for name in old[key] if old[key][name] != new[key][name]
                )  # fmt: skip
    return changes


def undo(
    public: Mapping[str, Sequence[Mapping[str, Any]]], injections: Sequence[Mapping[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Reverse the recorded changes on public tables. The result must be the clean books."""
    restored = {table: [dict(record) for record in public[table]] for table in ("invoices", "ledger")}
    id_field = {"invoices": "invoice_id", "ledger": "row_id"}
    for injection in reversed(injections):
        for change in reversed(injection["changes"]):
            records, field = restored[change["table"]], id_field[change["table"]]
            if change["op"] == "insert":
                records[:] = [r for r in records if r[field] != change["record"][field]]
            elif change["op"] == "delete":
                records.append(dict(change["record"]))
            else:
                target = next(r for r in records if r[field] == change["id"])
                if target[change["field"]] != change["after"]:
                    raise EpisodeError("provenance does not describe these records")
                target[change["field"]] = change["before"]
    return {table: sorted(records, key=lambda r: r[id_field[table]]) for table, records in restored.items()}


def assemble(
    world: Mapping[str, Any], version: Mapping[str, Sequence[Mapping[str, Any]]], episode_id: str
) -> PublicEpisode:
    public_tables = {table: tuple(_public(record) for record in records) for table, records in version.items()}
    manifest = {
        "schema_version": CASE_SCHEMA_VERSION,
        "episode_id": episode_id,
        "base_currency": world["base_currency"],
        "period_start": world["period_start"],
        "period_end": world["period_end"],
        "timezone": world["timezone"],
        "counts": {
            "ledger_rows": len(public_tables["ledger"]),
            "documents": len(public_tables["invoices"]) + len(public_tables["payments"]),
            "fx_rates": len(public_tables["fx"]),
        },
        "currencies": world["currencies"],
        "rounding": {"permitted": ["half_up"], "default": "half_up"},
        "amount_tolerance_minor": {code: 0 for code in world["currencies"]},
        "issue_types": list(FAMILIES),
        "limits": LIMITS,
    }
    return PublicEpisode(manifest=manifest, policy=POLICY, tables=public_tables)


def signature(issue: Mapping[str, Any]) -> tuple[Any, ...]:
    amount = issue["amount_minor"] if "amount_minor" in issue else issue["expected_amount_minor"]
    return (issue["type"], tuple(issue["affected_ids"]), amount, issue["currency"])


def build(
    world: Mapping[str, Any],
    errors: Sequence[Mapping[str, Any]],
    *,
    secret: bytes = DEV_SECRET,
    variant: str = "custom",
    envelope: bool = False,
) -> tuple[PublicEpisode, tuple[TruthIssue, ...], dict[str, Any]]:
    """One episode from a latent history and a list of clerk errors: (public episode, truth, provenance)."""
    labels = Labels(secret, world)
    stages = [derive(world, errors[:count]) for count in range(len(errors) + 1)]
    versions = [tables(world, stage, labels) for stage in stages]
    episode_id = "ep-" + keyed_hex(secret, f"episode|{BUILDER_VERSION}|{world['tag']}|{canon.digest(list(errors))}", 10)

    clean = assemble(world, versions[0], episode_id)
    validate_public(clean)
    validate_books(clean)  # the identities hold before any error is injected
    if detect(clean):
        raise EpisodeError(f"{variant}: the clean books already break a published rule")

    for version in versions[1:-1]:  # the identities hold after every single error, not only after the last
        between = assemble(world, version, episode_id)
        validate_public(between)
        validate_books(between)
    public = assemble(world, versions[-1], episode_id)
    validate_public(public)
    issues = detect(public)  # the identities are checked again here; the detector never sees `errors`
    truth = tuple(
        TruthIssue(
            issue_id="truth-" + keyed_hex(secret, f"issue|{BUILDER_VERSION}|{episode_id}|{number}", 12),
            type=issue["type"],
            affected_ids=frozenset(issue["affected_ids"]),
            expected_amount_minor=issue["expected_amount_minor"],
            currency=issue["currency"],
            acceptable_evidence_sets=tuple(frozenset(ids) for ids in issue["acceptable_evidence_sets"]),
        )
        for number, issue in enumerate(issues, start=1)
    )
    validate_truth(truth, public)
    expected, found = sorted(map(signature, stages[-1].effects)), sorted(map(signature, issues))
    if expected != found:
        raise EpisodeError(
            f"{variant}: the errors should cause {expected} but the detector derived {found} from the records"
        )
    if envelope:
        sizes = {**public.manifest["counts"], "issues": len(truth)}
        for name, (low, high) in ENVELOPE.items():
            if not low <= sizes[name] <= high:
                raise EpisodeError(f"{variant}: {name} = {sizes[name]} is outside the case envelope {low}..{high}")
    provenance = {
        "builder": BUILDER_VERSION,
        "variant": variant,
        "canary": "canary-" + keyed_hex(secret, f"canary|{BUILDER_VERSION}|{episode_id}", 16),
        "injections": [
            {
                "injection_id": f"inj-{number}",
                "family": error["family"],
                "error": dict(error),
                "expected": stages[number].effects[number - 1],
                "causal_note": CAUSAL_NOTES[error["family"]],
                "changes": diff(versions[number - 1], versions[number]),
            }
            for number, error in enumerate(errors, start=1)
        ],
    }
    return public, truth, provenance


def render(
    public: PublicEpisode, truth: Sequence[TruthIssue], provenance: Mapping[str, Any]
) -> tuple[dict[str, str], dict[str, str]]:
    """File contents: (public files, private files)."""
    private = {
        "truth.json": json.dumps({"issues": [issue.to_json() for issue in truth]}, indent=2, ensure_ascii=True) + "\n",
        "provenance.json": json.dumps(provenance, indent=2, ensure_ascii=True) + "\n",
    }
    return render_public(public), private
