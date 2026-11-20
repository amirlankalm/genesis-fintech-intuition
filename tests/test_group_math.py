from __future__ import annotations

import pytest

from genesis_audit.tutor.group_math import flat_fraction, group_stats


def test_guide_toy_group() -> None:
    stats = group_stats([0.74, 0.34, -0.46, -1.0])
    assert stats.mean == pytest.approx(-0.095)
    assert stats.population_std == pytest.approx(0.678, abs=5e-4)
    assert [round(value, 3) for value in stats.advantages] == [1.232, 0.642, -0.538, -1.335]
    assert sum(stats.advantages) == pytest.approx(0.0, abs=1e-9)
    assert not stats.flat


@pytest.mark.parametrize("reward", [-1.0, 0.94])
def test_zero_variance_groups_have_zero_reward_advantage(reward: float) -> None:
    stats = group_stats([reward] * 4)
    assert stats.flat and stats.population_std == 0.0 and stats.advantages == (0.0, 0.0, 0.0, 0.0)


def test_flat_fraction_is_measured_not_assumed() -> None:
    assert flat_fraction([[1, 1], [0, 1], [-1, -1], [0.5, 0.2]]) == 0.5


def test_input_checks() -> None:
    for bad in ([], [1.0]):
        with pytest.raises(ValueError):
            group_stats(bad)
    with pytest.raises(ValueError):
        group_stats([1.0, 2.0], epsilon=0.0)
    with pytest.raises(ValueError):
        flat_fraction([])
