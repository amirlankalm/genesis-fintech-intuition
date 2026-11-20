"""The jury's loading path: one flat episode directory, possibly transformed by the jury.

The transformer below is the jury's, not ours: it uses only the standard library and the file
formats as documented, never repository code. It shuffles the data lines of ledger.csv, fx.csv,
invoices.jsonl and payments.jsonl, renames every id space with its own bijection to another id
shape, rewrites truth (affected_ids, acceptable evidence sets) and provenance values, reorders JSON
keys, and never touches fx keys. Official references: "Как подаются парные проверки", Block 4
(P01-P20), and the Block 1 adapter interface.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import random
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from genesis_audit import paths
from genesis_audit.env import AuditEnv
from genesis_audit.episodes import DirectorySource, LoadedEpisode, load_episode_dir
from genesis_audit.errors import EpisodeError

PUBLIC_NAMES = ("manifest.json", "policy.json", "ledger.csv", "invoices.jsonl", "payments.jsonl", "fx.csv")
# Shipped episodes: two interaction fixtures, a clean one, a mixed dev episode, the 12-issue one, a train one.
EPISODES = ("fixture_x_fx_allocation", "fixture_x_duplicate_cutoff", "fixture_clean", "dev_04", "dev_09", "train_01")
SPACES = ("row_id", "doc_id", "invoice_id", "payment_id", "entity_id")


# ----------------------------------------------------------------------------- the jury's transformer


def _shape_q(space: str, number: int) -> str:
    """One shape for every space, independent counters: equal strings across spaces are expected."""
    return f"Q-{number:06d}"


def _shape_hex(space: str, number: int) -> str:
    return f"x{SPACES.index(space)}{number:03x}"


def _shape_wide(space: str, number: int) -> str:
    """Spaces, slashes, Cyrillic, commas and quotes, and a long tail: any string without control characters."""
    return f'ид {space}/{number}, "q" ' + "z" * 150


SHAPES: dict[str, Callable[[str, int], str]] = {"q_per_space": _shape_q, "hex": _shape_hex, "wide": _shape_wide}


def _read_csv(text: str) -> tuple[list[str], list[dict[str, str]]]:
    rows = list(csv.reader(io.StringIO(text, newline="")))
    return rows[0], [dict(zip(rows[0], row, strict=True)) for row in rows[1:] if row]


def _write_csv(header: list[str], rows: list[dict[str, str]], quote_all: bool) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL if quote_all else csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows([row[column] for column in header] for row in rows)
    return buffer.getvalue()


def _reorder(value: Any, rng: random.Random) -> Any:
    """The same JSON value with every object's keys in a random order (list order is kept)."""
    if isinstance(value, dict):
        keys = list(value)
        rng.shuffle(keys)
        return {key: _reorder(value[key], rng) for key in keys}
    if isinstance(value, list):
        return [_reorder(item, rng) for item in value]
    return value


def _rename_values(value: Any, mapping: dict[str, str]) -> Any:
    """Replace every string equal to an old id, anywhere (the value-based provenance rewrite)."""
    if isinstance(value, dict):
        return {key: _rename_values(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [_rename_values(item, mapping) for item in value]
    return mapping.get(value, value) if isinstance(value, str) else value


def _source_texts(name: str) -> dict[str, str]:
    texts = {file: (paths.PUBLIC_ROOT / name / file).read_text(encoding="utf-8") for file in PUBLIC_NAMES}
    for file in ("truth.json", "provenance.json"):
        texts[file] = (paths.PRIVATE_ROOT / name / file).read_text(encoding="utf-8")
    return texts


def _id_spaces(texts: dict[str, str]) -> dict[str, list[str]]:
    _, ledger = _read_csv(texts["ledger.csv"])
    invoices = [json.loads(line) for line in texts["invoices.jsonl"].splitlines()]
    payments = [json.loads(line) for line in texts["payments.jsonl"].splitlines()]
    entities = {row["entity_id"] for row in ledger if row["entity_id"]} | {i["entity_id"] for i in invoices}
    return {
        "row_id": [row["row_id"] for row in ledger],
        "doc_id": [record["doc_id"] for record in (*invoices, *payments)],
        "invoice_id": [record["invoice_id"] for record in invoices],
        "payment_id": [record["payment_id"] for record in payments],
        "entity_id": sorted(entities),
    }


def _bijections(spaces: dict[str, list[str]], shape: Callable[[str, int], str], rng: random.Random) -> dict[str, str]:
    """One bijection per id space, numbered in a shuffled order. Shipped ids are globally unique,
    so the union of the per-space maps is a function old id -> new id."""
    mapping: dict[str, str] = {}
    for space, ids in spaces.items():
        numbers = list(range(1, len(ids) + 1))
        rng.shuffle(numbers)
        renamed = {old: shape(space, number) for old, number in zip(ids, numbers, strict=True)}
        assert len(set(renamed.values())) == len(ids)  # a bijection within the space
        assert not set(renamed) & set(mapping)  # the shipped spaces are disjoint
        mapping.update(renamed)
    return mapping


def jury_transform(name: str, target: Path, *, shape: str, seed: int) -> dict[str, str]:
    """Write a permuted, renamed, key-reordered flat copy of shipped episode `name`. Returns old -> new ids."""
    rng = random.Random(seed)
    texts = _source_texts(name)
    mapping = _bijections(_id_spaces(texts), SHAPES[shape], rng)

    def ren(value: str) -> str:
        return mapping[value] if value else value

    def jsonl(rows: list[dict[str, Any]]) -> str:
        rng.shuffle(rows)
        return "".join(json.dumps(_reorder(row, rng), ensure_ascii=False) + "\n" for row in rows) + "\n"

    header, ledger = _read_csv(texts["ledger.csv"])
    ledger = [
        {**row, **{c: ren(row[c]) for c in ("row_id", "entity_id", "invoice_id", "payment_id")}} for row in ledger
    ]
    rng.shuffle(ledger)
    fx_header, fx = _read_csv(texts["fx.csv"])
    rng.shuffle(fx)  # fx rows keep their natural keys: date|source|target is not a surrogate id
    invoices = [json.loads(line) for line in texts["invoices.jsonl"].splitlines()]
    invoices = [{**i, "doc_id": ren(i["doc_id"]), "invoice_id": ren(i["invoice_id"]),
                 "entity_id": ren(i["entity_id"])} for i in invoices]  # fmt: skip
    payments = [json.loads(line) for line in texts["payments.jsonl"].splitlines()]
    payments = [{**p, "doc_id": ren(p["doc_id"]), "payment_id": ren(p["payment_id"]),
                 "invoice_refs": [ren(ref) for ref in p["invoice_refs"]]} for p in payments]  # fmt: skip
    truth = json.loads(texts["truth.json"])
    issues = [{**issue, "affected_ids": [ren(i) for i in issue["affected_ids"]],
               "acceptable_evidence_sets": [[mapping.get(i, i) for i in ids] for ids in issue["acceptable_evidence_sets"]]}
              for issue in truth["issues"]]  # fmt: skip
    rng.shuffle(issues)
    written = {
        "ledger.csv": _write_csv(header, ledger, quote_all=shape == "hex"),
        "fx.csv": _write_csv(fx_header, fx, quote_all=False),
        "invoices.jsonl": jsonl(invoices),
        "payments.jsonl": jsonl(payments),
        "manifest.json": json.dumps(_reorder(json.loads(texts["manifest.json"]), rng), ensure_ascii=False),
        "policy.json": json.dumps(json.loads(texts["policy.json"]), sort_keys=True, indent=1),
        "truth.json": json.dumps(_reorder({"issues": issues}, rng), ensure_ascii=False),
        "provenance.json": json.dumps(_reorder(_rename_values(json.loads(texts["provenance.json"]), mapping), rng)),
    }
    target.mkdir(parents=True)
    for file, text in written.items():
        (target / file).write_text(("\ufeff" if file == "ledger.csv" else "") + text, encoding="utf-8")
    (target / "mapping.json").write_text(json.dumps(mapping), encoding="utf-8")  # the jury's own notes
    return mapping


def flat_copy(name: str, target: Path) -> Path:
    """generate_episode's layout: the six public files, truth.json and provenance.json in one directory."""
    target.mkdir(parents=True)
    for file in PUBLIC_NAMES:
        shutil.copy(paths.PUBLIC_ROOT / name / file, target / file)
    for file in ("truth.json", "provenance.json"):
        shutil.copy(paths.PRIVATE_ROOT / name / file, target / file)
    return target


# ----------------------------------------------------------------------------- the jury's oracle


def jury_oracle(name: str, mapping: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Findings from the original truth.json alone, renamed through the bijection, and the fetch actions
    that read every cited evidence id once (also renamed). Built without repository code."""
    texts = _source_texts(name)
    spaces = _id_spaces(texts)
    rows, docs = set(spaces["row_id"]), set(spaces["doc_id"])
    findings, evidence = [], set()
    for issue in sorted(json.loads(texts["truth.json"])["issues"], key=lambda item: item["issue_id"]):
        cited = min(issue["acceptable_evidence_sets"], key=lambda ids: (len(ids), sorted(ids)))
        evidence.update(cited)
        findings.append({
            "type": issue["type"], "affected_ids": [mapping.get(i, i) for i in issue["affected_ids"]],
            "claimed_amount_minor": issue["expected_amount_minor"], "currency": issue["currency"],
            "evidence_ids": [mapping.get(i, i) for i in cited], "explanation": "jury oracle",
        })  # fmt: skip

    def fetch(old: str) -> dict[str, Any]:
        new = mapping.get(old, old)
        if old in docs:
            return {"action": "get_document", "args": {"doc_id": new}}
        return {"action": "get_record", "args": {"table": "ledger" if old in rows else "fx", "id": new}}

    return findings, [fetch(old) for old in sorted(evidence)]


def play(loaded: LoadedEpisode, findings: list[dict[str, Any]], fetches: list[dict[str, Any]], mode: str) -> dict:
    env = AuditEnv.from_episode(loaded)
    env.reset(config={"episode": "episode", "mode": mode})
    for action in fetches:
        observation, reward, *_ = env.step(action)
        assert "record" in observation, observation  # every cited evidence id is reachable on the copy too
        assert reward == 0.0
    document = {"episode_id": loaded.public.manifest["episode_id"], "findings": findings}
    _, reward, terminated, truncated, info = env.step({"action": "submit", "args": {"findings": document}})
    report = env.evaluator_report()
    assert (terminated, truncated, report["termination_cause"]) == (True, False, "submitted")
    if mode == "eval":
        assert (reward, info) == (0.0, {})
    return {
        "counts": report["counts"],
        "score": {key: report["score"][key] for key in ("tp", "fp", "fn", "precision", "recall", "f1", "reward")},
        "inspection_steps": report["inspection_steps"],
    }


# ----------------------------------------------------------------------------- tests


@pytest.mark.parametrize("name", EPISODES)
@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_p11_p20_permuted_and_renamed_copies_load_and_score_identically(tmp_path: Path, name: str, shape: str) -> None:
    """P01-P20 + PAIR-transport: every jury variant loads with strict=False, and the oracle's findings renamed
    through the bijection score the same TP/FP/FN/P/R/F1/reward at the same inspection_steps."""
    original = load_episode_dir(flat_copy(name, tmp_path / "original"), strict=False)
    mapping = jury_transform(name, tmp_path / "copy", shape=shape, seed=sum(map(ord, name + shape)))
    copy = load_episode_dir(tmp_path / "copy", strict=False)
    assert len(copy.truth) == len(original.truth)
    assert {t: len(rows) for t, rows in copy.public.tables.items()} == {
        t: len(rows) for t, rows in original.public.tables.items()
    }
    identity = {old: old for old in mapping}
    for mode in ("train", "eval"):
        before = play(original, *jury_oracle(name, identity), mode=mode)
        after = play(copy, *jury_oracle(name, mapping), mode=mode)
        assert after == before
        assert before["counts"] == {"tp": len(original.truth), "fp": 0, "fn": 0}


def _without(finding: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    return {**finding, key: value}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_p06_p20_broken_evidence_and_pre_rename_ids_do_not_score_on_either_side(tmp_path: Path, shape: str) -> None:
    """Block 4 pass condition 4: an unchanged reward with a broken evidence set is not a pass. Dropping one cited
    evidence id voids the finding on the original and on the copy alike, and on the copy the pre-rename ids name
    nothing, so a finding written with them is unmatched there."""
    name = "fixture_x_duplicate_cutoff"
    original = load_episode_dir(flat_copy(name, tmp_path / "original"), strict=False)
    mapping = jury_transform(name, tmp_path / "copy", shape=shape, seed=5)
    copy = load_episode_dir(tmp_path / "copy", strict=False)
    findings, fetches = jury_oracle(name, {old: old for old in mapping})
    renamed, renamed_fetches = jury_oracle(name, mapping)
    issues = len(original.truth)
    assert issues >= 2
    broken = [_without(findings[0], "evidence_ids", findings[0]["evidence_ids"][1:]), *findings[1:]]
    broken_renamed = [_without(renamed[0], "evidence_ids", renamed[0]["evidence_ids"][1:]), *renamed[1:]]
    for mode in ("train", "eval"):
        before = play(original, broken, fetches, mode=mode)
        assert before == play(copy, broken_renamed, renamed_fetches, mode=mode)
        assert before["counts"] == {"tp": issues - 1, "fp": 1, "fn": 1}
    stale = [findings[0], *renamed[1:]]  # the first finding still uses the ids of the original
    assert play(copy, stale, renamed_fetches, mode="train")["counts"] == {"tp": issues - 1, "fp": 1, "fn": 1}


def test_c05_c06_paging_a_shuffled_copy_follows_its_file_order_and_is_stable(tmp_path: Path) -> None:
    """Row order is whatever order the file has: limit=50 pages walk the copy's ledger.csv exactly, with no gap
    and no repeat (C05), and the same cursor returns the same page twice (C06)."""
    jury_transform("dev_04", tmp_path / "copy", shape="wide", seed=11)
    with (tmp_path / "copy" / "ledger.csv").open(encoding="utf-8-sig", newline="") as handle:
        file_order = [row["row_id"] for row in csv.DictReader(handle)]
    env = AuditEnv.from_episode(load_episode_dir(tmp_path / "copy", strict=False))
    env.reset(config={"episode": "episode", "mode": "eval"})
    seen: list[str] = []
    cursors: list[str | None] = [None]
    while True:
        observation, *_ = env.step({"action": "list_records", "args": {"table": "ledger", "cursor": cursors[-1],
                                                                       "limit": 50}})  # fmt: skip
        assert len(observation["records"]) <= 50
        seen += [record["row_id"] for record in observation["records"]]
        if observation["next_cursor"] is None:
            break
        cursors.append(observation["next_cursor"])
    assert len(cursors) >= 3 and seen == file_order
    twice = [env.step({"action": "list_records", "args": {"table": "ledger", "cursor": cursors[1], "limit": 50}})
             for _ in range(2)]  # fmt: skip
    assert twice[0][0]["records"] == twice[1][0]["records"]
    assert [r["row_id"] for r in twice[0][0]["records"]] == file_order[50:100]


@pytest.mark.parametrize("name", EPISODES)
def test_p11_p20_strict_mode_also_takes_globally_distinct_renamings(tmp_path: Path, name: str) -> None:
    """With ids distinct across spaces (the hex shape), even strict=True re-derives the renamed truth."""
    jury_transform(name, tmp_path / "copy", shape="hex", seed=7)
    loaded = load_episode_dir(tmp_path / "copy", strict=True)
    assert loaded.warnings == ()


def test_trf_cross_space_collision_loads_without_refusal(tmp_path: Path) -> None:
    """TRF-cross-space-collision: uniqueness is per id space, so equal strings in different spaces load."""
    mapping = jury_transform("dev_04", tmp_path / "copy", shape="q_per_space", seed=3)
    assert len(set(mapping.values())) < len(mapping)  # the copy really reuses strings across spaces
    loaded = load_episode_dir(tmp_path / "copy", strict=False)
    public = loaded.public
    row = public.tables["ledger"][0]
    assert public.get_record("ledger", row["row_id"])[1] == dict(row)


def test_trf_flat_dir_with_extra_files_loads_and_names_them(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """TRF-flat-dir + TRF-extra-files: one directory with all eight files plus the jury's own files."""
    directory = flat_copy("fixture_duplicate", tmp_path / "C-fixture.v1")  # any directory name
    (directory / "mapping.json").write_text("{}", encoding="utf-8")
    (directory / "ANSWER_KEY.md").write_text("notes", encoding="utf-8")
    (directory / "nested").mkdir()
    with caplog.at_level(logging.INFO, logger="genesis_audit.loader"):
        for strict in (True, False):
            loaded = load_episode_dir(directory, strict=strict)
            assert loaded.warnings == () and loaded.provenance is not None
    assert "mapping.json" in caplog.text and "ANSWER_KEY.md" in caplog.text and "nested" in caplog.text
    reference = DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT).load("fixture_duplicate")
    assert (loaded.public, loaded.truth) == (reference.public, reference.truth)


def test_trf_flat_dir_without_provenance_loads(tmp_path: Path) -> None:
    directory = flat_copy("fixture_clean", tmp_path / "ep")
    (directory / "provenance.json").unlink()
    assert load_episode_dir(directory, strict=True).provenance is None
    (directory / "truth.json").unlink()
    with pytest.raises(EpisodeError, match="cannot load truth"):
        load_episode_dir(directory, strict=False)


def test_trf_json_key_order_and_writer_effects_are_normalised(tmp_path: Path) -> None:
    """TRF-json-key-order: sorted keys, a BOM, CRLF and an empty last line load to the same observation."""
    reference = load_episode_dir(flat_copy("dev_04", tmp_path / "a"), strict=True)
    directory = flat_copy("dev_04", tmp_path / "b")
    for file in ("manifest.json", "truth.json", "provenance.json", "policy.json"):
        value = json.loads((directory / file).read_text(encoding="utf-8"))
        (directory / file).write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    for file in ("invoices.jsonl", "payments.jsonl"):
        lines = (directory / file).read_text(encoding="utf-8").splitlines()
        text = "".join(json.dumps(json.loads(line), sort_keys=True) + "\r\n" for line in lines) + "\r\n"
        (directory / file).write_text("\ufeff" + text, encoding="utf-8")
    loaded = load_episode_dir(directory, strict=True)
    assert loaded.public == reference.public and loaded.truth == reference.truth
    manifest, canonical = loaded.public.manifest, reference.public.manifest
    for key in (None, "limits", "rounding", "counts"):  # fixed-key objects come back in canonical order
        assert list(manifest[key] if key else manifest) == list(canonical[key] if key else canonical)
    assert json.dumps(loaded.public.policy) == json.dumps(reference.public.policy)
    assert json.dumps(loaded.public.tables["invoices"]) == json.dumps(reference.public.tables["invoices"])


@pytest.mark.parametrize("name", sorted(p.name for p in paths.PUBLIC_ROOT.iterdir() if p.is_dir()))
def test_strict_flat_load_equals_the_directory_source(tmp_path: Path, name: str) -> None:
    """strict=True on our own episodes is the same load as `check` does."""
    loaded = load_episode_dir(flat_copy(name, tmp_path / name), strict=True)
    reference = DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT).load(name)
    assert (loaded.public, loaded.truth, loaded.warnings) == (reference.public, reference.truth, ())


def _edit_json(path: Path, edit: Callable[[Any], None]) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    edit(value)
    path.write_text(json.dumps(value), encoding="utf-8")


SOFT_REFUSALS: list[tuple[str, Callable[[Path], None], str]] = [
    ("edited truth amount", lambda d: _edit_json(d / "truth.json", lambda t: t["issues"][0].update(
        expected_amount_minor=t["issues"][0]["expected_amount_minor"] + 1)), "not what the published rules find"),
    ("tolerance 1", lambda d: _edit_json(d / "manifest.json", lambda m: m["amount_tolerance_minor"].update(
        {code: 1 for code in m["amount_tolerance_minor"]})), "tolerance 0"),
    ("unpublished policy", lambda d: _edit_json(d / "policy.json", lambda p: p.update(note="jury")), "published policy"),
    ("other schema version", lambda d: _edit_json(d / "manifest.json", lambda m: m.update(schema_version="x")),
     "schema_version"),
    ("smaller page limit", lambda d: _edit_json(d / "manifest.json", lambda m: m["limits"].update(page_limit=5)),
     "budget and caps"),
    ("counts", lambda d: _edit_json(d / "manifest.json", lambda m: m["counts"].update(fx_rates=1)), "counts"),
]  # fmt: skip


@pytest.mark.parametrize(("what", "edit", "message"), SOFT_REFUSALS, ids=[case[0] for case in SOFT_REFUSALS])
def test_strict_still_refuses_what_it_refused_and_non_strict_only_warns(
    tmp_path: Path, what: str, edit: Callable[[Path], None], message: str
) -> None:
    directory = flat_copy("fixture_duplicate", tmp_path / "ep")
    edit(directory)
    with pytest.raises(EpisodeError, match=message):
        load_episode_dir(directory, strict=True)
    roots = tmp_path / "roots"
    for half, files in (("public", PUBLIC_NAMES), ("private", ("truth.json", "provenance.json"))):
        (roots / half / "ep").mkdir(parents=True)
        for file in files:
            shutil.copy(directory / file, roots / half / "ep" / file)
    with pytest.raises(EpisodeError, match=message):  # our own layout refuses it as before
        DirectorySource(roots / "public", roots / "private").load("ep")
    loaded = load_episode_dir(directory, strict=False)
    assert loaded.warnings and any(message in warning for warning in loaded.warnings), what


HARD_REFUSALS: list[tuple[str, str, str, str]] = [
    ("ledger.csv", "row_id,", "id,", "header"),
    ("invoices.jsonl", '"doc_id":', '"document":', "exactly the keys"),
    ("payments.jsonl", '"amount_minor":', '"amount_minor":"1",', "not strict JSON"),
    ("manifest.json", '"episode_id": "', '"episode_id": "\\u0007', "control characters"),
    ("fx.csv", "\n20", "\n2x", "fx row"),
]


@pytest.mark.parametrize(("file", "old", "new", "message"), HARD_REFUSALS)
def test_formats_are_refused_in_both_modes(tmp_path: Path, file: str, old: str, new: str, message: str) -> None:
    directory = flat_copy("fixture_duplicate", tmp_path / "ep")
    text = (directory / file).read_text(encoding="utf-8")
    assert old in text
    (directory / file).write_text(text.replace(old, new, 1), encoding="utf-8")
    for strict in (True, False):
        with pytest.raises(EpisodeError, match=message):
            load_episode_dir(directory, strict=strict)


def test_trf_id_shape_duplicate_ids_within_a_space_are_refused_in_both_modes(tmp_path: Path) -> None:
    directory = flat_copy("fixture_duplicate", tmp_path / "ep")
    header, *rows = (directory / "ledger.csv").read_text(encoding="utf-8").splitlines()
    first, second = rows[0].split(",", 1)[0], rows[1].split(",", 1)[0]
    rows[1] = rows[1].replace(second, first, 1)
    (directory / "ledger.csv").write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    for strict in (True, False):
        with pytest.raises(EpisodeError, match="unique within each id space"):
            load_episode_dir(directory, strict=strict)


# ----------------------------------------------------------------------------- a hand-built jury fixture

TINY_MANIFEST = {
    "episode_id": "jury M08",
    "schema_version": "jury-fixture/1",
    "base_currency": "KZT",
    "period_start": "2026-10-01T00:00:00+05:00",
    "period_end": "2026-10-31T23:59:59+05:00",
    "timezone": "Asia/Almaty",
    "counts": {"ledger_rows": 5, "documents": 2, "fx_rates": 0},
    "currencies": {"KZT": {"exponent": 2}},
    "rounding": {"default": "half_up", "permitted": ["half_up"]},
    "amount_tolerance_minor": {"KZT": 1},
    "issue_types": ["duplicate_invoice", "payment_allocation", "fx_mismatch", "cutoff"],
    "limits": {"page_limit": 50, "max_steps": 100, "max_findings": 30, "max_evidence_ids": 10,
               "max_explanation_chars": 1000},
}  # fmt: skip
TINY_LEDGER = """row_id,timestamp,account,debit_minor,credit_minor,currency,entity_id,invoice_id,payment_id
R 1,2026-10-02T10:00:00+05:00,accounts_receivable,20000,0,KZT,client/7,inv-1,
R 2,2026-10-02T10:00:00+05:00,revenue,0,20000,KZT,client/7,inv-1,
R 3,2026-10-09T12:00:00+05:00,bank,20000,0,KZT,client/7,,pay-1
R 4,2026-10-09T12:00:00+05:00,accounts_receivable,0,10000,KZT,client/7,inv-1,pay-1
R 5,2026-10-09T12:00:00+05:00,unapplied_receipts,0,10000,KZT,client/7,,pay-1
"""
TINY_INVOICE = {"doc_id": "doc-A", "invoice_id": "inv-1", "entity_id": "client/7", "issued_at": "2026-10-02T10:00:00+05:00",
                "due_at": "2026-10-16T10:00:00+05:00", "currency": "KZT", "total_minor": 20000,
                "line_items": [{"description": "audit", "quantity": 1, "unit_price_minor": 20000, "amount_minor": 20000}]}  # fmt: skip
TINY_PAYMENT = {"payment_id": "pay-1", "doc_id": "doc-B", "timestamp": "2026-10-09T12:00:00+05:00", "currency": "KZT",
                "amount_minor": 20000, "invoice_refs": ["inv-1"]}  # fmt: skip
TINY_TRUTH = {"issues": [{"issue_id": "M08", "type": "payment_allocation", "affected_ids": ["inv-1", "pay-1"],
                          "expected_amount_minor": 10000, "currency": "KZT",
                          "acceptable_evidence_sets": [["doc-A", "doc-B", "R 4"]]}]}  # fmt: skip


def tiny_episode(directory: Path) -> Path:
    directory.mkdir(parents=True)
    files = {
        "manifest.json": json.dumps(TINY_MANIFEST),
        "policy.json": json.dumps({"policy_version": "jury-hand-built", "note": "not a published policy"}),
        "ledger.csv": TINY_LEDGER,
        "invoices.jsonl": json.dumps(TINY_INVOICE) + "\n",
        "payments.jsonl": json.dumps(TINY_PAYMENT) + "\n",
        "fx.csv": "date,source_currency,target_currency,rate\n",
        "truth.json": json.dumps(TINY_TRUTH),
    }
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8")
    return directory


def test_m08_hand_built_tau_one_fixture_loads_non_strict_and_only_warns(tmp_path: Path) -> None:
    directory = tiny_episode(tmp_path / "M08")
    with pytest.raises(EpisodeError):
        load_episode_dir(directory, strict=True)
    loaded = load_episode_dir(directory, strict=False)
    assert loaded.warnings  # the contract and our rules cannot judge it: logged, not refused
    assert any("published policy" in warning for warning in loaded.warnings)
    assert loaded.public.manifest["amount_tolerance_minor"] == {"KZT": 1}
    assert list(loaded.public.manifest["rounding"]) == ["permitted", "default"]  # canonical order
    rewards = {}
    for claimed in (9998, 9999, 10000, 10001, 10002):
        rewards[claimed] = play(loaded, [m08_finding(claimed, "KZT")], [FETCH_R4], mode="train")["counts"]
    hit, miss = {"tp": 1, "fp": 0, "fn": 0}, {"tp": 0, "fp": 1, "fn": 1}
    assert rewards == {9998: miss, 9999: hit, 10000: hit, 10001: hit, 10002: miss}  # |claimed - 10000| <= 1


FETCH_R4 = {"action": "get_record", "args": {"table": "ledger", "id": "R 4"}}


def m08_finding(claimed: int, currency: str) -> dict[str, Any]:
    return {"type": "payment_allocation", "affected_ids": ["pay-1", "inv-1"], "claimed_amount_minor": claimed,
            "currency": currency, "evidence_ids": ["R 4", "doc-A", "doc-B"], "explanation": "M08"}  # fmt: skip


def test_m07_a_truth_currency_the_manifest_does_not_declare_is_exact_and_scoring_never_crashes(tmp_path: Path) -> None:
    """Tolerance default: tau is 0 unless published. A non-strict load may hold truth in a currency the manifest's
    tolerance map does not list; it is then compared exactly (10001 misses) instead of crashing the scoring."""
    directory = tiny_episode(tmp_path / "usd")
    truth = json.loads(json.dumps(TINY_TRUTH))
    truth["issues"][0]["currency"] = "USD"
    (directory / "truth.json").write_text(json.dumps(truth), encoding="utf-8")
    loaded = load_episode_dir(directory, strict=False)
    assert loaded.tolerance() == {"KZT": 1, "USD": 0}
    hit, miss = {"tp": 1, "fp": 0, "fn": 0}, {"tp": 0, "fp": 1, "fn": 1}
    for claimed, currency, expected in ((10000, "USD", hit), (10001, "USD", miss), (10000, "KZT", miss)):
        for mode in ("train", "eval"):
            assert play(loaded, [m08_finding(claimed, currency)], [FETCH_R4], mode=mode)["counts"] == expected


def test_trf_blank_last_lines_are_tolerated_in_csv_as_in_jsonl_but_an_empty_record_is_not(tmp_path: Path) -> None:
    reference = load_episode_dir(flat_copy("fixture_duplicate", tmp_path / "a"), strict=True)
    directory = flat_copy("fixture_duplicate", tmp_path / "b")
    for file in ("ledger.csv", "fx.csv", "payments.jsonl"):
        (directory / file).write_text((directory / file).read_text(encoding="utf-8") + "   \n\t\n", encoding="utf-8")
    assert load_episode_dir(directory, strict=True).public == reference.public
    fx = directory / "fx.csv"
    fx.write_text(fx.read_text(encoding="utf-8").rstrip() + "\n,,,\n", encoding="utf-8")
    for strict in (True, False):
        with pytest.raises(EpisodeError, match="fx row"):
            load_episode_dir(directory, strict=strict)
