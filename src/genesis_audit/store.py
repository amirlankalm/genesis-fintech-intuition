"""Public episode records: loading, validation, lookup and stable paging.

This module only ever touches the public half of an episode. It is the single
place that turns a tool call into records, and every failure a policy can cause
is raised as a PolicyVisibleError with a fixed message.

Parsing is key-order insensitive: an object is accepted when its key *set* is the
expected one, and is rebuilt in the canonical order, so what a policy observes does
not depend on how a file was written. Validation comes in two strengths (Checks):
format checks always refuse; consistency checks refuse in strict mode and become
evaluator-log warnings otherwise.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import canon, money
from .errors import EpisodeError, PolicyVisibleError

LOG = logging.getLogger("genesis_audit.loader")

TABLES = ("ledger", "invoices", "payments", "fx")
LEDGER_COLUMNS = (
    "row_id", "timestamp", "account", "debit_minor", "credit_minor",
    "currency", "entity_id", "invoice_id", "payment_id",
)  # fmt: skip
FX_COLUMNS = ("date", "source_currency", "target_currency", "rate")
INVOICE_KEYS = ("doc_id", "invoice_id", "entity_id", "issued_at", "due_at", "currency", "total_minor", "line_items")
PAYMENT_KEYS = ("doc_id", "payment_id", "timestamp", "currency", "amount_minor", "invoice_refs")
LINE_ITEM_KEYS = ("description", "quantity", "unit_price_minor", "amount_minor")
PUBLIC_FILES = ("manifest.json", "policy.json", "ledger.csv", "invoices.jsonl", "payments.jsonl", "fx.csv")

# The draft's budget and caps [S1]. An episode may not raise any of them: a manifest is data, and data must not
# be able to weaken the contract (a page of 2,000 rows, a budget of 100,000 steps).
DRAFT_LIMITS = {
    "max_steps": 100,
    "page_limit": 50,
    "max_findings": 30,
    "max_evidence_ids": 10,
    "max_explanation_chars": 1000,
}
MAX_ID_CHARS = 256
MAX_CURSOR_CHARS = 64
# C0 and C1 control characters and lone surrogates. Everything else is a legal id character.
_FORBIDDEN_ID_CHARS = re.compile("[\x00-\x1f\x7f-\x9f\ud800-\udfff]")
_NULLABLE_LEDGER = ("entity_id", "invoice_id", "payment_id")


def is_valid_id(value: object) -> bool:
    """An id is any non-empty string of at most 256 code points without control characters.

    The one gate for ids: the loader, the lookups and the truth file all use it.
    """
    return isinstance(value, str) and 0 < len(value) <= MAX_ID_CHARS and not _FORBIDDEN_ID_CHARS.search(value)


def fx_key(row: Mapping[str, Any]) -> str:
    """The id of an FX rate row: its natural key, 'date|source|target'."""
    return f"{row['date']}|{row['source_currency']}|{row['target_currency']}"


class Checks:
    """How hard validation is. Format checks always refuse; consistency checks refuse only when strict.

    A non-strict check that fails is written to the evaluator log (never to a policy) and kept in
    `warnings`, so a caller can report it.
    """

    def __init__(self, *, strict: bool) -> None:
        self.strict = strict
        self.warnings: list[str] = []

    def hard(self, condition: bool, message: str) -> None:
        if not condition:
            raise EpisodeError(message)

    def soft(self, condition: bool, message: str) -> None:
        if not condition:
            self.warn(message)

    def warn(self, message: str) -> None:
        """A consistency failure: refused when strict, logged and kept otherwise."""
        if self.strict:
            raise EpisodeError(message)
        LOG.warning("episode accepted despite: %s", message)
        self.warnings.append(message)


STRICT = Checks(strict=True)  # stateless while strict: a failure raises before anything is recorded


@dataclass(frozen=True)
class PublicEpisode:
    """The records a policy may reach through the tools. Treated as immutable."""

    manifest: Mapping[str, Any]
    policy: Mapping[str, Any]
    tables: Mapping[str, tuple[Mapping[str, Any], ...]]

    def record_id(self, table: str, record: Mapping[str, Any]) -> str:
        """The id used by get_record for this table."""
        if table == "ledger":
            return record["row_id"]
        if table == "invoices":
            return record["invoice_id"]
        if table == "payments":
            return record["payment_id"]
        return fx_key(record)

    def evidence_id(self, table: str, record: Mapping[str, Any]) -> str:
        """The id a finding cites as evidence: row_id, doc_id or the FX key."""
        if table in ("invoices", "payments"):
            return record["doc_id"]
        return self.record_id(table, record)

    def evidence_universe(self) -> frozenset[str]:
        """Every evidence id that exists in the public records."""
        return frozenset(self.evidence_id(table, record) for table in TABLES for record in self.tables[table])

    def accessible_ids(self) -> frozenset[str]:
        """Every id a tool returns a record or a document for: row_id, doc_id, invoice_id, payment_id, fx key.

        The one evidence universe: the env's end-of-episode scoring, judge_adapter.score_episode and
        truth.validate_truth all use it. A cited id outside it voids the finding (FP), never the submission.
        """
        by_record = (self.record_id(table, record) for table in TABLES for record in self.tables[table])
        return self.evidence_universe() | frozenset(by_record)

    def id_universe(self) -> frozenset[str]:
        """Every id a policy can learn from the tools: records, documents, business objects, entities."""
        ids = set(self.evidence_universe())
        for table in ("ledger", "invoices", "payments"):
            for record in self.tables[table]:
                ids.update(str(record[key]) for key in ("entity_id", "invoice_id", "payment_id") if record.get(key))
        return frozenset(ids)

    def page_limit(self) -> int:
        return int(self.manifest["limits"]["page_limit"])

    def list_page(self, table: object, cursor: object, limit: object) -> tuple[list[dict[str, Any]], str | None]:
        """Return one page in file order and the cursor of the next page, if any."""
        rows = self._table(table)
        if limit is None:
            limit = self.page_limit()
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= self.page_limit():
            raise PolicyVisibleError("bad_limit")
        offset = self._decode_cursor(str(table), cursor, len(rows))
        page = [_copy(record) for record in rows[offset : offset + limit]]
        end = offset + limit
        return page, (f"{table}:{end}" if end < len(rows) else None)

    def get_record(self, table: object, record_id: object) -> tuple[str, dict[str, Any]]:
        """Look one record up by its table id. Returns (table, record)."""
        rows = self._table(table)
        if not is_valid_id(record_id):
            raise PolicyVisibleError("unknown_id")
        for record in rows:
            if self.record_id(str(table), record) == record_id:
                return str(table), _copy(record)
        raise PolicyVisibleError("unknown_id")

    def get_document(self, doc_id: object) -> tuple[str, dict[str, Any]]:
        """Look a supporting document up by doc_id. Returns (table, record)."""
        if not is_valid_id(doc_id):
            raise PolicyVisibleError("unknown_id")
        for table in ("invoices", "payments"):
            for record in self.tables[table]:
                if record["doc_id"] == doc_id:
                    return table, _copy(record)
        raise PolicyVisibleError("unknown_id")

    def _table(self, table: object) -> tuple[Mapping[str, Any], ...]:
        if not isinstance(table, str) or table not in TABLES:
            raise PolicyVisibleError("unknown_table")
        return self.tables[table]

    @staticmethod
    def _decode_cursor(table: str, cursor: object, size: int) -> int:
        if cursor is None:
            return 0
        if not isinstance(cursor, str) or len(cursor) > MAX_CURSOR_CHARS:
            raise PolicyVisibleError("bad_cursor")
        name, _, offset = cursor.partition(":")
        if name != table or not offset.isascii() or not offset.isdigit() or len(offset) > 9:
            raise PolicyVisibleError("bad_cursor")
        if not 0 < int(offset) < size or offset != str(int(offset)):  # only the form the environment itself issues
            raise PolicyVisibleError("bad_cursor")
        return int(offset)


def _copy(record: Mapping[str, Any]) -> dict[str, Any]:
    """Hand out a fresh JSON-compatible copy so callers cannot mutate the store."""
    return json.loads(json.dumps(record))


# --------------------------------------------------------------------------- parsing


def canonical_object(value: object, keys: Sequence[str], where: str) -> dict[str, Any]:
    """`value` rebuilt with exactly `keys` in that order. Any order of the same keys is accepted."""
    if not isinstance(value, dict) or set(value) != set(keys):
        raise EpisodeError(f"{where} must have exactly the keys {', '.join(keys)} (in any order)")
    return {key: value[key] for key in keys}


def _content_lines(text: str) -> list[str]:
    """Lines of a text file; trailing empty lines (a final newline, an empty last line) are not content."""
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def parse_csv(text: str, columns: tuple[str, ...], what: str) -> list[dict[str, str]]:
    """Rows as dicts in canonical column order. The header may list the columns in any order."""
    rows = list(csv.reader(io.StringIO(text, newline="")))
    while rows and len(rows[-1]) <= 1 and not "".join(rows[-1]).strip():  # empty or blank last lines, as in JSONL
        rows.pop()
    if not rows or sorted(rows[0]) != sorted(columns):
        raise EpisodeError(f"{what}: header must be exactly {','.join(columns)} (in any order)")
    header = rows[0]
    parsed = []
    for number, row in enumerate(rows[1:], start=2):
        if len(row) != len(columns):
            raise EpisodeError(f"{what}: line {number} has {len(row)} fields, expected {len(columns)}")
        named = dict(zip(header, row, strict=True))
        parsed.append({column: named[column] for column in columns})
    return parsed


def parse_ledger(text: str) -> tuple[dict[str, Any], ...]:
    """ledger.csv -> records. An empty reference field is an explicit null."""
    records = []
    for raw in parse_csv(text, LEDGER_COLUMNS, "ledger.csv"):
        record: dict[str, Any] = dict(raw)
        for column in ("debit_minor", "credit_minor"):
            record[column] = _parse_minor(raw[column], f"ledger.csv {raw['row_id']} {column}")
        for column in _NULLABLE_LEDGER:
            record[column] = raw[column] or None
        records.append(record)
    return tuple(records)


def parse_fx(text: str) -> tuple[dict[str, Any], ...]:
    return tuple(dict(row) for row in parse_csv(text, FX_COLUMNS, "fx.csv"))


def parse_jsonl(text: str, keys: tuple[str, ...], what: str) -> tuple[dict[str, Any], ...]:
    records = []
    for number, line in enumerate(_content_lines(text), start=1):
        if not line.strip():
            raise EpisodeError(f"{what}: blank line {number}")
        try:
            record = canon.loads_strict(line)
        except ValueError as exc:
            raise EpisodeError(f"{what}: line {number} is not strict JSON ({exc})") from exc
        records.append(canonical_object(record, keys, f"{what}: line {number}"))
    return tuple(records)


def parse_invoices(text: str) -> tuple[dict[str, Any], ...]:
    """invoices.jsonl -> records, with each line item's keys in canonical order too."""
    invoices = []
    for invoice in parse_jsonl(text, INVOICE_KEYS, "invoices.jsonl"):
        items = invoice["line_items"]
        if isinstance(items, list):
            where = f"invoice {invoice['invoice_id']}: line item"
            items = [canonical_object(item, LINE_ITEM_KEYS, where) for item in items]
        invoices.append({**invoice, "line_items": items})
    return tuple(invoices)


def _parse_minor(value: str, where: str) -> int:
    if not value.isascii() or not value.isdigit() or len(value) > 15:
        raise EpisodeError(f"{where}: minor units must be a non-negative integer")
    return int(value)


_MANIFEST_KEYS = (
    "schema_version", "episode_id", "base_currency", "period_start", "period_end", "timezone",
    "counts", "currencies", "rounding", "amount_tolerance_minor", "issue_types", "limits",
)  # fmt: skip
_LIMIT_KEYS = ("max_steps", "page_limit", "max_findings", "max_evidence_ids", "max_explanation_chars")
_ROUNDING_KEYS = ("permitted", "default")
_COUNT_KEYS = ("ledger_rows", "documents", "fx_rates")


def canonical_manifest(manifest: object) -> object:
    """The manifest with its fixed-key objects in canonical order. Anything malformed is left for validation."""
    if not isinstance(manifest, dict) or set(manifest) != set(_MANIFEST_KEYS):
        return manifest
    nested = {"limits": _LIMIT_KEYS, "rounding": _ROUNDING_KEYS, "counts": _COUNT_KEYS}
    rebuilt: dict[str, Any] = {}
    for key in _MANIFEST_KEYS:
        value, order = manifest[key], nested.get(key)
        if order is not None and isinstance(value, dict) and set(value) == set(order):
            value = {name: value[name] for name in order}
        rebuilt[key] = value
    return rebuilt


def read_texts(directory: Path, names: Sequence[str]) -> dict[str, str]:
    """Read files as UTF-8; a byte-order mark at the start is tolerated."""
    try:
        return {name: (directory / name).read_text(encoding="utf-8-sig") for name in names}
    except (OSError, UnicodeDecodeError) as exc:
        raise EpisodeError(f"cannot read episode files: {exc}") from exc


def parse_public(texts: Mapping[str, str], checks: Checks = STRICT) -> PublicEpisode:
    """Parse and validate the six public files."""
    try:
        manifest = canonical_manifest(canon.loads_strict(texts["manifest.json"]))
        policy = canon.loads_strict(texts["policy.json"])
    except ValueError as exc:
        raise EpisodeError(f"manifest.json or policy.json is not strict JSON ({exc})") from exc
    if not isinstance(manifest, dict) or not isinstance(policy, dict):
        raise EpisodeError("manifest.json and policy.json must each hold an object")
    episode = PublicEpisode(
        manifest=manifest,
        policy=policy,
        tables={
            "ledger": parse_ledger(texts["ledger.csv"]),
            "invoices": parse_invoices(texts["invoices.jsonl"]),
            "payments": parse_jsonl(texts["payments.jsonl"], PAYMENT_KEYS, "payments.jsonl"),
            "fx": parse_fx(texts["fx.csv"]),
        },
    )
    validate_public(episode, checks)
    return episode


def load_public(directory: Path) -> PublicEpisode:
    """Load and strictly validate the public half of an episode: exactly the six public files."""
    try:
        extra = sorted(entry.name for entry in directory.iterdir() if entry.name not in PUBLIC_FILES)
    except OSError as exc:
        raise EpisodeError(f"cannot read public episode files: {exc}") from exc
    texts = read_texts(directory, PUBLIC_FILES)
    if extra:  # a stray answer key, for one, has no business in the public half
        raise EpisodeError(f"unexpected files in the public half of the episode: {extra}")
    return parse_public(texts)


def receipt_order_conflicts(payments: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    """(invoice_id, payment_id, payment_id) for every two receipts that share an invoice and an instant.

    Their order would be undefined, and any tie-break (file order, id order) would make truth depend
    on something a harmless perturbation changes. Grouped by invoice, so ties need not be adjacent.
    """
    seen: dict[tuple[str, datetime], str] = {}
    conflicts = []
    for payment in payments:
        moment = datetime.fromisoformat(payment["timestamp"])
        for invoice_id in payment["invoice_refs"]:
            earlier = seen.setdefault((invoice_id, moment), payment["payment_id"])
            if earlier != payment["payment_id"]:
                conflicts.append((invoice_id, *sorted((earlier, payment["payment_id"]))))
    return sorted(conflicts)


# ------------------------------------------------------------------------ validation


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EpisodeError(message)


def _timestamp(value: object, where: str) -> datetime:
    _require(isinstance(value, str), f"{where}: timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value)  # type: ignore[arg-type]
    except ValueError as exc:
        raise EpisodeError(f"{where}: not an ISO-8601 timestamp") from exc
    _require(parsed.tzinfo is not None, f"{where}: timestamp needs a UTC offset")
    return parsed


def is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    """The manifest is the format envelope of an episode: every check here refuses."""
    _require(isinstance(manifest, dict), "manifest must be an object")
    _require(set(manifest) == set(_MANIFEST_KEYS), f"manifest keys must be exactly: {', '.join(_MANIFEST_KEYS)}")
    _require(is_valid_id(manifest["episode_id"]), "manifest.episode_id must be an id (no control characters)")
    currencies = manifest["currencies"]
    _require(isinstance(currencies, dict) and bool(currencies), "manifest.currencies must be a non-empty object")
    for code, spec in currencies.items():
        ok = isinstance(spec, dict) and set(spec) == {"exponent"} and is_int(spec["exponent"])
        _require(ok and 0 <= spec["exponent"] <= 6, f"manifest.currencies[{code}] needs an exponent in 0..6")
    _require(manifest["base_currency"] in currencies, "manifest.base_currency must be a declared currency")
    start = _timestamp(manifest["period_start"], "manifest.period_start")
    end = _timestamp(manifest["period_end"], "manifest.period_end")
    _require(start < end, "manifest period must start before it ends")
    tolerance = manifest["amount_tolerance_minor"]
    _require(isinstance(tolerance, dict) and set(tolerance) == set(currencies), "tolerance must cover each currency")
    _require(all(is_int(v) and v >= 0 for v in tolerance.values()), "tolerances must be non-negative integers")
    rounding = manifest["rounding"]
    _require(isinstance(rounding, dict) and set(rounding) == set(_ROUNDING_KEYS), "manifest.rounding shape")
    _require(isinstance(rounding["permitted"], list), "manifest.rounding.permitted must be a list")
    _require(set(rounding["permitted"]) <= set(money.ROUNDING_MODES), "manifest.rounding lists an unknown mode")
    _require(rounding["default"] in rounding["permitted"], "manifest.rounding.default must be permitted")
    types = manifest["issue_types"]
    _require(isinstance(types, list) and all(isinstance(t, str) for t in types), "manifest.issue_types must be a list")
    limits = manifest["limits"]
    _require(isinstance(limits, dict) and set(limits) == set(_LIMIT_KEYS), "manifest.limits keys are fixed")
    _require(all(is_int(v) and v >= 1 for v in limits.values()), "manifest.limits must be positive integers")
    _require(all(limits[name] <= ceiling for name, ceiling in DRAFT_LIMITS.items()),
             f"manifest.limits may not exceed the draft's budget and caps: {DRAFT_LIMITS}")  # fmt: skip


def _validate_ids(episode: PublicEpisode) -> None:
    """Ids are well formed and unique within their own space; equal strings in different spaces are fine."""
    ledger, invoices, payments, fx = (episode.tables[name] for name in TABLES)
    spaces = {
        "ledger row_id": [record["row_id"] for record in ledger],
        "doc_id": [record["doc_id"] for record in (*invoices, *payments)],
        "invoice_id": [record["invoice_id"] for record in invoices],
        "payment_id": [record["payment_id"] for record in payments],
        "fx key": [fx_key(row) for row in fx],
    }
    entities = [record["entity_id"] for record in (*ledger, *invoices) if record["entity_id"] is not None]
    references = [record[key] for record in ledger for key in ("invoice_id", "payment_id") if record[key] is not None]
    refs = [payment["invoice_refs"] for payment in payments]
    _require(all(isinstance(value, list) for value in refs), "payment invoice_refs must be lists of ids")
    every = [
        *(value for ids in spaces.values() for value in ids),
        *entities,
        *references,
        *(r for v in refs for r in v),
    ]
    _require(all(is_valid_id(value) for value in every), "every id must be a non-empty string of at most "
             f"{MAX_ID_CHARS} characters without control characters")  # fmt: skip
    for space, ids in spaces.items():
        _require(len(set(ids)) == len(ids), f"ids must be unique within each id space: {space} repeats")


def _validate_ledger(episode: PublicEpisode, checks: Checks) -> None:
    currencies = episode.manifest["currencies"]
    ledger = episode.tables["ledger"]
    invoice_ids = {record["invoice_id"] for record in episode.tables["invoices"]}
    payment_ids = {record["payment_id"] for record in episode.tables["payments"]}
    for record in ledger:
        where = f"ledger row {record['row_id']}"
        _timestamp(record["timestamp"], where)
        checks.soft(record["currency"] in currencies, f"{where}: undeclared currency")
        checks.soft(
            (record["debit_minor"] > 0) != (record["credit_minor"] > 0), f"{where}: exactly one side is non-zero"
        )
        checks.soft(bool(record["account"]), f"{where}: account is required")
        checks.soft(record["invoice_id"] is None or record["invoice_id"] in invoice_ids, f"{where}: unknown invoice_id")
        checks.soft(record["payment_id"] is None or record["payment_id"] in payment_ids, f"{where}: unknown payment_id")
    for code in currencies:  # double entry: the one identity every valid episode satisfies, with or without errors
        debit = sum(r["debit_minor"] for r in ledger if r["currency"] == code)
        credit = sum(r["credit_minor"] for r in ledger if r["currency"] == code)
        checks.soft(debit == credit, f"ledger does not balance in {code}: debits {debit}, credits {credit}")


def _validate_invoices(episode: PublicEpisode, checks: Checks) -> None:
    currencies = episode.manifest["currencies"]
    for record in episode.tables["invoices"]:
        where = f"invoice {record['invoice_id']}"
        _timestamp(record["issued_at"], where)
        _timestamp(record["due_at"], where)
        _require(isinstance(record["currency"], str), f"{where}: currency must be a string")
        checks.soft(record["currency"] in currencies, f"{where}: undeclared currency")
        _require(is_int(record["total_minor"]), f"{where}: total_minor must be an integer")
        checks.soft(record["total_minor"] > 0, f"{where}: total_minor must be positive")
        items = record["line_items"]
        _require(isinstance(items, list), f"{where}: line_items must be a list")
        checks.soft(bool(items), f"{where}: line_items must be a non-empty list")
        for item in items:
            _require(isinstance(item, dict) and tuple(item) == LINE_ITEM_KEYS, f"{where}: line item keys")
            _require(all(is_int(item[key]) for key in LINE_ITEM_KEYS[1:]), f"{where}: line item numbers")
            checks.soft(item["quantity"] * item["unit_price_minor"] == item["amount_minor"], f"{where}: line item math")
        checks.soft(sum(item["amount_minor"] for item in items) == record["total_minor"], f"{where}: total != lines")


def _validate_payments(episode: PublicEpisode, checks: Checks) -> None:
    currencies = episode.manifest["currencies"]
    invoice_ids = {record["invoice_id"] for record in episode.tables["invoices"]}
    payments = episode.tables["payments"]
    for record in payments:
        where = f"payment {record['payment_id']}"
        _timestamp(record["timestamp"], where)
        _require(isinstance(record["currency"], str), f"{where}: currency must be a string")
        checks.soft(record["currency"] in currencies, f"{where}: undeclared currency")
        _require(is_int(record["amount_minor"]), f"{where}: amount_minor must be an integer")
        checks.soft(record["amount_minor"] > 0, f"{where}: amount_minor must be positive")
        refs = record["invoice_refs"]
        checks.soft(len(set(refs)) == len(refs), f"{where}: invoice_refs must be a list without repeats")
        checks.soft(all(ref in invoice_ids for ref in refs), f"{where}: invoice_refs must name known invoices")
    conflicts = receipt_order_conflicts(payments)
    checks.soft(not conflicts, f"receipts for one invoice share a timestamp, so their order is undefined: {conflicts}")


def _validate_fx(episode: PublicEpisode, checks: Checks) -> None:
    currencies = episode.manifest["currencies"]
    for row in episode.tables["fx"]:
        where = f"fx row {fx_key(row)}"
        try:
            date.fromisoformat(row["date"])
            money.parse_rate(row["rate"])
        except ValueError as exc:
            raise EpisodeError(f"{where}: {exc}") from exc
        known = row["source_currency"] in currencies and row["target_currency"] in currencies
        checks.soft(known, f"{where}: currency")


def validate_public(episode: PublicEpisode, checks: Checks = STRICT) -> None:
    """Reject an episode whose public files are malformed; consistency failures follow `checks`.

    Evaluator-side detail is fine in the messages: they never reach a policy.
    """
    validate_manifest(episode.manifest)
    _validate_ids(episode)
    _validate_ledger(episode, checks)
    _validate_invoices(episode, checks)
    _validate_payments(episode, checks)
    _validate_fx(episode, checks)
    tables = episode.tables
    actual = {
        "ledger_rows": len(tables["ledger"]),
        "documents": len(tables["invoices"]) + len(tables["payments"]),
        "fx_rates": len(tables["fx"]),
    }
    counts = episode.manifest["counts"]
    checks.soft(counts == actual, f"manifest.counts {counts} does not match the records {actual}")


# --------------------------------------------------------------------- serialization


def render_public(episode: PublicEpisode) -> dict[str, str]:
    """Deterministic file contents for the public half of an episode."""

    def render_csv(columns: tuple[str, ...], rows: tuple[Mapping[str, Any], ...]) -> str:
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow(["" if row[column] is None else row[column] for column in columns])
        return buffer.getvalue()

    def render_jsonl(keys: tuple[str, ...], rows: tuple[Mapping[str, Any], ...]) -> str:
        lines = [json.dumps({key: row[key] for key in keys}, ensure_ascii=True, separators=(",", ":")) for row in rows]
        return "".join(line + "\n" for line in lines)

    return {
        "manifest.json": json.dumps(episode.manifest, indent=2, ensure_ascii=True) + "\n",
        "policy.json": json.dumps(episode.policy, indent=2, ensure_ascii=True) + "\n",
        "ledger.csv": render_csv(LEDGER_COLUMNS, episode.tables["ledger"]),
        "invoices.jsonl": render_jsonl(INVOICE_KEYS, episode.tables["invoices"]),
        "payments.jsonl": render_jsonl(PAYMENT_KEYS, episode.tables["payments"]),
        "fx.csv": render_csv(FX_COLUMNS, episode.tables["fx"]),
    }
