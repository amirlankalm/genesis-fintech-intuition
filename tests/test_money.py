from __future__ import annotations

import pytest

from genesis_audit.money import convert_minor, format_minor, parse_rate


def test_guide_fx_example_is_in_minor_units() -> None:
    # USD 100.00 at 500 vs 490 KZT/USD, both exponents 2 (guide section 3B).
    right = convert_minor(10_000, 2, "500", 2, "half_up")
    booked = convert_minor(10_000, 2, "490", 2, "half_up")
    assert (right, booked, right - booked) == (5_000_000, 4_900_000, 100_000)


def test_exponents_are_not_assumed_to_be_two() -> None:
    assert convert_minor(10_000, 0, "3.30", 2, "half_up") == 3_300_000  # JPY -> KZT
    assert convert_minor(5_000_000, 2, "0.002", 0, "half_up") == 100  # KZT -> a zero-decimal currency


@pytest.mark.parametrize(("mode", "expected"), [("half_up", 3), ("half_even", 2)])
def test_rounding_mode_is_the_declared_one(mode: str, expected: int) -> None:
    assert convert_minor(1, 0, "2.5", 0, mode) == expected


@pytest.mark.parametrize("rate", ["", "abc", "1e3", "-1", "0", "1.2.3", " 500", "5" * 40, "٣"])
def test_bad_rates_are_rejected(rate: str) -> None:
    with pytest.raises(ValueError):
        parse_rate(rate)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"source_minor": 1.5}, "integer"),
        ({"source_minor": True}, "integer"),
        ({"rounding": "truncate"}, "undeclared"),
        ({"source_exponent": 9}, "exponent"),
        ({"target_exponent": -1}, "exponent"),
    ],
)
def test_bad_conversion_inputs_are_rejected(kwargs: dict, match: str) -> None:
    arguments = {"source_minor": 100, "source_exponent": 2, "rate": "1", "target_exponent": 2, "rounding": "half_up"}
    with pytest.raises(ValueError, match=match):
        convert_minor(**{**arguments, **kwargs})


def test_format_minor() -> None:
    assert format_minor(250_000, 2, "KZT") == "2500.00 KZT"
    assert format_minor(-5, 2, "KZT") == "-0.05 KZT"
    assert format_minor(10_000, 0, "JPY") == "10000 JPY"


def test_conversion_is_exact_beyond_28_significant_digits() -> None:
    """Review E, AF-6: one exact product, then the single declared rounding step."""
    assert convert_minor(3, 0, "0.166666666666666666666666666666", 0, "half_up") == 0  # 0.4999...98 rounds down
    assert convert_minor(1, 0, "0.499999999999999999999999999999", 0, "half_up") == 0
    assert convert_minor(1, 0, "0.5", 0, "half_up") == 1
    assert (
        convert_minor(10**18, 2, "99999999999999999999999999999.99", 6, "half_up")
        == 10**18 * 9999999999999999999999999999999 * 100
    )
    with pytest.raises(ValueError, match="range"):
        convert_minor(10**28, 2, "500", 2, "half_up")


def test_conversion_ignores_the_callers_decimal_context() -> None:
    import decimal

    with decimal.localcontext() as context:
        context.prec = 2
        context.rounding = decimal.ROUND_DOWN
        assert convert_minor(123_456_789, 2, "512.40", 2, "half_up") == 63_259_258_684
        assert context.prec == 2


def test_half_up_rounds_negative_halves_away_from_zero() -> None:
    assert convert_minor(-1, 0, "0.5", 0, "half_up") == -1
    assert convert_minor(-1, 0, "0.5", 0, "half_even") == 0
