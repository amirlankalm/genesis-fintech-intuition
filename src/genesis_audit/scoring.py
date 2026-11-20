"""The common score: F1 over strict matches, then the draft's terminal reward.

    F1     = 2*TP / (2*TP + FP + FN)          (1 when truth and findings are both empty)
    reward = clip(2*F1 - 1 - 0.002 * inspection_steps, -1, 1)

A malformed final submission is -1 directly. Arithmetic is exact (fractions), so
equal results compare equal on every platform; floats appear only at the edge.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from .errors import MalformedSubmission
from .matching import MatchResult, match
from .schemas import parse_findings_document
from .truth import TruthIssue

OFFICIAL_KEYS = ("tp", "fp", "fn", "precision", "recall", "f1", "return")
STEP_COST = Fraction(2, 1000)
MALFORMED_REWARD = Fraction(-1)


def _check_counts(*values: int) -> None:
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("counts must be non-negative integers")


def precision(tp: int, fp: int) -> Fraction:
    """TP / (TP + FP); an undefined precision is 0."""
    _check_counts(tp, fp)
    return Fraction(tp, tp + fp) if tp + fp else Fraction(0)


def recall(tp: int, fn: int) -> Fraction:
    """TP / (TP + FN); an undefined recall is 0."""
    _check_counts(tp, fn)
    return Fraction(tp, tp + fn) if tp + fn else Fraction(0)


def f1(tp: int, fp: int, fn: int) -> Fraction:
    _check_counts(tp, fp, fn)
    if tp == fp == fn == 0:
        return Fraction(1)  # clean books, empty submission: the explicit special case
    return Fraction(2 * tp, 2 * tp + fp + fn)


def reward_before_clip(tp: int, fp: int, fn: int, inspection_steps: int) -> Fraction:
    _check_counts(inspection_steps)
    return 2 * f1(tp, fp, fn) - 1 - STEP_COST * inspection_steps


def common_reward(tp: int, fp: int, fn: int, inspection_steps: int) -> Fraction:
    return max(Fraction(-1), min(Fraction(1), reward_before_clip(tp, fp, fn, inspection_steps)))


@dataclass(frozen=True)
class Score:
    """One episode's score with its raw components, for the evaluator's result sheet."""

    malformed: bool
    inspection_steps: int
    tp: int | None
    fp: int | None
    fn: int | None
    reward: Fraction

    @classmethod
    def from_counts(cls, tp: int, fp: int, fn: int, inspection_steps: int) -> Score:
        return cls(False, inspection_steps, tp, fp, fn, common_reward(tp, fp, fn, inspection_steps))

    @classmethod
    def for_malformed(cls, inspection_steps: int) -> Score:
        _check_counts(inspection_steps)
        return cls(True, inspection_steps, None, None, None, MALFORMED_REWARD)

    def to_official(self) -> dict[str, int | float | None]:
        """The jury's result object: tp, fp, fn, precision, recall, f1, return.

        A malformed submission gives return -1.0 and None for the other six.
        """
        if self.malformed:
            return {**dict.fromkeys(OFFICIAL_KEYS[:-1]), "return": float(self.reward)}
        tp, fp, fn = self.tp, self.fp, self.fn
        assert tp is not None and fp is not None and fn is not None
        return {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": float(precision(tp, fp)),
            "recall": float(recall(tp, fn)),
            "f1": float(f1(tp, fp, fn)),
            "return": float(self.reward),
        }

    def to_json(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "malformed": self.malformed,
            "inspection_steps": self.inspection_steps,
            "reward": float(self.reward),
            "reward_exact": str(self.reward),
        }
        if not self.malformed:
            tp, fp, fn = self.tp, self.fp, self.fn
            assert tp is not None and fp is not None and fn is not None
            document.update(
                tp=tp,
                fp=fp,
                fn=fn,
                precision=float(precision(tp, fp)),
                recall=float(recall(tp, fn)),
                f1=float(f1(tp, fp, fn)),
                f1_exact=str(f1(tp, fp, fn)),
                reward_before_clip=float(reward_before_clip(tp, fp, fn, self.inspection_steps)),
            )
        return document


@dataclass(frozen=True)
class Verification:
    """The verifier's full answer for one findings document."""

    score: Score
    result: MatchResult | None  # None when the submission is malformed
    error: str | None  # the structural error, for the evaluator log only


def score_submission(
    document: object,
    truth: Sequence[TruthIssue],
    *,
    episode_id: str,
    limits: Mapping[str, int],
    tolerance: Mapping[str, int],
    universe: Collection[str],
    inspection_steps: int,
    observed: Collection[str] | None = None,
) -> Verification:
    """Parse a findings.json object, match it against the truth and score it."""
    try:
        findings = parse_findings_document(document, episode_id, limits)
    except MalformedSubmission as error:
        return Verification(Score.for_malformed(inspection_steps), None, error.detail)
    result = match(findings, truth, tolerance=tolerance, universe=universe, observed=observed)
    return Verification(Score.from_counts(result.tp, result.fp, result.fn, inspection_steps), result, None)
