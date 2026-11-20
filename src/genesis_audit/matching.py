"""Strict, order-invariant matching of submitted findings to truth issues.

A finding may be paired with a truth issue only if all five conditions hold:
same type, same canonical affected-id set, same currency, amount within the
declared tolerance, and evidence that is valid and covers at least one complete
acceptable evidence set. Strings (type, currency, ids) are compared exactly: no
case folding, trimming or number-to-string conversion. Every cited evidence id
must be in `universe`, the set of ids the tools can return a record or document
for; any other cited id voids the finding. There is no partial credit: an edge
exists or it does not.

True positives are the size of a *maximum* one-to-one matching, so the count
cannot depend on the order findings were submitted in. A greedy first-fit matcher
does not have that property. Among all maximum matchings the official tie-break
picks one: issue_ids sorted by Unicode code points, then the lexicographically
smallest sorted sequence of (issue_id, finding index) pairs (see choose_pairs).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass

from .schemas import Finding
from .truth import TruthIssue

EVIDENCE_RULES = ("accessible", "observed")

# Reasons recorded for the evaluator only. Never returned to a policy.
REASON_MATCHED = "matched"
REASON_REPEATED = "repeat_of_matched_issue"
REASON_NOT_A_RECORD_ID = "evidence_id_is_not_a_record_id"
REASON_UNOBSERVED_EVIDENCE = "evidence_id_not_observed_in_episode"
REASON_NO_ISSUE = "no_issue_with_this_type_and_affected_ids"
REASON_CURRENCY = "currency_mismatch"
REASON_AMOUNT = "amount_outside_tolerance"
REASON_EVIDENCE_INCOMPLETE = "evidence_set_incomplete"


@dataclass(frozen=True)
class FindingVerdict:
    index: int  # position in the submission
    matched_issue_id: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class MatchResult:
    tp: int
    fp: int
    fn: int
    verdicts: tuple[FindingVerdict, ...]
    unmatched_issue_ids: tuple[str, ...]

    @property
    def pairs(self) -> tuple[tuple[str, int], ...]:
        """The chosen matching as sorted (issue_id, finding index) pairs, for the evaluator report."""
        return tuple(sorted((v.matched_issue_id, v.index) for v in self.verdicts if v.matched_issue_id is not None))


def evidence_problem(finding: Finding, universe: frozenset[str], observed: frozenset[str] | None) -> str | None:
    """Return why the cited evidence is unusable, or None if every cited id is usable."""
    cited = set(finding.evidence_ids)
    if not cited <= universe:
        return REASON_NOT_A_RECORD_ID
    if observed is not None and not cited <= observed:
        return REASON_UNOBSERVED_EVIDENCE
    return None


def edge_reasons(finding: Finding, issue: TruthIssue, tolerance: Mapping[str, int]) -> tuple[str, ...]:
    """Reasons this finding cannot be paired with this issue. Empty means a valid edge.

    Assumes type and affected ids already agree and the cited evidence is usable. A currency
    the tolerance map does not declare is compared exactly: tau 0 is the official default.
    """
    reasons = []
    if finding.currency != issue.currency:
        reasons.append(REASON_CURRENCY)
    elif abs(finding.claimed_amount_minor - issue.expected_amount_minor) > tolerance.get(issue.currency, 0):
        reasons.append(REASON_AMOUNT)
    cited = set(finding.evidence_ids)
    if not any(required <= cited for required in issue.acceptable_evidence_sets):
        reasons.append(REASON_EVIDENCE_INCOMPLETE)
    return tuple(reasons)


def match(
    findings: Sequence[Finding],
    truth: Sequence[TruthIssue],
    *,
    tolerance: Mapping[str, int],
    universe: Collection[str],
    observed: Collection[str] | None = None,
) -> MatchResult:
    """Score a submission. `observed` is None under the 'accessible' evidence rule.

    `universe` holds every evidence id that exists and is accessible through the tools;
    ids are arbitrary strings compared exactly.
    """
    issues = sorted(truth, key=lambda issue: issue.issue_id)  # str order is Unicode code-point order
    if len({issue.issue_id for issue in issues}) != len(issues):
        raise ValueError("truth issue_ids must be unique")
    usable, seen = frozenset(universe), None if observed is None else frozenset(observed)
    edges: list[tuple[str, int]] = []
    failures: dict[int, tuple[str, ...]] = {}
    for index, finding in enumerate(findings):
        fitting, failures[index] = _finding_edges(finding, issues, tolerance, usable, seen)
        edges.extend((issue_id, index) for issue_id in fitting)

    chosen = {index: issue_id for issue_id, index in choose_pairs(edges)}
    verdicts = tuple(
        FindingVerdict(index, chosen[index], (REASON_MATCHED,))
        if index in chosen
        else FindingVerdict(index, None, failures[index])
        for index in range(len(findings))
    )
    tp = len(chosen)
    matched = set(chosen.values())
    unmatched = tuple(issue.issue_id for issue in issues if issue.issue_id not in matched)
    return MatchResult(
        tp=tp, fp=len(findings) - tp, fn=len(issues) - tp, verdicts=verdicts, unmatched_issue_ids=unmatched
    )


def _finding_edges(
    finding: Finding,
    issues: Sequence[TruthIssue],
    tolerance: Mapping[str, int],
    universe: frozenset[str],
    observed: frozenset[str] | None,
) -> tuple[list[str], tuple[str, ...]]:
    """The issue_ids this finding has an edge to, and the reasons it would stay unmatched."""
    problem = evidence_problem(finding, universe, observed)
    if problem is not None:
        return [], (problem,)
    affected = frozenset(finding.affected_ids)
    candidates = [issue for issue in issues if issue.type == finding.type and issue.affected_ids == affected]
    if not candidates:
        return [], (REASON_NO_ISSUE,)
    reasons = {issue.issue_id: edge_reasons(finding, issue, tolerance) for issue in candidates}
    fitting = [issue_id for issue_id, why in reasons.items() if not why]
    if fitting:
        return fitting, (REASON_REPEATED,)
    return [], tuple(sorted({reason for why in reasons.values() for reason in why}))


def choose_pairs(edges: Iterable[tuple[str, int]]) -> tuple[tuple[str, int], ...]:
    """The official maximum matching of an edge graph given as (issue_id, finding index) pairs.

    Among all maximum-cardinality matchings it returns the one whose sorted sequence of
    (issue_id, finding index) pairs is lexicographically smallest, issue_ids compared by
    Unicode code points. Greedy with a feasibility check: walk the issues in order and give
    each the smallest finding index that still lets the rest complete a maximum matching.
    """
    graph: dict[str, set[int]] = {}
    for issue_id, index in edges:
        graph.setdefault(issue_id, set()).add(index)
    order = sorted(graph)
    size = _matching_size(order, graph, frozenset())
    chosen: list[tuple[str, int]] = []
    used: set[int] = set()
    for position, issue_id in enumerate(order):
        if len(chosen) == size:
            break
        later = order[position + 1 :]
        for index in sorted(graph[issue_id] - used):
            if len(chosen) + 1 + _matching_size(later, graph, frozenset(used | {index})) == size:
                chosen.append((issue_id, index))
                used.add(index)
                break
    return tuple(chosen)


def _matching_size(issue_ids: Sequence[str], graph: Mapping[str, set[int]], blocked: frozenset[int]) -> int:
    """Kuhn's augmenting paths: the maximum matching size between these issues and unblocked findings."""
    owner: dict[int, str] = {}

    def augment(issue_id: str, visited: set[int]) -> bool:
        for index in sorted(graph[issue_id] - blocked):
            if index in visited:
                continue
            visited.add(index)
            if index not in owner or augment(owner[index], visited):
                owner[index] = issue_id
                return True
        return False

    return sum(1 for issue_id in issue_ids if augment(issue_id, set()))
