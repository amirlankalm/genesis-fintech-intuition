from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from genesis_audit import paths
from genesis_audit.errors import EpisodeError, PolicyVisibleError
from genesis_audit.store import PublicEpisode, load_public

PUBLIC = paths.PUBLIC_ROOT / "teaching_b"


@pytest.fixture(scope="module")
def episode() -> PublicEpisode:
    return load_public(PUBLIC)


def code(call, *args) -> str:
    with pytest.raises(PolicyVisibleError) as caught:
        call(*args)
    return caught.value.code


def test_loads_the_teaching_episode(episode: PublicEpisode) -> None:
    assert {name: len(rows) for name, rows in episode.tables.items()} == {
        "ledger": 12, "invoices": 2, "payments": 3, "fx": 3,
    }  # fmt: skip
    assert len(episode.evidence_universe()) == 12 + 5 + 3
    assert len(episode.id_universe()) == 12 + 5 + 3 + 2 + 3 + 2  # plus invoices, payments, entities
    assert episode.tables["ledger"][4]["invoice_id"] is None  # an empty CSV field is an explicit null


def test_paging_is_stable_and_complete(episode: PublicEpisode) -> None:
    pages, cursor = [], None
    while True:
        page, next_cursor = episode.list_page("ledger", cursor, 5)
        assert episode.list_page("ledger", cursor, 5) == (page, next_cursor)  # same cursor, same page
        pages.append(page)
        if next_cursor is None:
            break
        cursor = next_cursor
    assert [len(page) for page in pages] == [5, 5, 2]
    assert [row for page in pages for row in page] == [dict(row) for row in episode.tables["ledger"]]
    assert episode.list_page("ledger", None, None)[1] is None  # default limit is the page limit


@pytest.mark.parametrize("limit", [0, 51, -1, "5", True, 2.0, [5]])
def test_bad_limits_are_errors_not_clamps(episode: PublicEpisode, limit: object) -> None:
    assert code(episode.list_page, "ledger", None, limit) == "bad_limit"


@pytest.mark.parametrize("cursor", ["ledger:0", "ledger:12", "ledger:999", "invoices:1", "ledger:-1", "ledger:1x",
                                    "ledger:", "ledger", 5, "x" * 100, "ledger:٣"])  # fmt: skip
def test_bad_cursors(episode: PublicEpisode, cursor: object) -> None:
    assert code(episode.list_page, "ledger", cursor, 5) == "bad_cursor"


def test_lookups(episode: PublicEpisode) -> None:
    assert episode.get_record("ledger", "L11")[1]["credit_minor"] == 150_000
    assert episode.get_record("invoices", "I7")[1]["doc_id"] == "D31"
    assert episode.get_record("payments", "P9")[1]["amount_minor"] == 260_000
    assert episode.get_record("fx", "2026-10-14|USD|KZT")[1]["rate"] == "512.40"
    assert episode.get_document("D44") == ("payments", episode.get_record("payments", "P9")[1])
    assert code(episode.get_record, "nope", "L11") == "unknown_table"
    assert code(episode.list_page, ["ledger"], None, 5) == "unknown_table"
    for bad in ("L99", "", 7, None, "L11 ", "x" * 65, "I7"):
        assert code(episode.get_record, "ledger", bad) == "unknown_id"
    for bad in ("L11", "I7", 3, "D99"):
        assert code(episode.get_document, bad) == "unknown_id"


def test_returned_records_are_copies(episode: PublicEpisode) -> None:
    _, record = episode.get_record("invoices", "I7")
    record["line_items"][0]["amount_minor"] = 1
    record["total_minor"] = 1
    assert episode.get_record("invoices", "I7")[1]["total_minor"] == 250_000
    assert episode.get_record("invoices", "I7")[1]["line_items"][0]["amount_minor"] == 250_000


MUTATIONS = [
    ("ledger.csv", "row_id,timestamp", "id,timestamp", "header"),
    ("ledger.csv", "L08,", "L21,", "unique"),
    ("ledger.csv", "revenue,0,250000,KZT,E4", "revenue,5,250000,KZT,E4", "exactly one side"),
    ("ledger.csv", "revenue,0,250000,KZT,E4", "revenue,0,0,KZT,E4", "exactly one side"),
    ("ledger.csv", "revenue,0,250000,KZT,E4", "revenue,0,-5,KZT,E4", "non-negative integer"),
    ("ledger.csv", "KZT,E4,I7,\n", "KZT,E4,I9,\n", "unknown invoice_id"),
    ("ledger.csv", "KZT,E4,,P9", "KZT,E4,,P1", "unknown payment_id"),
    ("ledger.csv", "2026-10-05T10:00:00+05:00,revenue", "2026-10-05T10:00:00,revenue", "UTC offset"),
    ("ledger.csv", "revenue,0,250000,KZT,E4", "revenue,0,250000,EUR,E4", "undeclared currency"),
    ("ledger.csv", "L06,2026-10-23T16:45:00+05:00,unapplied_receipts,0,20000,KZT,E8,,P5\n", "", "does not balance"),
    ("ledger.csv", "L06,", "L06,extra,", "fields"),
    ("invoices.jsonl", '"total_minor":250000', '"total_minor":250001', "total != lines"),
    ("invoices.jsonl", '"quantity":5', '"quantity":4', "line item math"),
    ("invoices.jsonl", '"doc_id":"D31",', "", "exactly the keys"),
    ("invoices.jsonl", '"total_minor":250000', '"total_minor":NaN', "strict JSON"),
    ("payments.jsonl", '["I7"]', '["I9"]', "known invoices"),
    ("payments.jsonl", '"amount_minor":260000', '"amount_minor":0', "amount_minor"),
    ("fx.csv", "512.40", "5e2", "rate"),
    (
        "payments.jsonl",
        '"timestamp":"2026-10-23T16:45:00+05:00"',
        '"timestamp":"2026-10-16T14:00:00+05:00"',
        "order is undefined",
    ),
    ("fx.csv", "2026-10-14", "2026-13-14", "month"),
    ("manifest.json", '"base_currency": "KZT"', '"base_currency": "EUR"', "declared currency"),
    ("manifest.json", '"max_steps": 100', '"max_steps": 0', "positive integers"),
    ("manifest.json", '"ledger_rows": 12', '"ledger_rows": 13', "counts"),
    ("ledger.csv", "revenue,0,250000,KZT,E4", "revenue,0,250001,KZT,E4", "does not balance"),
    ("manifest.json", '"episode_id": "ep-4c1f09"', '"episode_id": "ep\\u00014c1f09"', "control characters"),
    ("manifest.json", '"schema_version"', '"schema"', "manifest keys"),
    ("policy.json", "{", "{{", "strict JSON"),
]


@pytest.mark.parametrize(("filename", "old", "new", "message"), MUTATIONS)
def test_inconsistent_public_files_are_rejected(
    tmp_path: Path, filename: str, old: str, new: str, message: str
) -> None:
    target = tmp_path / "episode"
    shutil.copytree(PUBLIC, target)
    text = (target / filename).read_text(encoding="utf-8")
    assert old in text
    (target / filename).write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(EpisodeError, match=message):
        load_public(target)


def test_missing_file_is_an_episode_error(tmp_path: Path) -> None:
    with pytest.raises(EpisodeError, match="cannot read"):
        load_public(tmp_path)
