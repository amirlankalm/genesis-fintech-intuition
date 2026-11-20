"""Arithmetic for the group-relative exercise of prompt D.

This is a calculator for mean, population standard deviation and normalized
outcome advantages. It is not a trainer: there is no model, no loss, no gradient
and no weight update anywhere in this repository.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class GroupStats:
    mean: float
    population_std: float
    advantages: tuple[float, ...]

    @property
    def flat(self) -> bool:
        """True when every rollout in the group got the same reward."""
        return self.population_std == 0.0


def group_stats(rewards: Sequence[float], epsilon: float = 1e-8) -> GroupStats:
    """A_i = (reward_i - group_mean) / (group_std + epsilon), with the population std."""
    if len(rewards) < 2:
        raise ValueError("a group needs at least two rollouts")
    if epsilon <= 0:
        raise ValueError("epsilon must be positive")
    mean = math.fsum(rewards) / len(rewards)
    std = math.sqrt(math.fsum((reward - mean) ** 2 for reward in rewards) / len(rewards))
    return GroupStats(mean, std, tuple((reward - mean) / (std + epsilon) for reward in rewards))


def flat_fraction(groups: Sequence[Sequence[float]]) -> float:
    """Share of groups in which all rewards are equal. Measure this before filtering anything."""
    if not groups:
        raise ValueError("no groups")
    return sum(group_stats(group).flat for group in groups) / len(groups)
