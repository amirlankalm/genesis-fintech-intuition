"""Jury-side episode I/O: read and write the flat episode directory of ADAPTER.md section 4.

Written blind from docs/ADAPTER.md; it does not import anything from the team's package.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import os
from pathlib import Path
from typing import Any

LEDGER_FIELDS = [
    "row_id",
    "timestamp",
    "account",
    "debit_minor",
    "credit_minor",
    "currency",
    "entity_id",
    "invoice_id",
    "payment_id",
]
FX_FIELDS = ["date", "source_currency", "target_currency", "rate"]
NULLABLE_LEDGER = ("entity_id", "invoice_id", "payment_id")
TABLES = ("ledger", "invoices", "payments", "fx")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def read_csv(path: Path) -> list[dict[str, str]]:
    text = _read_text(path)
    return [dict(r) for r in csv.DictReader(io.StringIO(text))]


def ledger_from_csv(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        rec: dict[str, Any] = {k: r[k] for k in LEDGER_FIELDS}
        rec["debit_minor"] = int(r["debit_minor"])
        rec["credit_minor"] = int(r["credit_minor"])
        for k in NULLABLE_LEDGER:
            rec[k] = r[k] if r[k] != "" else None
        out.append(rec)
    return out


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in _read_text(path).splitlines() if line.strip()]


def fx_key(row: dict[str, Any]) -> str:
    return f"{row['date']}|{row['source_currency']}|{row['target_currency']}"


def read_episode(directory: str | os.PathLike) -> dict[str, Any]:
    d = Path(directory)
    ep: dict[str, Any] = {
        "manifest": json.loads(_read_text(d / "manifest.json")),
        "policy": json.loads(_read_text(d / "policy.json")),
        "ledger": ledger_from_csv(read_csv(d / "ledger.csv")),
        "invoices": read_jsonl(d / "invoices.jsonl"),
        "payments": read_jsonl(d / "payments.jsonl"),
        "fx": [{k: r[k] for k in FX_FIELDS} for r in read_csv(d / "fx.csv")],
        "truth": json.loads(_read_text(d / "truth.json")),
    }
    prov = d / "provenance.json"
    ep["provenance"] = json.loads(_read_text(prov)) if prov.exists() else None
    return ep


def write_episode(directory: str | os.PathLike, ep: dict[str, Any]) -> None:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps(ep["manifest"], indent=2, ensure_ascii=False), encoding="utf-8")
    (d / "policy.json").write_text(json.dumps(ep["policy"], indent=2, ensure_ascii=False), encoding="utf-8")
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(LEDGER_FIELDS)
    for r in ep["ledger"]:
        w.writerow(["" if r[k] is None else str(r[k]) for k in LEDGER_FIELDS])
    (d / "ledger.csv").write_text(buf.getvalue(), encoding="utf-8")
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(FX_FIELDS)
    for r in ep["fx"]:
        w.writerow([r[k] for k in FX_FIELDS])
    (d / "fx.csv").write_text(buf.getvalue(), encoding="utf-8")
    for name in ("invoices", "payments"):
        lines = [json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in ep[name]]
        (d / f"{name}.jsonl").write_text("".join(x + "\n" for x in lines), encoding="utf-8")
    (d / "truth.json").write_text(json.dumps(ep["truth"], indent=2, ensure_ascii=False), encoding="utf-8")
    if ep.get("provenance") is not None:
        (d / "provenance.json").write_text(json.dumps(ep["provenance"], indent=2, ensure_ascii=False), encoding="utf-8")


def clone(ep: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(ep)


def table_records(ep: dict[str, Any], table: str) -> list[dict[str, Any]]:
    return ep[table]


def all_public_ids(ep: dict[str, Any]) -> set[str]:
    """Every id string of every id space plus fx keys and the episode_id (used to choose U)."""
    ids: set[str] = {ep["manifest"]["episode_id"]}
    for r in ep["ledger"]:
        ids.add(r["row_id"])
        for k in NULLABLE_LEDGER:
            if r[k] is not None:
                ids.add(r[k])
    for doc in ep["invoices"]:
        ids.update([doc["doc_id"], doc["invoice_id"], doc["entity_id"]])
    for doc in ep["payments"]:
        ids.update([doc["doc_id"], doc["payment_id"], *doc["invoice_refs"]])
    for r in ep["fx"]:
        ids.add(fx_key(r))
    return ids


def choose_unknown_id(ep: dict[str, Any], base: str = "U") -> str:
    """U is chosen after reading the data: a string that is in no id space of the fixture."""
    ids = all_public_ids(ep)
    candidate = base
    n = 0
    while candidate in ids:
        n += 1
        candidate = f"{base}{n}"
    return candidate


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
