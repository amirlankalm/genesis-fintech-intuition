"""Block 3 of the official checks (tests 1-20) and the matcher conventions M01-M12, as written.

Source: docs/reference/fintech-checks-2026-11-20.md, "Блок 3" and "Точные соглашения matcher".
Shared fixture: one issue A of a supported type T on one record R1, 10000 KZT minor units, one
acceptable evidence set {D1, D2}, tau 0, inspection_steps 10 unless a test says otherwise. D3 is an
existing accessible extra document. U is an id absent from the fixture's records. Truth and findings
are built with the repo's own data classes and parsers; every result goes through the verifier entry
point `scoring.score_submission` (parse, match, score).
"""

from __future__ import annotations

import itertools
import json
import logging
import random
import shutil
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from genesis_audit import matching, paths
from genesis_audit.env import AuditEnv
from genesis_audit.episodes import LoadedEpisode, load_episode_dir
from genesis_audit.errors import EpisodeError
from genesis_audit.matching import choose_pairs, match
from genesis_audit.schemas import parse_findings_document
from genesis_audit.scoring import OFFICIAL_KEYS, Verification, score_submission
from genesis_audit.store import DRAFT_LIMITS
from genesis_audit.truth import TRUTH_KEYS, TruthIssue, parse_truth

EPISODE_ID = "ep-block3"
TYPES = ("duplicate_invoice", "payment_allocation", "fx_mismatch", "cutoff")  # the four supported types
T, OTHER_T = "cutoff", "fx_mismatch"
RECORDS = ("R1", "R2", "R3", "R4", "R5")
UNIVERSE = frozenset({"D1", "D2", "D3", *RECORDS})  # every id the tools can return a record or document for
U = "U9"  # absent from the fixture: not in UNIVERSE
A = TruthIssue("A", T, frozenset({"R1"}), 10_000, "KZT", (frozenset({"D1", "D2"}),))
B = TruthIssue("B", "duplicate_invoice", frozenset({"R2", "R3"}), 5_000, "KZT", (frozenset({"D3"}),))
# The M01-M12 examples: A on {R1, R2}.
A_M = TruthIssue("A", T, frozenset({"R1", "R2"}), 10_000, "KZT", (frozenset({"D1", "D2"}),))
EPS = 1e-9
UNSET: Any = object()


def f(**overrides: Any) -> dict[str, Any]:
    """The correct finding F for A, as a findings.json item, with overrides."""
    base = {
        "type": T,
        "affected_ids": ["R1"],
        "claimed_amount_minor": 10_000,
        "currency": "KZT",
        "evidence_ids": ["D1", "D2"],
        "explanation": "R1 was booked in the wrong period.",
    }
    return {**base, **overrides}


def fm(**overrides: Any) -> dict[str, Any]:
    """The correct finding for A_M (M01-M12)."""
    return f(**{"affected_ids": ["R1", "R2"], **overrides})


def verify(
    findings: list[Any],
    truth: tuple[TruthIssue, ...] = (A,),
    *,
    steps: int = 10,
    tau: int = 0,
    document: Any = UNSET,
) -> Verification:
    doc = {"episode_id": EPISODE_ID, "findings": findings} if document is UNSET else document
    return score_submission(
        doc,
        truth,
        episode_id=EPISODE_ID,
        limits=DRAFT_LIMITS,
        tolerance={"KZT": tau, "USD": 0},
        universe=UNIVERSE,
        inspection_steps=steps,
    )


def expect(
    v: Verification, tp: int, fp: int, fn: int, p: Fraction, r: Fraction, f1: Fraction, reward: Fraction
) -> None:
    """Exact counts and exact fractions, and the float result object within 1e-9."""
    assert v.error is None and v.result is not None
    assert (v.score.tp, v.score.fp, v.score.fn) == (tp, fp, fn)
    assert v.score.reward == reward
    official = v.score.to_official()
    assert set(official) == set(OFFICIAL_KEYS)
    assert (official["tp"], official["fp"], official["fn"]) == (tp, fp, fn)
    for key, value in (("precision", p), ("recall", r), ("f1", f1), ("return", reward)):
        number = official[key]
        assert isinstance(number, float) and abs(number - float(value)) <= EPS, key
        assert abs(Fraction(number) - value) <= Fraction(EPS)


def expect_miss(v: Verification) -> None:
    """TP=0, FP=1, FN=1: F1=0, reward -1."""
    expect(v, 0, 1, 1, Fraction(0), Fraction(0), Fraction(0), Fraction(-1))


def expect_structural(v: Verification) -> None:
    assert v.result is None and v.error
    assert v.score.malformed and v.score.reward == -1
    assert v.score.to_official() == {**dict.fromkeys(OFFICIAL_KEYS[:-1]), "return": -1.0}


ONE, ZERO = Fraction(1), Fraction(0)

# ----------------------------------------------------------------------------- Block 3: tests 1-20


def test_t01_one_correct_finding() -> None:
    expect(verify([f()]), 1, 0, 0, ONE, ONE, ONE, Fraction(98, 100))


def test_t02_empty_findings_with_one_issue() -> None:
    expect(verify([]), 0, 0, 1, ZERO, ZERO, ZERO, Fraction(-1))


def test_t03_empty_truth_and_empty_findings() -> None:
    expect(verify([], ()), 0, 0, 0, ZERO, ZERO, ONE, Fraction(98, 100))


def test_t04_empty_truth_one_false_finding() -> None:
    expect(verify([f()], ()), 0, 1, 0, ZERO, ZERO, ZERO, Fraction(-1))


def test_t05_two_identical_correct_findings() -> None:
    v = verify([f(), f()])
    expect(v, 1, 1, 0, Fraction(1, 2), ONE, Fraction(2, 3), Fraction(47, 150))
    assert v.score.reward <= verify([f()]).score.reward  # not above test 1
    assert v.result is not None and v.result.pairs == (("A", 0),)


def test_t06_wrong_supported_type() -> None:
    expect_miss(verify([f(type=OTHER_T)]))


def test_t07_another_existing_unaffected_record() -> None:
    expect_miss(verify([f(affected_ids=["R2"])]))


def test_t08_amount_off_by_one_at_tau_zero() -> None:
    expect_miss(verify([f(claimed_amount_minor=10_001)]))


def test_t09_other_currency() -> None:
    expect_miss(verify([f(currency="USD")]))


def test_t10_only_part_of_the_evidence_set() -> None:
    expect_miss(verify([f(evidence_ids=["D1"])]))


@pytest.mark.parametrize("absent", [U, "U-404", "UNKNOWN 1", "Ж404", "x" * 300, "D1/../x", "../truth.json", "", "D2 "])
def test_t11_absent_evidence_id_instead_of_d2_is_fp_whatever_its_shape(absent: str) -> None:
    assert absent not in UNIVERSE
    v = verify([f(evidence_ids=["D1", absent])])
    expect_miss(v)
    assert v.result is not None and v.result.verdicts[0].reasons == (matching.REASON_NOT_A_RECORD_ID,)


def test_t12_mass_flagging_five_records_times_four_types() -> None:
    findings = [f(type=kind, affected_ids=[record]) for record in RECORDS for kind in TYPES]
    assert len(findings) == 20
    expect(verify(findings), 1, 19, 0, Fraction(1, 20), ONE, Fraction(2, 21), Fraction(-871, 1050))


def test_t13_two_issues_only_a_found() -> None:
    expect(verify([f()], (A, B)), 1, 0, 1, ONE, Fraction(1, 2), Fraction(2, 3), Fraction(47, 150))


def test_t14_two_issues_a_found_plus_one_false() -> None:
    half = Fraction(1, 2)
    expect(verify([f(), f(affected_ids=["R4"])], (A, B)), 1, 1, 1, half, half, half, Fraction(-2, 100))


def test_t15_zero_inspection_steps() -> None:
    expect(verify([f()], steps=0), 1, 0, 0, ONE, ONE, ONE, ONE)


def test_t16_fifty_inspection_steps() -> None:
    v = verify([f()], steps=50)
    expect(v, 1, 0, 0, ONE, ONE, ONE, Fraction(90, 100))
    assert verify([f()]).score.reward - v.score.reward == Fraction(8, 100)


def test_t17_hundred_inspection_steps() -> None:
    expect(verify([f()], steps=100), 1, 0, 0, ONE, ONE, ONE, Fraction(80, 100))


def test_t18_thirty_one_findings_is_structural() -> None:
    expect_structural(verify([f()] * 31))
    assert verify([f()] * 30).error is None  # the limit itself is accepted


def test_t19_eleven_distinct_evidence_ids_is_structural() -> None:
    expect_structural(verify([f(evidence_ids=["D1", "D2", "D3", *RECORDS, "X1", "X2", "X3"])]))
    assert verify([f(evidence_ids=["D1", "D2", "D3", *RECORDS, "X1", "X2"])]).error is None


def test_t20_explanation_of_1001_ascii_characters_is_structural() -> None:
    expect_structural(verify([f(explanation="a" * 1001)]))
    expect(verify([f(explanation="a" * 1000)]), 1, 0, 0, ONE, ONE, ONE, Fraction(98, 100))


# ----------------------------------------------------------------------------- M01-M12


def test_m01_duplicate_affected_ids_are_a_set() -> None:
    expect(verify([fm(affected_ids=["R2", "R1", "R1"])], (A_M,)), 1, 0, 0, ONE, ONE, ONE, Fraction(98, 100))


def test_m02_extra_existing_unaffected_record() -> None:
    expect_miss(verify([fm(affected_ids=["R1", "R2", "R3"])], (A_M,)))


def test_m03_extra_existing_accessible_evidence() -> None:
    expect(verify([fm(evidence_ids=["D2", "D1", "D3"])], (A_M,)), 1, 0, 0, ONE, ONE, ONE, Fraction(98, 100))


def test_m04_absent_evidence_voids_the_finding() -> None:
    expect_miss(verify([fm(evidence_ids=["D1", "D2", U])], (A_M,)))


def test_m05_evidence_cap_is_checked_before_dedup() -> None:
    expect_structural(verify([fm(evidence_ids=["D1"] * 10 + ["D2"] * 1 + ["D1"])], (A_M,)))
    expect_structural(verify([fm(evidence_ids=["D1"] * 11)], (A_M,)))
    expect(verify([fm(evidence_ids=["D1"] * 9 + ["D2"])], (A_M,)), 1, 0, 0, ONE, ONE, ONE, Fraction(98, 100))


@pytest.mark.parametrize("currency", ["kzt", "Kzt", "KZT ", " KZT", "KZT\n", "KZTT", ""])
def test_m06_currency_differing_by_case_or_space_is_fp(currency: str) -> None:
    expect_miss(verify([fm(currency=currency)], (A_M,)))


def test_m07_amount_off_by_one_at_tau_zero() -> None:
    expect_miss(verify([fm(claimed_amount_minor=10_001)], (A_M,)))


@pytest.mark.parametrize(
    ("amount", "hit"), [(10_001, True), (9_999, True), (10_000, True), (10_002, False), (9_998, False)]
)
def test_m08_declared_tau_one_is_inclusive(amount: int, hit: bool) -> None:
    v = verify([fm(claimed_amount_minor=amount)], (A_M,), tau=1)
    if hit:
        expect(v, 1, 0, 0, ONE, ONE, ONE, Fraction(98, 100))
    else:
        expect_miss(v)


@pytest.mark.parametrize("amount", ["10000", True, False, 10_000.0, None, [10_000], {"minor": 10_000}])
def test_m09_amount_that_is_not_a_json_integer_is_structural(amount: object) -> None:
    expect_structural(verify([fm(claimed_amount_minor=amount)], (A_M,)))


# M10/M11 define the edge graph separately. As a matcher input: two issues with the same type, affected set,
# currency and amount, told apart only by their evidence sets. validate_truth refuses such a truth for an
# episode (no finding could tell them apart), so the graph is exercised through match() and choose_pairs().
A_TIE = TruthIssue("A", T, frozenset({"R1"}), 10_000, "KZT", (frozenset({"D1", "D2"}),))
B_TIE = TruthIssue("B", T, frozenset({"R1"}), 10_000, "KZT", (frozenset({"D1", "D3"}),))
FITS_BOTH, FITS_A_ONLY = f(evidence_ids=["D1", "D2", "D3"]), f(evidence_ids=["D1", "D2"])


def test_m10_maximum_matching_not_greedy_edge_graph() -> None:
    assert choose_pairs([("A", 0), ("B", 0), ("A", 1)]) == (("A", 1), ("B", 0))


def test_m10_maximum_matching_not_greedy_through_the_matcher() -> None:
    v = verify([FITS_BOTH, FITS_A_ONLY], (A_TIE, B_TIE))
    expect(v, 2, 0, 0, ONE, ONE, ONE, Fraction(98, 100))
    assert v.result is not None and v.result.pairs == (("A", 1), ("B", 0))


def test_m11_tie_break_edge_graph() -> None:
    assert choose_pairs([("A", 0), ("A", 1), ("B", 0), ("B", 1)]) == (("A", 0), ("B", 1))
    assert choose_pairs([("B", 1), ("B", 0), ("A", 1), ("A", 0)]) == (("A", 0), ("B", 1))  # edge order is irrelevant


def test_m11_tie_break_through_the_matcher() -> None:
    for truth in ((A_TIE, B_TIE), (B_TIE, A_TIE)):
        v = verify([FITS_BOTH, FITS_BOTH], truth)
        expect(v, 2, 0, 0, ONE, ONE, ONE, Fraction(98, 100))
        assert v.result is not None and v.result.pairs == (("A", 0), ("B", 1))
        assert [verdict.matched_issue_id for verdict in v.result.verdicts] == ["A", "B"]


def test_m11_permutation_changes_neither_counts_nor_reward_and_pairs_follow_the_rule() -> None:
    findings = [FITS_BOTH, FITS_BOTH, FITS_A_ONLY, f(claimed_amount_minor=1), f(evidence_ids=["D1", "D3"])]
    outcomes = set()
    for order in itertools.permutations(range(len(findings))):
        permuted = [findings[i] for i in order]
        v = verify(permuted, (A_TIE, B_TIE))
        assert v.result is not None
        outcomes.add((v.score.tp, v.score.fp, v.score.fn, v.score.reward))
        assert v.result.pairs == reference_pairs(edges_of(permuted, (A_TIE, B_TIE)))
    assert outcomes == {(2, 3, 0, Fraction(2 * 4, 4 + 3) - 1 - Fraction(2, 100))}


def test_m12_two_identical_correct_findings_are_not_merged() -> None:
    v = verify([fm(), fm()], (A_M,))
    expect(v, 1, 1, 0, Fraction(1, 2), ONE, Fraction(2, 3), Fraction(47, 150))
    assert v.score.reward == verify([f(), f()]).score.reward  # the reward vector of test 5
    assert v.result is not None and v.result.pairs == (("A", 0),)
    assert v.result.verdicts[1].reasons == (matching.REASON_REPEATED,)


def test_m12_first_index_wins_among_correct_findings_that_differ_in_extra_evidence() -> None:
    v = verify([fm(evidence_ids=["D1", "D2", "D3"]), fm()], (A_M,))
    assert v.result is not None and v.result.pairs == (("A", 0),)


# ----------------------------------------------------------------------------- tie-break against brute force


def edges_of(findings: list[dict[str, Any]], truth: tuple[TruthIssue, ...]) -> list[tuple[str, int]]:
    """The edge graph, from single (finding, issue) pairs: an edge exists iff that pair alone is a TP."""
    return [
        (issue.issue_id, j) for j, item in enumerate(findings) for issue in truth if verify([item], (issue,)).score.tp
    ]


def reference_pairs(edges: list[tuple[str, int]]) -> tuple[tuple[str, int], ...]:
    """The official rule by enumeration: max cardinality, then the smallest sorted pair sequence."""
    best: tuple[tuple[str, int], ...] | None = None
    edge_list = sorted(set(edges))
    for size in range(len(edge_list), -1, -1):
        for subset in itertools.combinations(edge_list, size):
            issues, findings = [e[0] for e in subset], [e[1] for e in subset]
            if len(set(issues)) == size == len(set(findings)):
                candidate = tuple(sorted(subset))
                best = candidate if best is None or candidate < best else best
        if best is not None:
            return best
    return ()


def test_choose_pairs_equals_the_official_rule_on_random_graphs() -> None:
    rng = random.Random(20261120)
    names = ["A", "B", "a", "Ä", "B2", "10", "9"]  # code-point order: "10" < "9" < "A" < "B" < "B2" < "a" < "Ä"
    for _ in range(400):
        issues = rng.sample(names, rng.randrange(0, 5))
        findings = range(rng.randrange(0, 5))
        edges = [(i, j) for i in issues for j in findings if rng.random() < 0.45]
        assert choose_pairs(edges) == reference_pairs(edges), edges


# ----------------------------------------------------------------------------- conventions


WELL_TYPED_BUT_WRONG = [
    {"type": "unknown_type"}, {"type": "Cutoff"}, {"type": "cut off"}, {"type": ""}, {"type": "c" * 500},
    {"currency": "kzt"}, {"currency": "XYZ"}, {"currency": "₸"},
    {"affected_ids": []}, {"affected_ids": [f"R{n}" for n in range(1, 22)]}, {"affected_ids": ["R1 "]},
    {"affected_ids": ["r1"]}, {"affected_ids": ["Р1"]}, {"affected_ids": ["x" * 300]},
    {"claimed_amount_minor": 2**53}, {"claimed_amount_minor": -10_000}, {"claimed_amount_minor": 10**40},
    {"claimed_amount_minor": 0}, {"evidence_ids": []}, {"evidence_ids": ["D1", "D2", "Д3"]},
]  # fmt: skip


@pytest.mark.parametrize("change", WELL_TYPED_BUT_WRONG)
def test_conv_structurally_valid_wrong_values_are_fp_not_structural(change: dict[str, Any]) -> None:
    expect_miss(verify([f(**change)]))


def without(key: str) -> dict[str, Any]:
    return {k: v for k, v in f().items() if k != key}


STRUCTURAL = [
    *([without(key)] for key in ("type", "affected_ids", "claimed_amount_minor", "currency", "evidence_ids", "explanation")),
    [f(type=3)], [f(type=None)], [f(currency=398)], [f(currency=["KZT"])],
    [f(explanation=None)], [f(explanation=7)],
    [f(affected_ids="R1")], [f(affected_ids=["R1", 5])], [f(affected_ids=[["R1"]])], [f(affected_ids=None)],
    [f(evidence_ids="D1")], [f(evidence_ids=[1])], [f(evidence_ids=None)],
    ["not an object"], [None], [[]],
]  # fmt: skip


@pytest.mark.parametrize("findings", STRUCTURAL)
def test_conv_wrong_json_type_or_missing_key_is_structural(findings: list[Any]) -> None:
    expect_structural(verify(findings))


def test_conv_one_bad_finding_makes_the_whole_submit_structural() -> None:
    expect_structural(verify([f(), f(claimed_amount_minor=True)]))


@pytest.mark.parametrize(
    "document",
    [[], "findings", None, {}, {"episode_id": EPISODE_ID}, {"episode_id": EPISODE_ID, "findings": {}},
     {"episode_id": EPISODE_ID, "findings": None}, {"episode_id": "ep-other", "findings": []},
     {"episode_id": 5, "findings": []}, {"episode_id": None, "findings": []}, {"episode_id": "", "findings": []}],
)  # fmt: skip
def test_conv_findings_document_structure(document: object) -> None:
    expect_structural(verify([], document=document))


def test_conv_episode_id_may_be_omitted_and_unknown_keys_are_ignored() -> None:
    expect(verify([], document={"findings": [f()]}), 1, 0, 0, ONE, ONE, ONE, Fraction(98, 100))
    document = {"episode_id": EPISODE_ID, "version": 2, "findings": [{**f(), "confidence": 0.9, "issue_id": "A"}]}
    expect(verify([], document=document), 1, 0, 0, ONE, ONE, ONE, Fraction(98, 100))


def test_conv_explanation_length_is_unicode_code_points() -> None:
    for text in ("😀" * 1000, "é" * 500, "Ж" * 1000):
        assert len(text) == 1000
        expect(verify([f(explanation=text)]), 1, 0, 0, ONE, ONE, ONE, Fraction(98, 100))
    for text in ("😀" * 1001, "é" * 500 + "x", "Ж" * 1001):
        expect_structural(verify([f(explanation=text)]))


def test_conv_bool_is_never_an_amount() -> None:
    expect_structural(verify([f(claimed_amount_minor=True)]))
    expect_structural(verify([f(claimed_amount_minor=False)]))


def test_conv_unknown_type_is_fp_with_reason() -> None:
    v = verify([f(type="totally_new_scenario")])
    expect_miss(v)
    assert v.result is not None and v.result.verdicts[0].reasons == (matching.REASON_NO_ISSUE,)


def test_conv_currency_is_compared_exactly() -> None:
    v = verify([f(currency="kzt")])
    expect_miss(v)
    assert v.result is not None and v.result.verdicts[0].reasons == (matching.REASON_CURRENCY,)


def test_conv_ids_are_exact_strings_in_any_shape() -> None:
    odd = "Счёт № 7 / 2026 ✓"
    truth = (TruthIssue("Z", T, frozenset({odd}), 10_000, "KZT", (frozenset({"D1", "d 2"}),)),)
    universe = UNIVERSE | {"d 2"}
    finding = f(affected_ids=[odd], evidence_ids=["d 2", "D1"])
    findings = parse_findings_document({"findings": [finding]}, EPISODE_ID, DRAFT_LIMITS)
    result = match(findings, truth, tolerance={"KZT": 0}, universe=universe)
    assert (result.tp, result.fp, result.fn) == (1, 0, 0)
    near = f(affected_ids=[odd + " "], evidence_ids=["d 2", "D1"])
    findings = parse_findings_document({"findings": [near]}, EPISODE_ID, DRAFT_LIMITS)
    result = match(findings, truth, tolerance={"KZT": 0}, universe=universe)
    assert (result.tp, result.fp, result.fn) == (0, 1, 1)


def test_conv_finding_order_never_changes_counts_or_reward() -> None:
    findings = [f(), f(), f(type=OTHER_T), f(affected_ids=["R2", "R3"], type="duplicate_invoice",
                claimed_amount_minor=5_000, evidence_ids=["D3"]), f(evidence_ids=["D1", U])]  # fmt: skip
    seen = set()
    for order in itertools.permutations(range(len(findings))):
        v = verify([findings[i] for i in order], (A, B))
        seen.add((v.score.tp, v.score.fp, v.score.fn, v.score.reward))
    assert seen == {(2, 3, 0, Fraction(8, 7) - 1 - Fraction(2, 100))}


# ----------------------------------------------------------------------------- truth.json parsing

TRUTH_A = {
    "issue_id": "A",
    "type": T,
    "affected_ids": ["R1"],
    "expected_amount_minor": 10_000,
    "currency": "KZT",
    "acceptable_evidence_sets": [["D2", "D1"]],
}


def test_truth_keys_in_any_order_parse_to_the_same_issue() -> None:
    reordered = {key: TRUTH_A[key] for key in reversed(TRUTH_KEYS)}
    assert parse_truth({"issues": [reordered]}) == parse_truth({"issues": [TRUTH_A]}) == (A,)
    assert list(A.to_json()) == list(TRUTH_KEYS)


def test_truth_unknown_keys_strict_refuses_lenient_ignores(caplog: pytest.LogCaptureFixture) -> None:
    document = {"issues": [{**TRUTH_A, "note": "hand-written"}], "version": 1}
    with pytest.raises(EpisodeError, match="unknown"):
        parse_truth(document)
    with caplog.at_level(logging.WARNING, logger="genesis_audit.truth"):
        assert parse_truth(document, strict=False) == (A,)
    assert "note" in caplog.text and "version" in caplog.text


@pytest.mark.parametrize(
    "change",
    [{"issue_id": 1}, {"type": None}, {"currency": 398}, {"affected_ids": "R1"}, {"affected_ids": []},
     {"affected_ids": [1]}, {"expected_amount_minor": True}, {"expected_amount_minor": "10000"},
     {"expected_amount_minor": 1.0}, {"acceptable_evidence_sets": []}, {"acceptable_evidence_sets": [[]]},
     {"acceptable_evidence_sets": ["D1"]}],
)  # fmt: skip
def test_truth_wrong_json_types_are_refused_in_both_modes(change: dict[str, Any]) -> None:
    for strict in (True, False):
        with pytest.raises(EpisodeError):
            parse_truth({"issues": [{**TRUTH_A, **change}]}, strict=strict)


def test_truth_missing_key_and_duplicate_issue_id_are_refused() -> None:
    for strict in (True, False):
        with pytest.raises(EpisodeError, match="missing: currency"):
            parse_truth({"issues": [{k: v for k, v in TRUTH_A.items() if k != "currency"}]}, strict=strict)
        with pytest.raises(EpisodeError, match="unique"):
            parse_truth({"issues": [TRUTH_A, {**TRUTH_A, "affected_ids": ["R2"]}]}, strict=strict)


def test_truth_ids_and_codes_are_any_strings() -> None:
    raw = {**TRUTH_A, "issue_id": "issue 1", "type": "Cutoff-X", "currency": "kzt", "affected_ids": ["Р 1"]}
    (issue,) = parse_truth({"issues": [raw]})
    assert (issue.issue_id, issue.type, issue.currency, issue.affected_ids) == ("issue 1", "Cutoff-X", "kzt", {"Р 1"})


# ----------------------------------------------------------------------------- review regressions


def test_conv_tau_defaults_to_zero_for_a_currency_the_tolerance_map_does_not_declare() -> None:
    """Official "Допуск суммы": tau is 0 unless published. A truth currency missing from the map must not crash."""
    eur = (TruthIssue("A", T, frozenset({"R1"}), 10_000, "EUR", (frozenset({"D1", "D2"}),)),)
    for amount, counts in ((10_000, (1, 0, 0)), (10_001, (0, 1, 1)), (9_999, (0, 1, 1))):
        findings = parse_findings_document(
            {"findings": [f(currency="EUR", claimed_amount_minor=amount)]}, "e", DRAFT_LIMITS
        )
        result = match(findings, eur, tolerance={"KZT": 5}, universe=UNIVERSE)
        assert (result.tp, result.fp, result.fn) == counts, amount
    v = score_submission(
        {"findings": [f(currency="EUR")]}, eur, episode_id="e", limits=DRAFT_LIMITS, tolerance={},
        universe=UNIVERSE, inspection_steps=10,
    )  # fmt: skip
    expect(v, 1, 0, 0, ONE, ONE, ONE, Fraction(98, 100))


def test_m02_missing_affected_record_is_fp_too() -> None:
    """Convention 2 in the other direction: a strict subset of the canonical affected set is not a TP."""
    expect_miss(verify([fm(affected_ids=["R1"])], (A_M,)))
    expect_miss(verify([fm(affected_ids=["R2", "R2"])], (A_M,)))


def test_conv_any_one_acceptable_evidence_set_suffices() -> None:
    """Convention 3: full inclusion of at least one acceptable set; a mix of partial sets is not enough."""
    two_sets = (TruthIssue("A", T, frozenset({"R1"}), 10_000, "KZT", (frozenset({"D1", "D2"}), frozenset({"D3"}))),)
    expect(verify([f(evidence_ids=["D3"])], two_sets), 1, 0, 0, ONE, ONE, ONE, Fraction(98, 100))
    expect(verify([f(evidence_ids=["D2", "D1"])], two_sets), 1, 0, 0, ONE, ONE, ONE, Fraction(98, 100))
    expect_miss(verify([f(evidence_ids=["D1", "R1"])], two_sets))
    expect_miss(verify([f(evidence_ids=[])], two_sets))


def test_conv_explanation_takes_no_part_in_edges() -> None:
    """ "Объяснение не участвует в выборе рёбер": any explanation text, including empty or misleading, scores alike."""
    for text in ("", "wrong type, wrong amount", "x" * 1000):
        expect(verify([f(explanation=text)]), 1, 0, 0, ONE, ONE, ONE, Fraction(98, 100))
    v = verify([f(explanation="first"), f(explanation="second, more convincing")])
    assert v.result is not None and v.result.pairs == (("A", 0),)


# The episode path: the same rules through a jury-built directory loaded with strict=False and the environment.
JURY_NAME = "fixture_duplicate"  # one duplicate_invoice issue


def _jury_copy(root: Path) -> Path:
    directory = root / JURY_NAME
    directory.mkdir()
    for source in (paths.PUBLIC_ROOT, paths.PRIVATE_ROOT):
        for entry in (source / JURY_NAME).iterdir():
            shutil.copy(entry, directory / entry.name)
    return directory


@pytest.fixture(scope="module")
def jury_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _jury_copy(tmp_path_factory.mktemp("jury"))


def _finding_for(issue: TruthIssue, **overrides: Any) -> dict[str, Any]:
    base = {
        "type": issue.type, "affected_ids": sorted(issue.affected_ids), "claimed_amount_minor": issue.expected_amount_minor,
        "currency": issue.currency, "evidence_ids": sorted(min(issue.acceptable_evidence_sets, key=len)),
        "explanation": "oracle",
    }  # fmt: skip
    return {**base, **overrides}


def _run_submit(loaded: LoadedEpisode, findings: list[Any]) -> tuple[float, bool, dict[str, Any]]:
    env = AuditEnv.from_episode(loaded)
    env.reset(config={"episode": "episode", "mode": "eval"})
    document = {"episode_id": loaded.public.manifest["episode_id"], "findings": findings}
    _, reward, terminated, _, info = env.step({"action": "submit", "args": {"findings": document}})
    assert info == {}
    return reward, terminated, env.evaluator_report()


def test_t18_t19_t20_structural_limits_end_the_episode_at_minus_one_with_an_evaluator_log(jury_dir: Path) -> None:
    loaded = load_episode_dir(jury_dir, strict=False)
    (issue,) = loaded.truth
    good = _finding_for(issue)
    evidence = good["evidence_ids"]
    cases = {
        "t18": ([good] * 31, [good] * 30),
        "t19": ([_finding_for(issue, evidence_ids=[*evidence, *(f"X{n}" for n in range(11 - len(evidence)))])],
                [_finding_for(issue, evidence_ids=(evidence * 10)[:10])]),
        "t20": ([_finding_for(issue, explanation="a" * 1001)], [_finding_for(issue, explanation="a" * 1000)]),
    }  # fmt: skip
    for check, (over, at_limit) in cases.items():
        reward, terminated, report = _run_submit(loaded, over)
        assert (reward, terminated) == (0.0, True), check  # closed mode: the policy sees a numeric 0
        assert report["termination_cause"] == "malformed_submission", check
        assert report["score"]["malformed"] is True and report["score"]["reward"] == -1.0, check
        assert isinstance(report["validation_error"], str) and report["validation_error"], check
        _, _, report = _run_submit(loaded, at_limit)
        assert report["valid_submission"] is True and report["counts"]["tp"] == 1, check


def test_m10_m11_through_a_jury_built_truth(tmp_path: Path) -> None:
    """Two issues told apart only by their evidence sets: refused for our own episodes, a warning on the jury path."""
    directory = _jury_copy(tmp_path)
    (issue,) = load_episode_dir(directory, strict=False).truth
    smallest = sorted(min(issue.acceptable_evidence_sets, key=len))
    extra = sorted(load_episode_dir(directory, strict=False).public.evidence_universe() - set(smallest))[0]
    raw = issue.to_json()
    document = {"issues": [{**raw, "issue_id": "B", "acceptable_evidence_sets": [[*smallest, extra]]},
                           {**raw, "issue_id": "A", "acceptable_evidence_sets": [smallest]}]}  # fmt: skip
    (directory / "truth.json").write_text(json.dumps(document), encoding="utf-8")
    loaded = load_episode_dir(directory, strict=False)
    assert any("could not tell them apart" in warning for warning in loaded.warnings)
    with pytest.raises(EpisodeError):
        load_episode_dir(directory, strict=True)
    fits_both, fits_a = _finding_for(issue, evidence_ids=[*smallest, extra]), _finding_for(issue)
    for findings, pairs in (
        ([fits_both, fits_a], [("B", 0), ("A", 1)]),
        ([fits_both, fits_both], [("A", 0), ("B", 1)]),
    ):
        _, _, report = _run_submit(loaded, findings)
        assert report["counts"] == {"tp": 2, "fp": 0, "fn": 0}
        assert [(v["matched_issue_id"], v["index"]) for v in report["findings"]] == pairs
        v = score_submission(
            {"findings": findings}, loaded.truth, episode_id=loaded.public.manifest["episode_id"],
            limits=loaded.public.manifest["limits"], tolerance=loaded.tolerance(),
            universe=loaded.public.evidence_universe(), inspection_steps=0,
        )  # fmt: skip
        assert v.result is not None and v.score.reward == 1
        assert sorted(v.result.pairs) == sorted(pairs)
