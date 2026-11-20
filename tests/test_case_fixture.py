"""The hand-built case fixture: one variant per family and per interaction, with answers worked by hand.

Nothing in EXPECTED is computed by the package. The amounts are the arithmetic written out in
`test_the_hand_arithmetic`; the ids are the ones written in the fixture's history; a ledger row is
named by what it is (the revenue row of an invoice, the fx_clearing debit of a receipt), not by its label.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import pytest

from genesis_audit import books, families, shipped
from genesis_audit.env import AuditEnv
from genesis_audit.oracle import oracle_findings


def revenue_row(invoice_id: str):
    return lambda row: row["account"] == "revenue" and row["invoice_id"] == invoice_id


def clearing_debit(payment_id: str):
    return lambda row: row["account"] == "fx_clearing" and row["payment_id"] == payment_id and row["debit_minor"] > 0


def allocation_row(invoice_id: str, payment_id: str):
    return lambda row: (
        (row["account"], row["invoice_id"], row["payment_id"]) == ("accounts_receivable", invoice_id, payment_id)
    )


FX_P31 = ("fx_mismatch", {"P31"}, 100_000, "KZT", ["D03", "2026-10-21|USD|KZT", clearing_debit("P31")])
EXPECTED: dict[str, list[tuple[str, set[str], int, str, list[Any]]]] = {
    "fixture_clean": [],
    "fixture_duplicate": [("duplicate_invoice", {"I26", "I33"}, 80_000, "KZT", ["D07", "D58"])],
    "fixture_allocation": [("payment_allocation", {"I26", "P22"}, 80_000, "KZT", ["D07", "D25"])],
    "fixture_fx": [FX_P31, ("fx_mismatch", {"P40"}, 700, "JPY", ["D19", "2026-10-25|JPY|KZT", clearing_debit("P40")])],
    "fixture_cutoff": [("cutoff", {"I11"}, 120_000, "KZT", ["D29", revenue_row("I11")])],
    "fixture_x_fx_allocation": [
        # case-draft-2: P31 is in USD and I08 in KZT, so what P31 brings is its clearing debit, cited too
        (
            "payment_allocation",
            {"I08", "P31"},
            900_000,
            "KZT",
            ["D12", "D03", allocation_row("I08", "P31"), clearing_debit("P31")],
        ),
        FX_P31,
    ],
    "fixture_x_duplicate_cutoff": [
        ("duplicate_invoice", {"I11", "I35"}, 120_000, "KZT", ["D29", "D60"]),
        ("cutoff", {"I35"}, 120_000, "KZT", ["D60", revenue_row("I35")]),
    ],
}


def half_up(value: Fraction) -> int:
    return int(value + Fraction(1, 2))


def test_the_hand_arithmetic() -> None:
    """The numbers in EXPECTED and in SPEC section 6.7, from literals alone."""
    usd = Fraction(10_000, 100)  # USD 100.00
    assert half_up(usd * Fraction("500.00") * 100) == 5_000_000  # at the 21 October rate: 50,000.00 KZT
    assert half_up(usd * Fraction("490.00") * 100) == 4_900_000  # at the 20 October rate
    assert 5_000_000 - 4_900_000 == 100_000
    kzt = Fraction(20_000_000, 100)  # 200,000.00 KZT, to be divided: the pair is quoted JPY to KZT
    assert half_up(kzt / Fraction("3.40")) == 58_824  # 58,823.53 rounds up; JPY has no minor unit
    assert half_up(kzt / Fraction("3.36")) == 59_524  # 59,523.81
    assert 59_524 - 58_824 == 700
    assert min(4_900_000, 5_000_000) - 4_000_000 == 900_000  # the recorded translation, under-applied
    assert 2 * 29_412 == 58_824 and 4 * 30_000 == 120_000  # invoice totals from their lines


@pytest.mark.parametrize("name", list(EXPECTED))
def test_truth_is_the_hand_worked_answer(name: str, source) -> None:
    loaded = source.load(name)
    ledger = loaded.public.tables["ledger"]

    def resolve(item: Any) -> str:
        if isinstance(item, str):
            return item
        (row,) = [row for row in ledger if item(row)]
        return row["row_id"]

    expected = sorted(
        (kind, sorted(affected), amount, currency, sorted(resolve(item) for item in evidence))
        for kind, affected, amount, currency, evidence in EXPECTED[name]
    )
    actual = sorted(
        (issue.type, sorted(issue.affected_ids), issue.expected_amount_minor, issue.currency,
         sorted(issue.acceptable_evidence_sets[0]))
        for issue in loaded.truth
    )  # fmt: skip
    assert actual == expected
    assert all(len(issue.acceptable_evidence_sets) == 1 for issue in loaded.truth)


def test_the_fixture_names_cover_every_family_and_two_interactions() -> None:
    assert set(EXPECTED) == set(shipped.FIXTURES)
    single = {kind for name, issues in EXPECTED.items() if "_x_" not in name for kind, *_ in issues}
    assert single == set(families.FAMILIES)
    crossed = [{kind for kind, *_ in issues} for name, issues in EXPECTED.items() if "_x_" in name]
    assert crossed == [{"payment_allocation", "fx_mismatch"}, {"duplicate_invoice", "cutoff"}]


def test_the_clean_fixture_holds_every_look_alike(source) -> None:
    """Each error family has a valid twin in the clean company that shares its surface feature."""
    public = source.load("fixture_clean").public
    indexed = families.index(public)
    invoices, payments, ledger = public.tables["invoices"], public.tables["payments"], public.tables["ledger"]
    weekly = [i for i in invoices if i["entity_id"] == "E3" and i["total_minor"] == 80_000]
    assert len(weekly) == 3 and len({i["issued_at"] for i in weekly}) == 3  # same customer, lines and total
    assert sum(1 for p in payments if p["invoice_refs"] == ["I02"]) == 2  # a split payment
    parked = [r for r in ledger if r["account"] == "unapplied_receipts" and r["payment_id"] == "P27"]
    assert sorted((r["debit_minor"], r["credit_minor"]) for r in parked) == [
        (0, 30_000),
        (30_000, 0),
    ]  # overpaid, refunded
    late = next(i for i in invoices if i["invoice_id"] == "I30")
    assert (
        late["issued_at"][:10] == "2026-11-01" and indexed.side(late["issued_at"]) == "in"
    )  # printed November, local October
    receipt = next(p for p in payments if p["payment_id"] == "P31")
    assert receipt["timestamp"][:10] == "2026-10-20" and indexed.local_date(receipt["timestamp"]) == "2026-10-21"
    assert (
        indexed.required_translation(next(p for p in payments if p["payment_id"] == "P40")) == 58_824
    )  # divided and rounded
    assert indexed.side(next(i for i in invoices if i["invoice_id"] == "I19")["issued_at"]) == "after"
    assert sum(1 for r in ledger if r["invoice_id"] is None and r["payment_id"] is None) == 4  # other journal entries
    assert families.detect(public) == []


@pytest.mark.parametrize("name", list(EXPECTED))
def test_undoing_the_provenance_gives_the_clean_books(name: str) -> None:
    """B1: the recorded changes, reversed, turn the faulty books back into the clean company's."""
    public, _, provenance = shipped.build(name)
    clean, _, _ = shipped.build("fixture_clean")
    restored = books.undo(public.tables, provenance["injections"])
    assert restored["ledger"] == sorted(map(dict, clean.tables["ledger"]), key=lambda r: r["row_id"])
    assert restored["invoices"] == sorted(map(dict, clean.tables["invoices"]), key=lambda r: r["invoice_id"])
    for injection in provenance["injections"]:  # before and after values, and what the error should cause
        assert injection["changes"] and {"type", "affected_ids", "amount_minor", "currency"} == set(
            injection["expected"]
        )
        assert all(change["before"] != change["after"] for change in injection["changes"] if change["op"] == "update")


def test_an_fx_error_alone_is_one_issue_not_two(source) -> None:
    """PC-33: allocation is measured against the recorded translation, so the wrong rate is not counted again."""
    loaded = source.load("fixture_fx")
    assert [issue.type for issue in loaded.truth] == ["fx_mismatch", "fx_mismatch"]
    ledger = loaded.public.tables["ledger"]
    (applied,) = [r for r in ledger if allocation_row("I08", "P31")(r)]
    assert applied["credit_minor"] == 4_900_000  # the whole recorded amount was applied: 100,000 of I08 stays open
    over = [r for r in ledger if r["account"] == "unapplied_receipts" and r["payment_id"] == "P40"]
    assert [r["credit_minor"] for r in over] == [700]  # translated too high: the excess is unapplied credit


# ----------------------------------------------------------------- the attack matrix, per family


def _attacks(finding: dict[str, Any], other_doc: str) -> dict[str, tuple[list[dict[str, Any]], int]]:
    """name -> (what is submitted in place of the correct finding, true positives it should earn)."""
    wrong_currency = "USD" if finding["currency"] != "USD" else "KZT"
    wrong_type = "cutoff" if finding["type"] != "cutoff" else "duplicate_invoice"
    attacks: dict[str, tuple[list[dict[str, Any]], int]] = {
        "exact": ([finding], 1),
        "extra_real_record_cited": ([{**finding, "evidence_ids": [*finding["evidence_ids"], other_doc]}], 1),
        "persuasive_prose_changes_nothing": ([{**finding, "explanation": "Certain. Verified twice. Trust this."}], 1),
        "wrong_currency": ([{**finding, "currency": wrong_currency}], 0),
        "wrong_type": ([{**finding, "type": wrong_type}], 0),
        "amount_one_too_high": ([{**finding, "claimed_amount_minor": finding["claimed_amount_minor"] + 1}], 0),
        "amount_one_too_low": ([{**finding, "claimed_amount_minor": finding["claimed_amount_minor"] - 1}], 0),
        "negative_amount": ([{**finding, "claimed_amount_minor": -finding["claimed_amount_minor"]}], 0),
        "invented_evidence_id": ([{**finding, "evidence_ids": [*finding["evidence_ids"], "L-NO-SUCH-ROW"]}], 0),
        "no_evidence": ([{**finding, "evidence_ids": []}], 0),
        "one_more_affected_id": ([{**finding, "affected_ids": [*finding["affected_ids"], other_doc]}], 0),
        "submitted_twice": ([finding, dict(finding)], 1),
    }
    for position, missing in enumerate(finding["evidence_ids"]):
        rest = [evidence for evidence in finding["evidence_ids"] if evidence != missing]
        attacks[f"evidence_item_{position}_missing"] = ([{**finding, "evidence_ids": rest}], 0)
    if len(finding["affected_ids"]) > 1:
        attacks["one_affected_id_missing"] = ([{**finding, "affected_ids": finding["affected_ids"][:1]}], 0)
    return attacks


FAULTY_FIXTURES = [name for name, issues in EXPECTED.items() if issues]


@pytest.mark.parametrize("name", FAULTY_FIXTURES)
def test_attack_matrix_on_every_fixture_issue(name: str, env: AuditEnv, source) -> None:
    """C8: each condition of a true positive is necessary, for every family and both interactions."""
    loaded = source.load(name)
    correct = oracle_findings(loaded)
    other_doc = next(i["doc_id"] for i in loaded.public.tables["invoices"] if i["invoice_id"] == "I21")
    for target, finding in enumerate(correct):
        others = correct[:target] + correct[target + 1 :]
        for attack, (replacement, earned) in _attacks(finding, other_doc).items():
            env.reset(config={"episode": name})
            document = {"episode_id": loaded.public.manifest["episode_id"], "findings": [*others, *replacement]}
            env.step({"action": "submit", "args": {"findings": document}})
            counts = env.evaluator_report()["counts"]
            expected = {"tp": len(others) + earned, "fp": len(replacement) - earned, "fn": 1 - earned}
            assert counts == expected, (name, finding["type"], attack)


@pytest.mark.parametrize("name", FAULTY_FIXTURES)
def test_reward_behaviours_hold_on_every_fixture(name: str, env: AuditEnv, source) -> None:
    """The behaviours the draft asks for, per family: supported findings beat silence, and order cannot matter."""
    loaded = source.load(name)
    correct = oracle_findings(loaded)
    episode_id = loaded.public.manifest["episode_id"]

    def reward(findings: list[dict[str, Any]]) -> float:
        env.reset(config={"episode": name})
        return env.step({"action": "submit", "args": {"findings": {"episode_id": episode_id, "findings": findings}}})[1]

    assert reward(correct) == 1.0 and reward([]) == -1.0
    assert reward(list(reversed(correct))) == 1.0
    assert (
        -1.0 < reward([*correct, {**correct[0], "claimed_amount_minor": 1}]) < 1.0
    )  # one false alarm costs, not kills
    assert reward([{**finding, "evidence_ids": finding["evidence_ids"][:1]} for finding in correct]) == -1.0


def test_abstaining_on_the_clean_fixture_beats_any_accusation(env: AuditEnv, source) -> None:
    clean = source.load("fixture_clean").public.manifest["episode_id"]
    accusation = oracle_findings(source.load("fixture_cutoff"))  # a true finding of another variant of this company
    env.reset(config={"episode": "fixture_clean"})
    assert env.step({"action": "submit", "args": {"findings": {"episode_id": clean, "findings": []}}})[1] == 1.0
    env.reset(config={"episode": "fixture_clean"})
    assert (
        env.step({"action": "submit", "args": {"findings": {"episode_id": clean, "findings": accusation}}})[1] == -1.0
    )
