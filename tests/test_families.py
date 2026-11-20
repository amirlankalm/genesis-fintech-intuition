"""The four published rules: edge cases, the posting structure they rely on, and the attack matrix at scale."""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Callable
from typing import Any

import pytest

from genesis_audit import books, evaluate, families, money, shipped
from genesis_audit.env import AuditEnv
from genesis_audit.errors import EpisodeError
from genesis_audit.oracle import oracle_findings
from genesis_audit.store import PublicEpisode

Rows = list[dict[str, Any]]


def fixture(name: str = "fixture_clean") -> PublicEpisode:
    return shipped.build(name)[0]


def with_ledger(public: PublicEpisode, change: Callable[[Rows], Rows | None]) -> PublicEpisode:
    rows = [dict(row) for row in public.tables["ledger"]]
    rows = change(rows) or rows
    return dataclasses.replace(public, tables={**public.tables, "ledger": tuple(rows)})


def row_of(rows: Rows, account: str, **where: Any) -> dict[str, Any]:
    (found,) = [r for r in rows if r["account"] == account and all(r[k] == v for k, v in where.items())]
    return found


def world(**changes: Any) -> dict[str, Any]:
    return {**copy.deepcopy(dict(shipped.FIXTURE_WORLD)), **changes}


# ------------------------------------------------------------- posting structure (PC-29) can fail


def _post_twice(rows: Rows) -> None:
    rows += [{**r, "row_id": r["row_id"] + "x"} for r in rows if r["invoice_id"] == "I21" and r["payment_id"] is None]


def _wrong_total(rows: Rows) -> None:
    row_of(rows, "revenue", invoice_id="I21")["credit_minor"] += 1


def _rows_apart(rows: Rows) -> None:
    row_of(rows, "revenue", invoice_id="I21")["timestamp"] = "2026-10-05T10:21:00+05:00"


def _bank_differs(rows: Rows) -> None:
    row_of(rows, "bank", payment_id="P14", credit_minor=0)["debit_minor"] -= 1


def _translation_missing(rows: Rows) -> Rows:
    return [r for r in rows if not (r["account"] == "fx_clearing" and r["payment_id"] == "P31" and r["debit_minor"])]


def _needless_translation(rows: Rows) -> None:
    base = row_of(rows, "bank", payment_id="P14", credit_minor=0)
    rows.append({**base, "row_id": "Lx1", "account": "fx_clearing", "debit_minor": 0, "credit_minor": 300000})
    rows.append({**base, "row_id": "Lx2", "account": "fx_clearing"})


def _settlement_short(rows: Rows) -> None:
    row_of(rows, "accounts_receivable", invoice_id="I21", payment_id="P14")["credit_minor"] -= 1


def _refund_too_large(rows: Rows) -> None:
    for row in rows:
        if row["payment_id"] == "P27" and (row["account"], row["credit_minor"]) != ("unapplied_receipts", 30000):
            if row["debit_minor"] == 30000 or (row["account"] == "bank" and row["credit_minor"] == 30000):
                key = "debit_minor" if row["debit_minor"] else "credit_minor"
                row[key] = 30001


def _refund_rows_disagree(rows: Rows) -> None:
    row_of(rows, "bank", payment_id="P27", debit_minor=0)["credit_minor"] = 29999


def _foreign_account(rows: Rows) -> None:
    row_of(rows, "rent_expense")["payment_id"] = "P14"


def _unreferenced_invoice(rows: Rows) -> None:
    row_of(rows, "accounts_receivable", invoice_id="I21", payment_id="P14")["invoice_id"] = "I17"


STRUCTURE_FAULTS = [
    (_post_twice, "must be posted once"),
    (_wrong_total, "posting differs from the invoice total"),
    (_rows_apart, "posting rows differ in time"),
    (_bank_differs, "needs one bank debit for the document amount"),
    (_translation_missing, "fx_clearing debit"),
    (_needless_translation, "a same-currency receipt has no fx_clearing rows"),
    (_settlement_short, "allocations plus unapplied differ from the receipt"),
    (_refund_too_large, "refund exceeds the unapplied credit"),
    (_refund_rows_disagree, "refund rows do not agree"),
    (_foreign_account, "a row on an account receipts do not use"),
    (_unreferenced_invoice, "receivable credits must name its referenced invoices"),
]


@pytest.mark.parametrize(("change", "message"), STRUCTURE_FAULTS, ids=[fault.__name__ for fault, _ in STRUCTURE_FAULTS])
def test_broken_posting_structure_is_refused_not_labelled(change: Callable[[Rows], Rows | None], message: str) -> None:
    """B2: the declared identities are checked in code and each check can fail."""
    clean = fixture()
    families.validate_books(clean)  # holds on the clean books...
    for name in shipped.FIXTURES:  # ...and after every injected error
        families.validate_books(fixture(name))
    with pytest.raises(EpisodeError, match=message):
        families.validate_books(with_ledger(clean, change))
    with pytest.raises(EpisodeError, match=message):
        families.detect(with_ledger(clean, change))  # truth is never computed from books that break the structure


def test_an_episode_that_needs_an_unpublished_fact_is_refused() -> None:
    """B3: no issue may depend on something the tools cannot return."""
    clean = fixture()
    no_rate = dataclasses.replace(clean, tables={**clean.tables, "fx": tuple(
        row for row in clean.tables["fx"] if row["date"] != "2026-10-21")})  # fmt: skip
    with pytest.raises(EpisodeError, match="0 published rates"):
        families.validate_books(no_rate)
    both_ways = {"date": "2026-10-22", "source_currency": "KZT", "target_currency": "USD", "rate": "0.002"}
    with pytest.raises(EpisodeError, match="both directions"):
        families.validate_books(
            dataclasses.replace(clean, tables={**clean.tables, "fx": (*clean.tables["fx"], both_ways)})
        )
    tight = {**clean.manifest, "limits": {**clean.manifest["limits"], "max_steps": 4}}
    with pytest.raises(EpisodeError, match="no room left to submit"):  # four tables, four pages, and then the submit
        families.validate_books(dataclasses.replace(clean, manifest=tight))
    assert families.scan_steps(clean) == 4


def test_cases_outside_the_conventions_are_refused() -> None:
    def over_allocate(rows: Rows) -> Rows:
        row_of(rows, "accounts_receivable", invoice_id="I30", payment_id="P27")["credit_minor"] = 230000
        return [r for r in rows if not (r["payment_id"] == "P27" and r["account"] == "unapplied_receipts")
                and not (r["payment_id"] == "P27" and r["account"] == "bank" and r["credit_minor"])]  # fmt: skip

    with pytest.raises(EpisodeError, match="over-allocation"):
        families.detect(with_ledger(fixture(), over_allocate))
    mixed = world()
    mixed["payments"][0]["invoice_refs"] = ["I21", "I24"]  # a KZT and a JPY invoice on one receipt
    with pytest.raises(EpisodeError, match="different currencies"):
        books.build(mixed, [])
    neither_base = world()
    neither_base["payments"][-1]["currency"] = "USD"  # a USD receipt for the JPY invoice: no base currency in the pair
    with pytest.raises(EpisodeError, match="no single published rate"):
        books.build(neither_base, [])
    unknown = dataclasses.replace(fixture(), manifest={**fixture().manifest, "issue_types": ["made_up_family"]})
    with pytest.raises(EpisodeError, match="a case episode declares exactly"):
        families.detect(unknown)
    from genesis_audit import teaching

    taught = teaching.build("teaching_b")[0]
    with pytest.raises(EpisodeError, match="no published rule"):  # a family nobody has published a rule for
        families.detect(dataclasses.replace(taught, manifest={**taught.manifest, "issue_types": ["made_up_family"]}))


# ----------------------------------------------------------------------------- rule edge cases


def _invoice(
    invoice: str, doc: str, issued: str, posted: str, due: str = "2026-11-20T12:00:00+05:00"
) -> dict[str, Any]:
    return {"key": "invoice:" + invoice, "doc_id": doc, "invoice_id": invoice, "entity_id": "E7", "issued_at": issued,
            "due_at": due, "currency": "KZT", "posted_at": posted,
            "line_items": [{"description": "Lab access pass", "quantity": 1, "unit_price_minor": 30000, "amount_minor": 30000}]}  # fmt: skip


def test_the_period_is_inclusive_at_both_ends() -> None:
    """PC-28: an instant equal to period_start or period_end is inside; one second outside is outside."""
    last, first = "2026-10-31T23:59:59+05:00", "2026-10-01T00:00:00+05:00"
    edge = world()
    edge["invoices"] += [_invoice("I90", "D90", last, last), _invoice("I91", "D91", first, first)]
    assert books.build(edge, [])[1] == ()  # posted at the boundary instant itself: inside, no issue
    late = [{"family": "cutoff", "invoice_id": "I90", "posted_at": "2026-11-01T00:00:00+05:00"},
            {"family": "cutoff", "invoice_id": "I91", "posted_at": "2026-09-30T23:59:59+05:00"}]  # fmt: skip
    truth = books.build(edge, late)[1]
    assert sorted((issue.type, sorted(issue.affected_ids)) for issue in truth) == [
        ("cutoff", ["I90"]),
        ("cutoff", ["I91"]),
    ]
    with pytest.raises(EpisodeError, match="another side"):  # a later posting on the same side is not a cutoff error
        books.build(edge, [{"family": "cutoff", "invoice_id": "I91", "posted_at": "2026-10-20T12:00:00+05:00"}])


def test_cutoff_compares_instants_not_printed_dates() -> None:
    """Printed 1 November at +09:00 is 31 October local. The same instant printed in UTC is no different."""
    public = fixture()
    indexed = families.index(public)
    assert indexed.side("2026-11-01T03:15:00+09:00") == "in" and indexed.side("2026-10-31T18:15:00+00:00") == "in"
    assert indexed.side("2026-10-31T19:00:00+00:00") == "after"  # 1 November 00:00 local
    assert indexed.local_date("2026-10-20T21:30:00+00:00") == "2026-10-21"


def test_a_duplicate_needs_all_five_fields_identical() -> None:
    near = world()
    template = next(i for i in near["invoices"] if i["invoice_id"] == "I26")
    for number, field, value in ((1, "due_at", "2026-10-22T09:00:00+05:00"), (2, "entity_id", "E9"),
                                 (3, "issued_at", "2026-10-14T09:01:00+05:00"), (4, "currency", "USD")):  # fmt: skip
        near["invoices"].append({**copy.deepcopy(template), "key": f"near:{number}", "invoice_id": f"I8{number}",
                                 "doc_id": f"D8{number}", field: value})  # fmt: skip
    lines = copy.deepcopy(template["line_items"])
    lines[0]["description"] = "Support plan week (renewal)"
    near["invoices"].append(
        {**copy.deepcopy(template), "key": "near:5", "invoice_id": "I85", "doc_id": "D85", "line_items": lines}
    )
    assert books.build(near, [])[1] == ()  # five near-copies, each differing in exactly one field: no duplicate


def test_a_duplicate_is_recognised_whatever_offset_it_is_written_at() -> None:
    copy_at_tokyo = {"invoice_id": "I33", "doc_id": "D58", "posted_at": "2026-10-14T11:05:00+05:00",
                     "issued_at": "2026-10-14T13:00:00+09:00", "due_at": "2026-10-21T13:00:00+09:00"}  # fmt: skip
    (issue,) = books.build(world(), [{"family": "duplicate_invoice", "invoice_id": "I26", "copy": copy_at_tokyo}])[1]
    assert (issue.type, sorted(issue.affected_ids), issue.expected_amount_minor) == (
        "duplicate_invoice",
        ["I26", "I33"],
        80000,
    )


def test_fx_arithmetic_is_exact_and_rounds_once() -> None:
    """B5: integer minor units, declared exponents, decimal-string rates with a direction, half-up rounding."""
    assert money.convert_minor(10_000, 2, "500.00", 2, "half_up") == 5_000_000
    assert money.convert_minor_inverse(20_000_000, 2, "3.40", 0, "half_up") == 58_824  # exponent 2 into exponent 0
    assert money.convert_minor_inverse(58_824, 0, "0.29412", 2, "half_up") == 20_000_000  # and back, another quote
    assert (
        money.convert_minor(1, 2, "0.50", 2, "half_up") == 1 and money.convert_minor(1, 2, "0.50", 2, "half_even") == 0
    )
    assert (
        money.convert_minor_inverse(1, 2, "2", 2, "half_up") == 1
        and money.convert_minor_inverse(1, 2, "2", 2, "half_even") == 0
    )
    assert (
        money.convert_minor_inverse(3, 2, "2", 2, "half_even") == 2
        and money.convert_minor_inverse(5, 3, "1", 0, "half_up") == 0
    )
    assert money.convert_minor_inverse(1_000, 3, "3.25", 2, "half_up") == 31  # KWD 1.000 at 3.25 KWD per unit
    assert (
        money.round_fraction(money.Fraction(-5, 2), "half_up") == -3
        and money.round_fraction(money.Fraction(-5, 2), "half_even") == -2
    )
    for bad in (
        (True, 2, "1", 2, "half_up"),
        (1, 2, "1", 2, "up"),
        (1, 7, "1", 2, "half_up"),
        (10**19, 2, "1", 2, "half_up"),
    ):
        with pytest.raises(ValueError):
            money.convert_minor_inverse(*bad)
    with pytest.raises(ValueError):
        money.round_fraction(money.Fraction(1, 2), "nearest")


def test_a_receipt_with_no_reference_has_nothing_to_allocate() -> None:
    loose = world()
    loose["payments"].append({"key": "payment:P77", "doc_id": "D77", "payment_id": "P77", "currency": "KZT",
                              "timestamp": "2026-10-18T12:00:00+05:00", "amount_minor": 45000, "invoice_refs": []})  # fmt: skip
    public, truth, _ = books.build(loose, [])
    parked = [r for r in public.tables["ledger"] if r["payment_id"] == "P77" and r["account"] == "unapplied_receipts"]
    assert truth == () and [r["credit_minor"] for r in parked] == [45000]


def test_open_balance_follows_what_the_policy_required() -> None:
    """After a shortfall on the first part of a split payment, the second part is still judged on its own."""
    short = [{"family": "payment_allocation", "payment_id": "P09", "invoice_id": "I02", "applied_minor": 20000}]
    public, truth, _ = books.build(world(), short)
    (issue,) = truth
    assert (sorted(issue.affected_ids), issue.expected_amount_minor) == (["I02", "P09"], 30000)
    second = row_of(list(public.tables["ledger"]), "accounts_receivable", invoice_id="I02", payment_id="P18")
    assert (
        second["credit_minor"] == 30000
    )  # the open balance was 80,000 - 50,000 required, not 80,000 - 20,000 recorded


def test_families_are_configured_one_by_one() -> None:
    """[S1] "four independently configurable error families": each has its own count, and they do not interfere."""
    config = {"invoices": 30, "ledger_rows": 300, "foreign_currencies": ["USD", "JPY"]}
    for family in families.FAMILIES:
        for count in (1, 2):
            public, truth, provenance = shipped.generate(44, config, {family: count})
            assert [issue.type for issue in truth] == [family] * count
            assert public.manifest["issue_types"] == list(families.FAMILIES)  # the manifest never says which
            assert provenance["families"] == [family] and provenance["status"] == "faulty"
    everything = {family: 1 for family in families.FAMILIES}
    assert sorted(issue.type for issue in shipped.generate(44, config, everything)[1]) == sorted(families.FAMILIES)
    scoped = dataclasses.replace(fixture("fixture_cutoff"), manifest={**fixture().manifest, "issue_types": ["cutoff"]})
    with pytest.raises(EpisodeError, match="declares exactly"):  # a manifest cannot narrow the task of a case episode
        families.detect(scoped)


def test_errors_that_change_nothing_are_refused_at_build() -> None:
    cases = [
        ({"family": "fx_mismatch", "payment_id": "P31", "rate": "500.00"}, "gives the same amount"),
        ({"family": "fx_mismatch", "payment_id": "P14", "rate": "1.00"}, "need no translation"),
        (
            {"family": "payment_allocation", "payment_id": "P14", "invoice_id": "I21", "applied_minor": 300000},
            "must apply less",
        ),
        (
            {"family": "payment_allocation", "payment_id": "P99", "invoice_id": "I21", "applied_minor": 1},
            "do not exist",
        ),
        (
            {"family": "duplicate_invoice", "invoice_id": "I99", "copy": {"invoice_id": "I98", "doc_id": "D98"}},
            "an original that exists",
        ),
        ({"family": "write_off"}, "unknown error family"),
    ]
    for error, message in cases:
        with pytest.raises(EpisodeError, match=message):
            books.build(world(), [error])
    again = {
        "family": "duplicate_invoice",
        "invoice_id": "I33",
        "copy": {"invoice_id": "I34", "doc_id": "D59", "posted_at": "2026-10-14T12:00:00+05:00"},
    }
    with pytest.raises(EpisodeError, match="not itself part of a duplicate"):
        books.build(world(), [*shipped.FIXTURES["fixture_duplicate"], again])


def test_truth_must_be_what_the_errors_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    """Truth comes from the records, and the build refuses an episode where records and errors disagree."""
    monkeypatch.setattr(books, "detect", lambda public: [])
    with pytest.raises(EpisodeError, match="the detector derived"):
        books.build(world(), shipped.FIXTURES["fixture_cutoff"])
    monkeypatch.undo()
    dirty = world()
    dirty["invoices"][5]["posted_at"] = "2026-11-01T09:00:00+05:00"  # a latent history that already breaks a rule
    with pytest.raises(EpisodeError, match="clean books already break"):
        books.build(dirty, [])


# ------------------------------------------------------------ the attack matrix on generated episodes

FAULTY_GENERATED = [name for name in evaluate.GENERATED if evaluate.EPISODES[name]["status"] != "clean"]


@pytest.mark.parametrize("name", FAULTY_GENERATED)
def test_attack_matrix_on_generated_episodes(name: str, env: AuditEnv, source) -> None:
    """C8 at scale: the same attacks, applied to every labelled issue of every generated episode at once."""
    loaded = source.load(name)
    correct = oracle_findings(loaded)
    count, episode_id = len(correct), loaded.public.manifest["episode_id"]
    declared = sorted(loaded.public.manifest["currencies"])

    def counts(findings: list[dict[str, Any]]) -> tuple[int, int, int]:
        env.reset(config={"episode": name})
        env.step({"action": "submit", "args": {"findings": {"episode_id": episode_id, "findings": findings}}})
        report = env.evaluator_report()["counts"]
        return report["tp"], report["fp"], report["fn"]

    assert counts(correct) == (count, 0, 0)
    assert counts(correct + correct) == (count, count, 0)  # repeats earn nothing and cost
    assert counts([{**f, "currency": next(c for c in declared if c != f["currency"])} for f in correct]) == (
        0,
        count,
        count,
    )
    assert counts([{**f, "claimed_amount_minor": f["claimed_amount_minor"] + 1} for f in correct]) == (0, count, count)
    assert counts([{**f, "evidence_ids": f["evidence_ids"][1:]} for f in correct]) == (0, count, count)
    assert counts([{**f, "evidence_ids": [*f["evidence_ids"], "L-INVENTED"]} for f in correct]) == (0, count, count)
    assert counts([{**f, "affected_ids": [*f["affected_ids"], "I-INVENTED"]} for f in correct]) == (0, count, count)
    kinds = {issue.type for issue in loaded.truth}
    assert kinds == set(evaluate.EPISODES[name]["families"])  # the labels on the result sheet are what truth holds
