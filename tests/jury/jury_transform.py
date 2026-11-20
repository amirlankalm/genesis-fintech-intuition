"""The jury's OWN paired-check transformer (Block 4), written from the official safe-transformation rules.

- permute: reorder ledger rows, invoice documents, payment documents and fx rows. line_items and invoice_refs
  keep their order (semantically ordered parts of a document are never shuffled).
- rename: a one-to-one map per id space (row_id, doc_id, invoice_id, payment_id, entity_id), applied to every
  datum and reference: ledger, invoices, payments.invoice_refs, truth affected_ids / evidence sets and every
  provenance string. fx keys (date|source|target) are natural keys and are never renamed.
"""

from __future__ import annotations

import copy
import random
from typing import Any

from jury_data import NULLABLE_LEDGER, all_public_ids

SPACES = ("row_id", "doc_id", "invoice_id", "payment_id", "entity_id")
_ALPHA = "abcdefghijkmnpqrstuvwxyz23456789"


def collect_spaces(ep: dict[str, Any]) -> dict[str, list[str]]:
    sp: dict[str, list[str]] = {s: [] for s in SPACES}

    def add(space: str, v: str | None) -> None:
        if v is not None and v not in sp[space]:
            sp[space].append(v)

    for r in ep["ledger"]:
        add("row_id", r["row_id"])
        add("entity_id", r["entity_id"])
        add("invoice_id", r["invoice_id"])
        add("payment_id", r["payment_id"])
    for d in ep["invoices"]:
        add("doc_id", d["doc_id"])
        add("invoice_id", d["invoice_id"])
        add("entity_id", d["entity_id"])
    for d in ep["payments"]:
        add("doc_id", d["doc_id"])
        add("payment_id", d["payment_id"])
        for ref in d["invoice_refs"]:
            add("invoice_id", ref)
    return sp


def build_maps(ep: dict[str, Any], seed: int) -> dict[str, dict[str, str]]:
    rng = random.Random(seed)
    sp = collect_spaces(ep)
    taken = set(all_public_ids(ep))
    # every old id must live in exactly one space, or a union lookup would be ambiguous
    seen: dict[str, str] = {}
    for space, ids in sp.items():
        for i in ids:
            assert i not in seen, f"precondition: id {i!r} is in two spaces ({seen[i]}, {space})"
            seen[i] = space
    maps: dict[str, dict[str, str]] = {}
    for space, ids in sp.items():
        m = {}
        for old in ids:
            while True:
                new = space[0] + "-" + "".join(rng.choice(_ALPHA) for _ in range(9))
                if new not in taken:
                    break
            taken.add(new)
            m[old] = new
        maps[space] = m
    return maps


def union(maps: dict[str, dict[str, str]]) -> dict[str, str]:
    u: dict[str, str] = {}
    for m in maps.values():
        u.update(m)
    return u


def invert(m: dict[str, str]) -> dict[str, str]:
    inv = {v: k for k, v in m.items()}
    assert len(inv) == len(m), "map is not one-to-one"
    return inv


def _rename_strings(value: Any, u: dict[str, str]) -> Any:
    if isinstance(value, str):
        return u.get(value, value)
    if isinstance(value, list):
        return [_rename_strings(v, u) for v in value]
    if isinstance(value, dict):
        return {k: _rename_strings(v, u) for k, v in value.items()}
    return value


def rename(ep: dict[str, Any], maps: dict[str, dict[str, str]]) -> dict[str, Any]:
    u = union(maps)
    out = copy.deepcopy(ep)
    for r in out["ledger"]:
        r["row_id"] = maps["row_id"][r["row_id"]]
        for k in NULLABLE_LEDGER:
            if r[k] is not None:
                r[k] = maps[k][r[k]]
    for d in out["invoices"]:
        d["doc_id"] = maps["doc_id"][d["doc_id"]]
        d["invoice_id"] = maps["invoice_id"][d["invoice_id"]]
        d["entity_id"] = maps["entity_id"][d["entity_id"]]
    for d in out["payments"]:
        d["doc_id"] = maps["doc_id"][d["doc_id"]]
        d["payment_id"] = maps["payment_id"][d["payment_id"]]
        d["invoice_refs"] = [maps["invoice_id"][x] for x in d["invoice_refs"]]
    for issue in out["truth"]["issues"]:
        issue["affected_ids"] = [u[x] for x in issue["affected_ids"]]
        issue["acceptable_evidence_sets"] = [[u.get(x, x) for x in s] for s in issue["acceptable_evidence_sets"]]
    if out.get("provenance") is not None:
        out["provenance"] = _rename_strings(out["provenance"], u)
    return out


def permute(ep: dict[str, Any], seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    out = copy.deepcopy(ep)
    for table in ("ledger", "invoices", "payments", "fx"):
        rows = out[table]
        original = list(rows)
        for _ in range(10):
            rng.shuffle(rows)
            if len(rows) < 2 or rows != original:
                break
    return out


def map_findings(doc: dict[str, Any], u: dict[str, str]) -> dict[str, Any]:
    out = copy.deepcopy(doc)
    for f in out["findings"]:
        f["affected_ids"] = [u.get(x, x) for x in f["affected_ids"]]
        f["evidence_ids"] = [u.get(x, x) for x in f["evidence_ids"]]
    return out


def map_record(rec: dict[str, Any], u: dict[str, str]) -> dict[str, Any]:
    return _rename_strings(rec, u)
