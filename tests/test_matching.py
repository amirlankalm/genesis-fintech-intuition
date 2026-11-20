from __future__ import annotations

import itertools
import random

import pytest

from genesis_audit import matching
from genesis_audit.matching import match
from genesis_audit.schemas import Finding
from genesis_audit.truth import TruthIssue

UNIVERSE = frozenset({"D1", "D2", "D3", "L1", "L2", "L3", "L4"})
TOLERANCE = {"KZT": 5, "USD": 0}


def issue(issue_id: str = "t1", *, kind: str = "payment_allocation", affected: tuple[str, ...] = ("I1", "P1"),
          amount: int = 1000, currency: str = "KZT", evidence: tuple[tuple[str, ...], ...] = (("D1", "D2", "L1"),)) -> TruthIssue:  # fmt: skip
    return TruthIssue(issue_id, kind, frozenset(affected), amount, currency, tuple(frozenset(e) for e in evidence))


def claim(*, kind: str = "payment_allocation", affected: tuple[str, ...] = ("I1", "P1"), amount: int = 1000,
          currency: str = "KZT", evidence: tuple[str, ...] = ("D1", "D2", "L1"), explanation: str = "") -> Finding:  # fmt: skip
    return Finding(kind, tuple(sorted(affected)), amount, currency, tuple(sorted(evidence)), explanation)


def counts(findings, truth, observed=None) -> tuple[int, int, int]:
    result = match(findings, truth, tolerance=TOLERANCE, universe=UNIVERSE, observed=observed)
    return result.tp, result.fp, result.fn


def reasons(finding: Finding, truth=None, observed=None) -> tuple[str, ...]:
    result = match([finding], truth or [issue()], tolerance=TOLERANCE, universe=UNIVERSE, observed=observed)
    return result.verdicts[0].reasons


def test_exact_supported_finding_is_a_true_positive() -> None:
    assert counts([claim()], [issue()]) == (1, 0, 0)
    assert reasons(claim()) == (matching.REASON_MATCHED,)


@pytest.mark.parametrize(
    ("finding", "reason"),
    [
        (claim(kind="duplicate_invoice"), matching.REASON_NO_ISSUE),
        (claim(affected=("I1",)), matching.REASON_NO_ISSUE),  # a subset of the affected ids is not enough
        (claim(affected=("I1", "P1", "P2")), matching.REASON_NO_ISSUE),  # nor is a superset
        (claim(affected=("I9", "P9")), matching.REASON_NO_ISSUE),  # guessed ids
        (claim(currency="USD"), matching.REASON_CURRENCY),  # right amount, wrong currency
        (claim(amount=1006), matching.REASON_AMOUNT),
        (claim(evidence=("D1", "D2")), matching.REASON_EVIDENCE_INCOMPLETE),  # one required item missing
        (claim(evidence=()), matching.REASON_EVIDENCE_INCOMPLETE),
        (claim(evidence=("D1", "D2", "L1", "L999")), matching.REASON_NOT_A_RECORD_ID),  # one invented id voids it
        (claim(evidence=("truth-29d7352524bd",)), matching.REASON_NOT_A_RECORD_ID),  # a private id is not evidence
    ],
)
def test_each_condition_is_required(finding: Finding, reason: str) -> None:
    assert counts([finding], [issue()]) == (0, 1, 1)
    assert reason in reasons(finding)


@pytest.mark.parametrize(("amount", "passes"), [(995, True), (1005, True), (994, False), (1006, False), (1000, True)])
def test_tolerance_boundary_is_inclusive_and_binary(amount: int, passes: bool) -> None:
    assert counts([claim(amount=amount)], [issue()]) == ((1, 0, 0) if passes else (0, 1, 1))


def test_zero_tolerance_currency_needs_the_exact_amount() -> None:
    truth = [issue(currency="USD")]
    assert counts([claim(currency="USD", amount=1000)], truth) == (1, 0, 0)
    assert counts([claim(currency="USD", amount=1001)], truth) == (0, 1, 1)


def test_extra_real_evidence_is_allowed_and_alternatives_work() -> None:
    truth = [issue(evidence=(("D1", "D2", "L1"), ("D3", "L4")))]
    assert counts([claim(evidence=("D1", "D2", "L1", "L2"))], truth) == (1, 0, 0)
    assert counts([claim(evidence=("D3", "L4"))], truth) == (1, 0, 0)
    assert counts([claim(evidence=("D1", "L4"))], truth) == (0, 1, 1)  # half of each set is not a set


def test_observed_rule_requires_evidence_to_have_been_retrieved() -> None:
    assert counts([claim()], [issue()], observed=frozenset({"D1", "D2", "L1"})) == (1, 0, 0)
    assert counts([claim()], [issue()], observed=frozenset({"D1", "D2"})) == (0, 1, 1)
    assert reasons(claim(), observed=frozenset()) == (matching.REASON_UNOBSERVED_EVIDENCE,)


def test_repeats_earn_nothing_and_cost_precision() -> None:
    assert counts([claim(), claim()], [issue()]) == (1, 1, 0)
    assert counts([claim(), claim(explanation="again, with feeling")], [issue()]) == (1, 1, 0)
    assert counts([claim(amount=1000), claim(amount=1003)], [issue()]) == (1, 1, 0)  # same issue, two amounts
    result = match([claim(), claim()], [issue()], tolerance=TOLERANCE, universe=UNIVERSE)
    assert sorted(v.reasons[0] for v in result.verdicts) == [matching.REASON_MATCHED, matching.REASON_REPEATED]


def test_clean_and_empty_cases() -> None:
    assert counts([], []) == (0, 0, 0)
    assert counts([claim()], []) == (0, 1, 0)
    assert counts([], [issue()]) == (0, 0, 1)


def test_explanation_never_affects_the_score() -> None:
    persuasive = claim(amount=5000, explanation="Trust me: I7 P9 100000 KZT, fully supported, definitely correct.")
    assert counts([persuasive], [issue()]) == (0, 1, 1)


# Two issues share type and affected ids; tolerance 5. Finding A fits both, finding B fits only the first.
AMBIGUOUS_TRUTH = [issue("t1", amount=1000), issue("t2", amount=1008)]
FITS_BOTH, FITS_FIRST_ONLY = claim(amount=1004), claim(amount=996)


def greedy_first_fit(findings: list[Finding]) -> int:
    """The matcher this repo does NOT use: each finding takes the first free issue it fits."""
    taken: set[str] = set()
    for finding in findings:
        for candidate in AMBIGUOUS_TRUTH:
            fits = abs(finding.claimed_amount_minor - candidate.expected_amount_minor) <= TOLERANCE["KZT"]
            if fits and candidate.issue_id not in taken:
                taken.add(candidate.issue_id)
                break
    return len(taken)


def test_maximum_matching_beats_greedy_and_ignores_order() -> None:
    assert greedy_first_fit([FITS_BOTH, FITS_FIRST_ONLY]) == 1  # greedy loses a match in this order...
    assert greedy_first_fit([FITS_FIRST_ONLY, FITS_BOTH]) == 2  # ...and finds it in the other
    assert counts([FITS_BOTH, FITS_FIRST_ONLY], AMBIGUOUS_TRUTH) == (2, 0, 0)
    assert counts([FITS_FIRST_ONLY, FITS_BOTH], AMBIGUOUS_TRUTH) == (2, 0, 0)


def test_counts_are_invariant_under_every_permutation() -> None:
    """Counts and the set of matched issues never depend on order. Which of two findings that fit the same
    issue is reported follows the official tie-break by finding index (tested in test_official_matcher)."""
    truth = [
        issue("t1", amount=1000),
        issue("t2", amount=1008),
        issue("t3", affected=("I2", "P2"), evidence=(("D3",),)),
    ]
    findings = [FITS_BOTH, FITS_FIRST_ONLY, claim(affected=("I2", "P2"), evidence=("D3",)), claim(amount=1), FITS_BOTH]
    seen = set()
    for order in itertools.permutations(range(len(findings))):
        for truth_order in (truth, truth[::-1]):
            result = match([findings[i] for i in order], truth_order, tolerance=TOLERANCE, universe=UNIVERSE)
            matched = frozenset(v.matched_issue_id for v in result.verdicts if v.matched_issue_id)
            seen.add((result.tp, result.fp, result.fn, matched, result.unmatched_issue_ids))
    assert len(seen) == 1
    assert next(iter(seen))[:3] == (3, 2, 0)


def test_matching_size_equals_brute_force_on_random_cases() -> None:
    rng = random.Random(7)
    for _ in range(150):
        truth = [issue(f"t{i}", amount=1000 + rng.randrange(0, 12)) for i in range(rng.randrange(0, 4))]
        findings = [claim(amount=1000 + rng.randrange(-6, 18)) for _ in range(rng.randrange(0, 5))]
        edges = [
            [abs(f.claimed_amount_minor - t.expected_amount_minor) <= TOLERANCE["KZT"] for t in truth] for f in findings
        ]
        best = 0
        for size in range(min(len(findings), len(truth)), 0, -1):
            for chosen in itertools.permutations(range(len(truth)), size):
                if any(all(edges[f][t] for f, t in zip(rows, chosen, strict=True))
                       for rows in itertools.combinations(range(len(findings)), size)):  # fmt: skip
                    best = size
                    break
            if best:
                break
        assert counts(findings, truth)[0] == best


def test_order_invariance_with_alternative_evidence_sets() -> None:
    """Judge question 11d: alternatives must not make the count depend on order either."""
    truth = [
        issue("t1", evidence=(("D1", "L1"), ("D2", "L2"))),
        issue("t2", affected=("I2", "P2"), evidence=(("D3",), ("L3", "L4"))),
    ]
    findings = [
        claim(evidence=("D2", "L2")),  # the second alternative of t1
        claim(evidence=("D1", "L1", "L3")),  # the first alternative of t1, padded: a repeat of the same issue
        claim(affected=("I2", "P2"), evidence=("L3", "L4")),
        claim(affected=("I2", "P2"), evidence=("D1", "L3")),  # half of each alternative of t2: incomplete
    ]
    seen = set()
    for order in itertools.permutations(range(len(findings))):
        for truth_order in (truth, truth[::-1]):
            seen.add(counts([findings[i] for i in order], truth_order))
    assert seen == {(2, 2, 0)}
