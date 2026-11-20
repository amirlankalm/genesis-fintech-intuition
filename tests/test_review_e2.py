"""Regression tests for the adversarial review of the case stage (docs/review/E2_case_stage_review.md).

Each test is one of the reviewer's failures, written as the attack and asserted to fail now.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import shutil
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from genesis_audit import books, cli, evaluate, families, paths, shipped, store
from genesis_audit.episodes import DirectorySource, LoadedEpisode
from genesis_audit.errors import EpisodeError, PolicyVisibleError
from genesis_audit.families import when
from genesis_audit.sandbox import Confinement

PLAIN = Confinement("none")


def copy_episode(tmp_path: Path, name: str, as_name: str | None = None) -> tuple[Path, Path]:
    public, private = tmp_path / "public" / (as_name or name), tmp_path / "private" / (as_name or name)
    shutil.copytree(paths.PUBLIC_ROOT / name, public)
    shutil.copytree(paths.PRIVATE_ROOT / name, private)
    return public, private


def edit_json(path: Path, change: Any) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


# 1 ------------------------------------------------------------------ recorded settings regenerate the episode


@pytest.mark.parametrize("name", evaluate.GENERATED)
def test_the_recorded_settings_regenerate_the_episode(name: str) -> None:
    """Failure 1: provenance stored a normalised `inject`, and the error stream was keyed on the caller's spelling."""
    recorded = json.loads((paths.PRIVATE_ROOT / name / "provenance.json").read_text(encoding="utf-8"))["generator"]
    public_files, private_files = books.render(
        *shipped.generate(recorded["seed"], recorded["config"], recorded["inject"])
    )
    for filename, text in public_files.items():
        assert (paths.PUBLIC_ROOT / name / filename).read_text(encoding="utf-8") == text, filename
    assert (paths.PRIVATE_ROOT / name / "truth.json").read_text(encoding="utf-8") == private_files["truth.json"]


def test_how_inject_is_spelled_does_not_change_the_episode() -> None:
    config = {"invoices": 24, "ledger_rows": 220}
    spelled = [{"cutoff": 1, "duplicate_invoice": 1}, {"duplicate_invoice": 1, "cutoff": 1, "fx_mismatch": 0},
               {"interactions": [], "payment_allocation": 0, "cutoff": 1, "duplicate_invoice": 1}]  # fmt: skip
    rendered = [books.render(*shipped.generate(9, config, inject)) for inject in spelled]
    assert rendered[0] == rendered[1] == rendered[2]


# 2 ---------------------------------------------------------------------- a weakened grader does not load


def _huge_tolerance(manifest: dict) -> None:
    manifest["amount_tolerance_minor"] = {code: 10**12 for code in manifest["currencies"]}


def _huge_page(manifest: dict) -> None:
    manifest["limits"]["page_limit"] = 2000


def _huge_budget(manifest: dict) -> None:
    manifest["limits"]["max_steps"] = 100_000


def _fewer_families(manifest: dict) -> None:
    manifest["issue_types"] = ["cutoff"]


def _other_rule(policy: dict) -> None:
    policy["cutoff"]["note"] = "Revenue belongs to the period of the due date."


WEAKENED = [("manifest.json", _huge_tolerance, "tolerance"), ("manifest.json", _huge_page, "may not exceed the draft"),
            ("manifest.json", _huge_budget, "may not exceed the draft"), ("manifest.json", _fewer_families, "not declared in manifest.issue_types|declares exactly"),
            ("policy.json", _other_rule, "is not the published policy")]  # fmt: skip


@pytest.mark.parametrize(
    ("filename", "change", "message"), WEAKENED, ids=[change.__name__ for _, change, _ in WEAKENED]
)
def test_a_root_with_a_weakened_grader_does_not_load(tmp_path: Path, filename: str, change: Any, message: str) -> None:
    """Failure 2: a manifest or policy file could raise the tolerance, the page size or the budget, or rewrite a rule."""
    public, _ = copy_episode(tmp_path, "fixture_fx")
    source = DirectorySource(tmp_path / "public", tmp_path / "private")
    assert len(source.load("fixture_fx").truth) == 2
    edit_json(public / filename, change)
    with pytest.raises(EpisodeError, match=message):
        source.load("fixture_fx")


def test_truth_inside_the_tolerance_is_refused(source) -> None:
    from genesis_audit.truth import validate_truth

    loaded = source.load("teaching_b")
    loose = {**loaded.public.manifest, "amount_tolerance_minor": {"KZT": 100_000, "USD": 0}}
    with pytest.raises(EpisodeError, match="within the tolerance"):
        validate_truth(loaded.truth, dataclasses.replace(loaded.public, manifest=loose))
    validate_truth(
        loaded.truth,
        dataclasses.replace(loaded.public, manifest={**loose, "amount_tolerance_minor": {"KZT": 99_999, "USD": 0}}),
    )


# 3 ----------------------------------------------------------------------------- the probe aims at what exists


def test_the_boundary_probe_aims_at_an_episode_that_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure 3: the probe was aimed at `teaching_b`; on a root without it every read "failed" for the wrong reason."""
    copy_episode(tmp_path, "fixture_fx", "held_only")
    monkeypatch.setattr(paths, "PUBLIC_ROOT", tmp_path / "public")
    monkeypatch.setattr(paths, "PRIVATE_ROOT", tmp_path / "private")
    unconfined = evaluate.probe_in_process(PLAIN)
    assert unconfined["attempts"]["read_truth"] == "ok" and unconfined["attempts"]["read_public_file"] == "ok"
    strongest = Confinement.strongest((tmp_path,))
    if strongest.backend != "none":
        confined = evaluate.probe_in_process(strongest)
        assert confined["held"] and confined["attempts"]["read_truth"].startswith("denied:Permission")
    shutil.rmtree(tmp_path / "public" / "held_only")
    empty = evaluate.probe_in_process(PLAIN)
    assert empty["held"] is False and "no episode" in empty["error"]


# 4, 8 -------------------------------------------------------------- over-allocation and bad refunds do not load


def _rows(public: Path) -> list[list[str]]:
    return [line.split(",") for line in (public / "ledger.csv").read_text(encoding="utf-8").splitlines()]


def _write(public: Path, rows: list[list[str]]) -> None:
    (public / "ledger.csv").write_text("".join(",".join(row) + "\n" for row in rows), encoding="utf-8")


def test_over_allocation_is_refused_at_load(tmp_path: Path) -> None:
    """Failure 4: SPEC says refused at load; the loader accepted it and the harness crashed later."""
    public, _ = copy_episode(tmp_path, "fixture_clean")
    rows = _rows(public)
    header = rows[0]
    account, credit, debit, payment = (
        header.index(c) for c in ("account", "credit_minor", "debit_minor", "payment_id")
    )
    for row in rows[1:]:  # P27 pays 230,000 on a 200,000 invoice: apply 210,000 and leave 20,000, refund 20,000
        if row[payment] == "P27" and row[account] == "accounts_receivable":
            row[credit] = "210000"
        elif row[payment] == "P27" and row[account] == "unapplied_receipts":
            row[credit if row[credit] != "0" else debit] = "20000"
        elif row[payment] == "P27" and row[account] == "bank" and row[credit] != "0":
            row[credit] = "20000"
    _write(public, rows)
    with pytest.raises(EpisodeError, match="over-allocation"):
        DirectorySource(tmp_path / "public", tmp_path / "private").load("fixture_clean")


def test_refunds_outside_the_convention_are_refused() -> None:
    """Failure 8: a refund in another currency, one before its receipt, one of a translated receipt."""
    clean = shipped.build("fixture_clean")[0]

    def with_refund(**changes: Any) -> store.PublicEpisode:
        rows = [dict(row) for row in clean.tables["ledger"]]
        for row in rows:
            if row["payment_id"] == "P27" and (
                row["debit_minor"] == 30000 or (row["account"] == "bank" and row["credit_minor"])
            ):
                row.update(changes)
        return dataclasses.replace(clean, tables={**clean.tables, "ledger": tuple(rows)})

    families.validate_books(clean)
    with pytest.raises(EpisodeError, match="in the receipt's currency and later"):
        families.validate_books(with_refund(currency="USD"))
    with pytest.raises(EpisodeError, match="in the receipt's currency and later"):
        families.validate_books(with_refund(timestamp="2026-11-01T12:00:00+05:00"))  # two days before the receipt
    translated = copy.deepcopy(dict(shipped.FIXTURE_WORLD))
    translated["refunds"] = [{"payment_id": "P40", "timestamp": "2026-10-27T12:00:00+05:00", "amount_minor": 1}]
    with pytest.raises(EpisodeError):  # P40 is a KZT receipt for a JPY invoice
        books.build(translated, [])
    two_customers = copy.deepcopy(dict(shipped.FIXTURE_WORLD))
    two_customers["payments"][0]["invoice_refs"] = ["I21", "I11"]
    with pytest.raises(EpisodeError, match="more than one customer"):
        books.build(two_customers, [])


# 5, 6 ------------------------------------------------------------------------------------ shortcuts


def test_proximity_of_postings_does_not_find_duplicates(source) -> None:
    """Failure 6: "two revenue credits, same customer, currency and amount, within four hours" used to score F1 0.8."""
    tp = fp = fn = 0
    for name in evaluate.GENERATED:
        loaded = source.load(name)
        truth = {tuple(sorted(issue.affected_ids)) for issue in loaded.truth if issue.type == "duplicate_invoice"}
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for row in loaded.public.tables["ledger"]:
            if row["account"] == "revenue":
                groups[(row["entity_id"], row["currency"], row["credit_minor"])].append(row)
        claimed = {tuple(sorted((a["invoice_id"], b["invoice_id"]))) for rows in groups.values() for a in rows for b in rows
                   if a["row_id"] < b["row_id"] and abs(when(a["timestamp"]) - when(b["timestamp"])) <= timedelta(hours=4)}  # fmt: skip
        tp, fp, fn = tp + len(claimed & truth), fp + len(claimed - truth), fn + len(truth - claimed)
    assert tp + fn == 11 and fp >= 20  # every company has valid pairs posted together
    assert 2 * tp / (2 * tp + fp + fn) < 0.5


def test_part_of_the_duplicate_rule_is_not_enough(source) -> None:
    """Customer, issue instant and total agree for valid pairs too: the lines and the due date decide."""
    tp = fp = fn = 0
    for name in evaluate.GENERATED:
        loaded = source.load(name)
        truth = {tuple(sorted(issue.affected_ids)) for issue in loaded.truth if issue.type == "duplicate_invoice"}
        groups: dict[tuple, list[str]] = defaultdict(list)
        for invoice in loaded.public.tables["invoices"]:
            groups[(invoice["entity_id"], when(invoice["issued_at"]), invoice["total_minor"])].append(
                invoice["invoice_id"]
            )
        claimed = {tuple(sorted(ids)) for ids in groups.values() if len(ids) > 1}
        tp, fp, fn = tp + len(claimed & truth), fp + len(claimed - truth), fn + len(truth - claimed)
    assert fp >= 2 * 20 - 5 and 2 * tp / (2 * tp + fp + fn) < 0.5


# 7 ------------------------------------------------------------------------- the stored measurements are checked


def test_falsified_measurements_and_stray_files_are_noticed(tmp_path: Path) -> None:
    """Failure 7: `check` passed with a falsified scale file, an emptied sweep and an answer key in the public half."""
    stored = json.loads((paths.REPO_ROOT / "docs" / "measurements" / "scale.json").read_text(encoding="utf-8"))
    measured = evaluate.scale_measurements(PLAIN)
    assert evaluate.scale_facts(stored) == evaluate.scale_facts(measured)  # everything but clocks and memory
    falsified = copy.deepcopy(stored)
    falsified["episodes"]["dev_09"]["steps_to_read_everything"] = 5
    assert evaluate.scale_facts(falsified) != evaluate.scale_facts(measured)
    slower = copy.deepcopy(stored)
    slower["slowest_solver_episode_seconds"] = 999.0  # a clock reading: reported, never compared
    assert evaluate.scale_facts(slower) == evaluate.scale_facts(measured)
    sweep = json.loads(
        (paths.REPO_ROOT / "docs" / "measurements" / "random_inspector_sweep.json").read_text(encoding="utf-8")
    )
    assert evaluate.sweep_agrees(sweep, PLAIN, seeds=6)
    assert not evaluate.sweep_agrees({}, PLAIN) and not evaluate.sweep_agrees(None, PLAIN)
    emptied = copy.deepcopy(sweep)
    emptied["episodes"]["teaching_b"]["reward_histogram"] = {"1.000": 400}
    assert not evaluate.sweep_agrees(emptied, PLAIN, seeds=6)
    public, private = copy_episode(tmp_path, "fixture_fx")
    source = DirectorySource(tmp_path / "public", tmp_path / "private")
    shutil.copy(private / "truth.json", public / "truth.json")
    with pytest.raises(EpisodeError, match="unexpected files in the public half"):
        source.load("fixture_fx")
    (public / "truth.json").unlink()
    (private / "notes.txt").write_text("x")
    with pytest.raises(EpisodeError, match="nothing else"):
        source.load("fixture_fx")
    (private / "notes.txt").unlink()
    (private / "provenance.json").unlink()  # failure 10: a missing provenance file is a refusal, not a crash later
    with pytest.raises(EpisodeError, match="cannot read the private half"):
        source.load("fixture_fx")


def test_truth_with_an_extra_evidence_set_or_a_missing_issue_does_not_load(tmp_path: Path) -> None:
    """Weak spot: these were caught only by the independent checker. Now the loader derives truth and compares."""
    _, private = copy_episode(tmp_path, "fixture_fx")
    source = DirectorySource(tmp_path / "public", tmp_path / "private")
    original = (private / "truth.json").read_text(encoding="utf-8")
    edit_json(private / "truth.json", lambda doc: doc["issues"][0]["acceptable_evidence_sets"].append(["D03"]))
    with pytest.raises(EpisodeError, match="not what the published rules find"):
        source.load("fixture_fx")
    (private / "truth.json").write_text(original, encoding="utf-8")
    edit_json(private / "truth.json", lambda doc: doc["issues"].pop())
    with pytest.raises(EpisodeError, match="2 derived"):
        source.load("fixture_fx")


# 9 ------------------------------------------------------------------------------------------- generate


def test_generate_is_all_or_nothing_and_says_which_key_it_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Failure 9: a repeated name replaced an episode, a refused entry left others written, bad JSON gave a traceback."""
    monkeypatch.setattr(paths, "PUBLIC_ROOT", tmp_path / "public")
    monkeypatch.setattr(paths, "PRIVATE_ROOT", tmp_path / "private")
    job = tmp_path / "job.json"
    good = {"name": "held_a", "seed": 5, "config": {"invoices": 20, "ledger_rows": 210}}

    def generate(text: str) -> int:
        job.write_text(text, encoding="utf-8")
        return cli.main(["generate", "--job", str(job)])

    assert generate(json.dumps({"episodes": [good, {**good, "seed": 6}]})) == 2  # the same name twice
    assert generate(json.dumps({"episodes": [good, {"name": "held_b", "seed": 6, "config": {"invoices": 2}}]})) == 2
    assert generate(json.dumps({"episodes": [good, {"name": "held_b", "seed": 6, "inject": ["cutoff"]}]})) == 2
    assert not (tmp_path / "public").exists()  # the first, valid entry was not written either
    assert generate("{not json") == 2
    err = capsys.readouterr().err
    assert "share a name" in err and "not readable strict JSON" in err and "Traceback" not in err
    assert generate(json.dumps({"episodes": [good]})) == 0
    assert "public development key" in capsys.readouterr().err  # said out loud, not silently


# 11 ---------------------------------------------------------------------------- what the spec says the code does


def test_structure_is_checked_after_every_single_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure 11: SPEC 6.0 says "again after every injected error"; only the first and last versions were checked."""
    seen = []
    real = books.validate_books
    monkeypatch.setattr(
        books, "validate_books", lambda public: (seen.append(public.manifest["counts"]["ledger_rows"]), real(public))[1]
    )
    errors = [*shipped.FIXTURES["fixture_x_duplicate_cutoff"], *shipped.FIXTURES["fixture_fx"]]
    books.build(shipped.FIXTURE_WORLD, errors)
    assert len(seen) >= len(errors)  # the clean books and each intermediate version; the last is checked by detect


def test_cursors_have_one_spelling(source) -> None:
    public = source.load("train_10").public
    page, cursor = public.list_page("ledger", None, 50)
    assert cursor == "ledger:50" and public.list_page("ledger", cursor, 50)[0][0] != page[0]
    for odd in ("ledger:050", "ledger:00050", "ledger:0", "ledger:+50", "ledger: 50"):
        with pytest.raises(PolicyVisibleError):
            public.list_page("ledger", odd, 50)


# ------------------------------------------------- defects found by the independent grader (third pass)


def _odd_offset_pairs(invoices: list[dict]) -> set[tuple[str, ...]]:
    """The grader's shortcut: an invoice written at an offset unlike its customer's others, with one same-total sibling."""
    by_customer: dict[str, list[dict]] = defaultdict(list)
    for invoice in invoices:
        by_customer[invoice["entity_id"]].append(invoice)
    claimed = set()
    for group in by_customer.values():
        for invoice in group:
            others = [other for other in group if other is not invoice]
            offset = when(invoice["issued_at"]).utcoffset()
            same_total = [other for other in others if other["total_minor"] == invoice["total_minor"]]
            if (
                others
                and all(when(other["issued_at"]).utcoffset() != offset for other in others)
                and len(same_total) == 1
            ):
                claimed.add(tuple(sorted((invoice["invoice_id"], same_total[0]["invoice_id"]))))
    return claimed


def test_an_unusual_offset_does_not_mark_a_copy(source) -> None:
    """Grader, defect 1: copies written at another offset were the only invoices at an offset unlike their customer's."""
    tp = fp = fn = 0
    companies = [source.load(name) for name in evaluate.GENERATED]
    for seed in range(40):
        public, truth, _ = shipped.generate(seed, {}, {"duplicate_invoice": 3})
        companies.append(LoadedEpisode(public=public, truth=truth))
    for loaded in companies:
        truth = {tuple(sorted(issue.affected_ids)) for issue in loaded.truth if issue.type == "duplicate_invoice"}
        claimed = _odd_offset_pairs(list(loaded.public.tables["invoices"]))
        tp, fp, fn = tp + len(claimed & truth), fp + len(claimed - truth), fn + len(truth - claimed)
    assert tp + fn == 11 + 3 * 40
    assert fp > tp and 2 * tp / (2 * tp + fp + fn) < 0.5, (tp, fp, fn)  # the grader's bar; it was 84 right and 2 wrong


def test_a_case_root_cannot_shed_its_contract(tmp_path: Path) -> None:
    """Grader, defect 2: deleting `accounts` from policy.json made a case episode load as if no contract applied."""
    public, _ = copy_episode(tmp_path, "fixture_cutoff")
    source = DirectorySource(tmp_path / "public", tmp_path / "private")
    original = {name: (public / name).read_text(encoding="utf-8") for name in ("policy.json", "manifest.json")}

    def restore() -> None:
        for name, text in original.items():
            (public / name).write_text(text, encoding="utf-8")

    def weakened(policy: dict) -> None:
        del policy["accounts"]
        policy["cutoff"]["note"] = "Any posting is fine."

    edit_json(public / "policy.json", weakened)
    edit_json(
        public / "manifest.json",
        lambda m: m.update(issue_types=["cutoff"], amount_tolerance_minor={c: 119_999 for c in m["currencies"]}),
    )
    with pytest.raises(EpisodeError, match="is not the published policy"):
        source.load("fixture_cutoff")
    restore()
    # case-draft-2 is published since 20 Nov 2026; the withdrawn case-draft-1 and a future name are not.
    for unpublished in ("case-draft-1", "case-draft-3"):
        edit_json(public / "policy.json", lambda policy, name=unpublished: policy.update(policy_version=name))
        with pytest.raises(EpisodeError, match="names no published policy version"):
            source.load("fixture_cutoff")
        restore()
    edit_json(
        public / "policy.json", lambda policy: policy.update(policy_version="teaching-1")
    )  # borrow the smaller policy
    with pytest.raises(EpisodeError, match="is not the published policy teaching-1"):
        source.load("fixture_cutoff")
    restore()
    edit_json(public / "manifest.json", lambda m: m.update(amount_tolerance_minor={c: 5 for c in m["currencies"]}))
    with pytest.raises(EpisodeError, match="tolerance 0"):
        source.load("fixture_cutoff")
    restore()
    edit_json(public / "manifest.json", lambda m: m.update(schema_version="something-else"))
    with pytest.raises(EpisodeError, match="schema_version does not belong"):
        source.load("fixture_cutoff")
    restore()
    assert len(source.load("fixture_cutoff").truth) == 1
    teaching_public, _ = copy_episode(tmp_path, "teaching_b")
    edit_json(teaching_public / "manifest.json", lambda m: m.update(amount_tolerance_minor={"KZT": 99_999, "USD": 0}))
    with pytest.raises(EpisodeError, match="tolerance 0"):  # the same holds for the teaching episodes
        source.load("teaching_b")


def test_replay_gives_a_verdict_on_a_report_it_cannot_re_run(capsys) -> None:
    """Grader, defect 4: a doctored termination cause made `replay` exit with a LifecycleError and no verdict."""
    record = evaluate.run("never_acts", "fixture_clean", confinement=PLAIN)
    assert evaluate.replay(record)["match"]
    doctored = dataclasses.replace(record, report={**record.report, "termination_cause": "submitted"})
    verdict = evaluate.replay(doctored)
    assert verdict["match"] is False and verdict["error"] == "LifecycleError"
    unknown = dataclasses.replace(record, config={"episode": "no_such_episode"})
    assert evaluate.replay(unknown)["match"] is False


def test_a_probe_with_no_boundary_never_reports_that_it_held(capsys) -> None:
    """Grader, defect 5: `probe --confine none` printed "held": true and exited 0 while every attempt succeeded."""
    report = evaluate.probe_in_process(PLAIN)
    assert report["held"] is False and report["attempts"]["read_truth"] == "ok"
    assert cli.main(["probe", "--confine", "none"]) == 1
    assert '"held": false' in capsys.readouterr().out


def _same_instant_pairs(public: store.PublicEpisode) -> dict[str, set[tuple[str, ...]]]:
    """One-feature guesses at which pair of one customer at one instant is the duplicate. None reads lines or due date."""
    indexed = families.index(public)
    invoices = {invoice["invoice_id"]: invoice for invoice in public.tables["invoices"]}
    posted = {key: when(families.revenue_row(indexed, key)["timestamp"]) for key in invoices}
    paid = {ref for payment in public.tables["payments"] for ref in payment["invoice_refs"]}
    groups: dict[tuple, list[str]] = defaultdict(list)
    for key, invoice in invoices.items():
        groups[(invoice["entity_id"], when(invoice["issued_at"]))].append(key)
    pairs = [tuple(sorted(ids)) for ids in groups.values() if len(ids) == 2]

    def offset(key: str) -> Any:
        return when(invoices[key]["issued_at"]).utcoffset()

    def local_hour(key: str) -> int:
        return when(invoices[key]["issued_at"]).astimezone(indexed.offset).hour

    def terms(key: str) -> int:
        return (when(invoices[key]["due_at"]) - when(invoices[key]["issued_at"])).days

    return {
        "every such pair": set(pairs),
        "posted at different instants": {p for p in pairs if posted[p[0]] != posted[p[1]]},  # the grader's defect 7
        "posted at the same instant": {p for p in pairs if posted[p[0]] == posted[p[1]]},
        "exactly one has no receipt": {p for p in pairs if (p[0] in paid) != (p[1] in paid)},
        "neither has a receipt": {p for p in pairs if p[0] not in paid and p[1] not in paid},
        "written at different offsets": {p for p in pairs if offset(p[0]) != offset(p[1])},
        "same total": {p for p in pairs if invoices[p[0]]["total_minor"] == invoices[p[1]]["total_minor"]},
        # the grader's defect 8: what the first record of a pair looks like
        "a record has more than one line": {p for p in pairs if any(len(invoices[k]["line_items"]) > 1 for k in p)},
        "issued outside office hours": {p for p in pairs if not 8 <= local_hour(p[0]) < 19},
        "neither is due 14 days after issue": {p for p in pairs if all(terms(k) != 14 for k in p)},
        "a record is due 7 or 21 days after issue": {p for p in pairs if any(terms(k) in (7, 21) for k in p)},
        "any of lines, hours, terms": {p for p in pairs if any(len(invoices[k]["line_items"]) > 1 for k in p)
                                       or not 8 <= local_hour(p[0]) < 19 or all(terms(k) != 14 for k in p)},
        # most of the rule: one of its two decisive fields, without the other
        "same lines": {p for p in pairs if invoices[p[0]]["line_items"] == invoices[p[1]]["line_items"]},
        "same due date": {p for p in pairs if when(invoices[p[0]]["due_at"]) == when(invoices[p[1]]["due_at"])},
    }  # fmt: skip


def test_nothing_but_the_rule_tells_a_copy_from_a_valid_sibling(source) -> None:
    """Grader, defects 7 and 8: posting time, and then the look of the first record, gave a copy away.

    Valid same-instant pairs were always posted together and copies never were (F1 0.89). When that was
    fixed, every valid sibling still came from one template (one line, office hours, 14-day terms), so a
    pair that did not fit the template was a copy for certain (F1 0.80, no false positive). A valid
    sibling is now made from an invoice chosen at random, as a copy is, and drawn like a copy in everything
    the rule does not name. Each guess below stays under F1 0.5 and is wrong more often than right, on the
    shipped episodes and on fresh companies with three copies each.
    """
    companies = [source.load(name) for name in evaluate.GENERATED]
    for seed in range(40):
        public, truth, _ = shipped.generate(seed, {}, {"duplicate_invoice": 3})
        companies.append(LoadedEpisode(public=public, truth=truth))
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for loaded in companies:
        truth = {tuple(sorted(issue.affected_ids)) for issue in loaded.truth if issue.type == "duplicate_invoice"}
        for guess, claimed in _same_instant_pairs(loaded.public).items():
            counts[guess][0] += len(claimed & truth)
            counts[guess][1] += len(claimed - truth)
            counts[guess][2] += len(truth - claimed)
    scores = {guess: 2 * tp / (2 * tp + fp + fn) for guess, (tp, fp, fn) in counts.items()}
    assert max(scores.values()) < 0.5, scores
    assert all(fp > tp for tp, fp, _ in counts.values()), dict(counts)  # each guess is wrong more often than right


def test_replay_never_crashes_on_a_doctored_report(tmp_path: Path, capsys) -> None:
    """Grader's re-check: a report without its digest or score, or one that is not an object, still crashed `replay`."""
    record = evaluate.run("always_abstain", "fixture_clean", confinement=PLAIN)
    for doctored in ({k: v for k, v in record.report.items() if k != "trajectory_digest"},
                     {k: v for k, v in record.report.items() if k != "score"}, None, [], "report"):  # fmt: skip
        verdict = evaluate.replay(dataclasses.replace(record, report=doctored))
        assert verdict["match"] is False, doctored
    (tmp_path / "public").mkdir()
    (tmp_path / "evaluator").mkdir()
    (tmp_path / "public" / "trajectories.jsonl").write_text(
        "".join(line + "\n" for line in evaluate.trajectory_lines([record]))
    )
    saved = {"policy": record.policy, "episode": record.episode, "seed": record.seed, "config": record.config,
             "report": record.report, "process": record.process}  # fmt: skip
    for report in (record.report, {k: v for k, v in record.report.items() if k != "score"}, None):
        (tmp_path / "evaluator" / "reports.json").write_text(json.dumps([{**saved, "report": report}]))
        assert (
            cli.main(["replay", str(tmp_path)]) == 1
        )  # one run is never the committed set; a doctored one never crashes
    out = capsys.readouterr()
    assert "MISMATCH" in out.out and "Traceback" not in out.err and "Error" not in out.err


def test_a_group_of_three_or_a_count_does_not_mark_copies() -> None:
    """Grader, defect 9 (found at its final re-check; this fix was not re-graded).

    An invoice could have at most one valid sibling and a sibling none, and their number was a fixed
    function of the company's size. So three records of one customer at one instant meant a copy, and
    counting second records gave the number of copies exactly. Now any record may get a sibling, and
    their number is drawn.
    """

    def same_instant_groups(public: store.PublicEpisode) -> list[list[dict]]:
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for invoice in public.tables["invoices"]:
            groups[(invoice["entity_id"], when(invoice["issued_at"]))].append(invoice)
        return [group for group in groups.values() if len(group) > 1]

    seconds: dict[str, list[int]] = {"clean": [], "faulty": []}
    with_three = {"clean": 0, "faulty": 0}
    right = wrong = 0
    for seed in range(40):
        for label, inject in (("clean", {}), ("faulty", {"duplicate_invoice": 3})):
            public, truth, _ = shipped.generate(seed, {}, inject)
            groups = same_instant_groups(public)
            seconds[label].append(sum(len(group) - 1 for group in groups))
            with_three[label] += any(len(group) >= 3 for group in groups)
            copies = {tuple(sorted(issue.affected_ids)) for issue in truth}
            for group in groups:  # the grader's guess: in a group of three, the one pair with equal totals
                pairs = [(a, b) for position, a in enumerate(group) for b in group[position + 1 :]]
                equal = [pair for pair in pairs if pair[0]["total_minor"] == pair[1]["total_minor"]]
                if label == "faulty" and len(group) == 3 and len(equal) == 1:
                    claimed = tuple(sorted(invoice["invoice_id"] for invoice in equal[0]))
                    right, wrong = right + (claimed in copies), wrong + (claimed not in copies)
    assert with_three["clean"] >= 24  # most clean companies have three records of one customer at one instant
    assert wrong > right  # and in such a group the equal-total pair is usually two valid records
    assert len(set(seconds["clean"])) >= 6  # the number of second records is not a function of the size
    overlap = [count for count in seconds["faulty"] if min(seconds["clean"]) <= count <= max(seconds["clean"])]
    assert len(overlap) >= 20  # at least half the companies with three copies have a count some clean company has
