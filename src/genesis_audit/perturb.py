"""Harmless perturbations: consistent id renaming and row reordering.

The economic facts and the policy do not change. A correct environment must give
the oracle the same findings (after renaming) and the same reward on the
perturbed episode. The perturbation is driven by a keyed stream, so the new ids
do not reveal the seed to anyone without the evaluator's key.
"""

from __future__ import annotations

from typing import Any

from . import ENV_VERSION
from .episodes import LoadedEpisode
from .prng import KeyedStream, keyed_hex
from .store import PublicEpisode, validate_public
from .truth import TruthIssue, validate_truth

ID_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
ID_LENGTH = 6


def _collect_ids(public: PublicEpisode) -> list[tuple[str, list[str]]]:
    """Every renamable id, grouped by kind prefix, in a stable order."""
    ledger, invoices, payments = (public.tables[name] for name in ("ledger", "invoices", "payments"))
    entities = {record["entity_id"] for record in (*ledger, *invoices) if record["entity_id"] is not None}
    return [
        ("L", sorted(row["row_id"] for row in ledger)),
        ("D", sorted(record["doc_id"] for record in (*invoices, *payments))),
        ("I", sorted(record["invoice_id"] for record in invoices)),
        ("P", sorted(record["payment_id"] for record in payments)),
        ("E", sorted(entities)),
    ]


def perturb(
    loaded: LoadedEpisode, *, key: bytes, seed: int, rename_ids: bool, shuffle_rows: bool
) -> tuple[LoadedEpisode, dict[str, str]]:
    """Return the perturbed episode and the old-id -> new-id mapping (evaluator-side)."""
    public = loaded.public
    label = f"perturb|{ENV_VERSION}|{public.manifest['episode_id']}|{seed}|{int(rename_ids)}{int(shuffle_rows)}"
    stream = KeyedStream(key, label)
    mapping: dict[str, str] = {}
    if rename_ids:
        used: set[str] = set()
        for prefix, ids in _collect_ids(public):
            for old in ids:
                new = prefix + stream.token(ID_LENGTH, ID_ALPHABET)
                while new in used:
                    new = prefix + stream.token(ID_LENGTH, ID_ALPHABET)
                used.add(new)
                mapping[old] = new

    def renamed(value: Any) -> Any:
        return mapping.get(value, value)

    def rename_fields(record: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
        return {name: (renamed(value) if name in fields else value) for name, value in record.items()}

    tables = {
        "ledger": [
            rename_fields(dict(r), ("row_id", "entity_id", "invoice_id", "payment_id")) for r in public.tables["ledger"]
        ],
        "invoices": [rename_fields(dict(r), ("doc_id", "invoice_id", "entity_id")) for r in public.tables["invoices"]],
        "payments": [
            {
                **rename_fields(dict(r), ("doc_id", "payment_id")),
                "invoice_refs": [renamed(ref) for ref in r["invoice_refs"]],
            }
            for r in public.tables["payments"]
        ],
        "fx": [dict(r) for r in public.tables["fx"]],
    }
    if shuffle_rows:
        tables = {name: stream.shuffled(rows) for name, rows in tables.items()}
    manifest = {**public.manifest, "episode_id": "ep-" + keyed_hex(key, "episode|" + label, 10)}
    new_public = PublicEpisode(manifest, public.policy, {name: tuple(rows) for name, rows in tables.items()})
    truth = tuple(
        TruthIssue(
            issue_id="truth-" + keyed_hex(key, f"issue|{label}|{position}", 12),
            type=issue.type,
            affected_ids=frozenset(renamed(value) for value in issue.affected_ids),
            expected_amount_minor=issue.expected_amount_minor,
            currency=issue.currency,
            acceptable_evidence_sets=tuple(
                frozenset(renamed(value) for value in evidence) for evidence in issue.acceptable_evidence_sets
            ),
        )
        for position, issue in enumerate(sorted(loaded.truth, key=lambda item: item.issue_id))
    )
    validate_public(new_public)
    validate_truth(truth, new_public)
    return LoadedEpisode(public=new_public, truth=truth), mapping
