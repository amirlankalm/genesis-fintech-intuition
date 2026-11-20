from __future__ import annotations

import itertools
from fractions import Fraction

import pytest

from genesis_audit import scoring
from genesis_audit.scoring import Score, common_reward, f1, precision, recall, reward_before_clip

# The guide's table (section 4), at 30 inspections. Reward to three decimals.
GUIDE_TABLE = [
    (3, 0, 0, "1.000", "0.940"),
    (2, 0, 1, "0.800", "0.540"),
    (2, 1, 1, "0.667", "0.273"),
    (3, 27, 0, "0.182", "-0.696"),
    (0, 0, 3, "0.000", "-1.000"),
    (0, 0, 0, "1.000", "0.940"),
    (0, 1, 0, "0.000", "-1.000"),
]


@pytest.mark.parametrize(("tp", "fp", "fn", "f1_text", "reward_text"), GUIDE_TABLE)
def test_guide_table(tp: int, fp: int, fn: int, f1_text: str, reward_text: str) -> None:
    assert f"{float(f1(tp, fp, fn)):.3f}" == f1_text
    assert f"{float(common_reward(tp, fp, fn, 30)):.3f}" == reward_text


def test_exact_values() -> None:
    assert common_reward(3, 0, 0, 30) == Fraction(47, 50)
    assert common_reward(3, 1, 0, 30) == Fraction(229, 350)  # one false claim on top of a perfect answer
    assert reward_before_clip(0, 0, 3, 30) == Fraction(-53, 50)
    assert scoring.STEP_COST == Fraction(1, 500) and scoring.MALFORMED_REWARD == -1


def test_special_cases_for_empty_sets() -> None:
    assert f1(0, 0, 0) == 1  # truth empty, findings empty
    assert f1(0, 4, 0) == 0  # truth empty, findings not
    assert f1(0, 0, 4) == 0  # findings empty, truth not
    assert precision(0, 0) == 0 and recall(0, 0) == 0  # undefined P or R is 0


def test_reward_is_clipped_to_the_unit_interval() -> None:
    for tp, fp, fn, steps in itertools.product(range(4), range(4), range(4), (0, 30, 99, 100)):
        assert -1 <= common_reward(tp, fp, fn, steps) <= 1
    assert common_reward(5, 0, 0, 0) == 1 and common_reward(0, 9, 9, 100) == -1


def test_reward_is_monotone_in_each_count() -> None:
    for tp, fp, fn in itertools.product(range(5), repeat=3):
        here = common_reward(tp, fp, fn, 10)
        if tp + fp + fn > 0:  # leaving the both-empty special case is not a "one more" comparison
            assert common_reward(tp, fp + 1, fn, 10) <= here
            assert common_reward(tp, fp, fn + 1, 10) <= here
        assert common_reward(tp + 1, fp, fn, 10) >= here or tp + fp + fn == 0
        assert common_reward(tp, fp, fn, 11) <= here


def test_step_cost_only_separates_otherwise_equal_results_slightly() -> None:
    assert common_reward(3, 0, 0, 10) - common_reward(3, 0, 0, 11) == Fraction(1, 500)
    assert common_reward(3, 0, 0, 0) - common_reward(3, 0, 0, 50) == Fraction(1, 10)
    # even the whole budget of inspections costs less than one missed issue out of three
    assert common_reward(3, 0, 0, 99) > common_reward(2, 0, 1, 0)


def test_score_json_keeps_raw_components() -> None:
    document = Score.from_counts(3, 27, 0, 30).to_json()
    assert document["f1_exact"] == "2/11" and document["reward_exact"] == "-383/550"
    assert (document["tp"], document["fp"], document["fn"], document["malformed"]) == (3, 27, 0, False)
    assert document["precision"] == pytest.approx(0.1) and document["recall"] == 1.0
    clipped = Score.from_counts(0, 0, 3, 30).to_json()
    assert (clipped["reward"], clipped["reward_before_clip"]) == (-1.0, -1.06)
    malformed = Score.for_malformed(4).to_json()
    assert malformed == {"malformed": True, "inspection_steps": 4, "reward": -1.0, "reward_exact": "-1"}


@pytest.mark.parametrize("bad", [(-1, 0, 0, 0), (0, 1.5, 0, 0), (0, 0, True, 0), (0, 0, 0, -3), (0, 0, 0, "3")])
def test_counts_must_be_non_negative_integers(bad: tuple) -> None:
    with pytest.raises(ValueError):
        common_reward(*bad)
    with pytest.raises(ValueError):
        Score.for_malformed(-1)
