"""Evaluator-only truth: loading and validation.

Nothing in this module may be imported by, or returned to, a policy. A truth file
is rejected if an issue depends on a fact the public tools cannot reach, or if no
well-formed finding could ever match it: both are broken episodes, not hard ones.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import canon
from .errors import EpisodeError
from .store import PublicEpisode

LOG = logging.getLogger(__name__)
TRUTH_KEYS = ("issue_id", "type", "affected_ids", "expected_amount_minor", "currency", "acceptable_evidence_sets")
# Sanity bounds of the truth format. A finding has no such bounds: a longer or larger claim is simply unmatched.
MAX_ABS_AMOUNT_MINOR = 2**53 - 1  # the exact-integer range every JSON reader shares
MAX_AFFECTED_IDS = 20


@dataclass(frozen=True)
class TruthIssue:
    issue_id: str
    type: str
    affected_ids: frozenset[str]
    expected_amount_minor: int
    currency: str
    acceptable_evidence_sets: tuple[frozenset[str], ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "type": self.type,
            "affected_ids": sorted(self.affected_ids),
            "expected_amount_minor": self.expected_amount_minor,
            "currency": self.currency,
            "acceptable_evidence_sets": sorted(sorted(evidence) for evidence in self.acceptable_evidence_sets),
        }


def parse_truth(document: Any, *, strict: bool = True) -> tuple[TruthIssue, ...]:
    """Parse the truth.json document {"issues": [...]}. Key order never matters.

    strict=True (our own episodes) refuses unknown keys. strict=False (jury-built fixtures)
    ignores them and logs their names on the evaluator side. Missing keys and wrong JSON
    types are refused in both modes.
    """
    if not isinstance(document, dict) or "issues" not in document or not isinstance(document["issues"], list):
        raise EpisodeError("truth.json must be an object with exactly the key 'issues' holding a list")
    _check_keys(document, ("issues",), "truth.json must be an object with exactly the key 'issues'", strict)
    issues = tuple(_parse_issue(raw, strict) for raw in document["issues"])
    issue_ids = [issue.issue_id for issue in issues]
    if len(set(issue_ids)) != len(issue_ids):
        raise EpisodeError("truth issue_ids must be unique")
    return issues


def _check_keys(raw: Mapping[str, Any], expected: tuple[str, ...], message: str, strict: bool) -> None:
    if not set(expected) <= set(raw):
        raise EpisodeError(f"{message}; missing: {', '.join(sorted(set(expected) - set(raw)))}")
    extra = sorted(set(raw) - set(expected))
    if extra and strict:
        raise EpisodeError(f"{message}; unknown: {', '.join(extra)}")
    if extra:
        LOG.warning("truth.json: ignoring unknown keys %s", extra)


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) for item in value)


def _parse_issue(raw: Any, strict: bool) -> TruthIssue:
    if not isinstance(raw, dict):
        raise EpisodeError("every truth issue must be an object")
    _check_keys(raw, TRUTH_KEYS, f"truth issue keys must be exactly: {', '.join(TRUTH_KEYS)}", strict)
    amount = raw["expected_amount_minor"]
    if isinstance(amount, bool) or not isinstance(amount, int) or abs(amount) > MAX_ABS_AMOUNT_MINOR:
        raise EpisodeError("truth expected_amount_minor must be an integer within +/-(2**53 - 1): amount out of range")
    if not isinstance(raw["type"], str):
        raise EpisodeError("truth type must be a string")
    if not isinstance(raw["currency"], str):
        raise EpisodeError("truth currency must be a string")
    if not isinstance(raw["issue_id"], str):
        raise EpisodeError("truth issue_id must be a string")
    evidence_sets = raw["acceptable_evidence_sets"]
    if not isinstance(evidence_sets, list) or not evidence_sets:
        raise EpisodeError("truth acceptable_evidence_sets must be a non-empty list")
    if not all(_is_str_list(ids) for ids in (raw["affected_ids"], *evidence_sets)):
        raise EpisodeError("truth id lists must be non-empty lists of strings")
    return TruthIssue(
        issue_id=raw["issue_id"],
        type=raw["type"],
        affected_ids=frozenset(raw["affected_ids"]),
        expected_amount_minor=amount,
        currency=raw["currency"],
        acceptable_evidence_sets=tuple(frozenset(ids) for ids in evidence_sets),
    )


def validate_truth(truth: tuple[TruthIssue, ...], episode: PublicEpisode) -> None:
    """Check the truth against the public records it claims to describe.

    Every issue must be reachable and expressible: a policy that does the audit
    correctly must be able to write a well-formed finding that matches it. An issue
    that fails this is a broken episode, not a hard one.
    """
    # The scorer's universe (env._finish, judge_adapter.score_episode): an id it would void cannot be required.
    accessible, id_universe = episode.accessible_ids(), episode.id_universe()
    manifest: Mapping[str, Any] = episode.manifest
    limits = manifest["limits"]
    issue_ids = [issue.issue_id for issue in truth]
    if len(set(issue_ids)) != len(issue_ids):
        raise EpisodeError("truth issue_ids must be unique")
    if len(truth) > limits["max_findings"]:
        raise EpisodeError("truth has more issues than one submission may contain")
    keys = [(issue.type, issue.affected_ids, issue.currency) for issue in truth]
    if len(set(keys)) != len(keys):
        raise EpisodeError(
            "two truth issues share type, affected ids and currency; a finding could not tell them apart"
        )
    for issue in truth:
        where = f"truth issue {issue.issue_id}"
        if issue.type not in manifest["issue_types"]:
            raise EpisodeError(f"{where}: type is not declared in manifest.issue_types")
        if issue.currency not in manifest["currencies"]:
            raise EpisodeError(f"{where}: undeclared currency")
        if abs(issue.expected_amount_minor) <= manifest["amount_tolerance_minor"][issue.currency]:
            raise EpisodeError(
                f"{where}: the amount is within the tolerance, so a claim of nothing at all would match it"
            )
        if len(issue.affected_ids) > MAX_AFFECTED_IDS:
            raise EpisodeError(f"{where}: more affected ids than the truth format allows ({MAX_AFFECTED_IDS})")
        unknown = sorted(issue.affected_ids - id_universe)
        if unknown:
            raise EpisodeError(f"{where}: affected ids not in public records: {unknown}")
        for evidence in issue.acceptable_evidence_sets:
            missing = sorted(evidence - accessible)
            if missing:
                raise EpisodeError(
                    f"{where}: evidence not in public records (no tool returns a record or document for it): {missing}"
                )
            if len(evidence) > limits["max_evidence_ids"]:
                raise EpisodeError(f"{where}: an evidence set is larger than a finding may cite")


def load_truth(path: Path, episode: PublicEpisode, *, strict: bool = True) -> tuple[TruthIssue, ...]:
    """Read, parse and validate truth.json (UTF-8, an optional BOM is accepted)."""
    try:
        document = canon.loads_strict(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise EpisodeError(f"cannot load truth: {exc}") from exc
    truth = parse_truth(document, strict=strict)
    validate_truth(truth, episode)
    return truth
