"""Money in integer minor units and FX conversion with declared exponents and rounding.

No binary floats: amounts are integers, rates are decimal strings, and the
conversion is exact up to the single declared rounding step. It uses its own
decimal context, so the caller's context can neither round it early nor change it.
half_up rounds halves away from zero, for negative amounts too.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Context, Decimal, InvalidOperation
from fractions import Fraction

ROUNDING_MODES = {"half_up": ROUND_HALF_UP, "half_even": ROUND_HALF_EVEN}
_MAX_RATE_CHARS = 32
MAX_ABS_MINOR = 10**18
# Wide enough that amount x rate x scale is exact: 19 + 32 + 6 digits fit with room to spare.
_EXACT = Context(prec=80)


def parse_rate(rate: str) -> Decimal:
    """Parse an FX rate given as a plain positive decimal string such as '512.40'."""
    if not isinstance(rate, str) or not 0 < len(rate) <= _MAX_RATE_CHARS:
        raise ValueError("rate must be a short decimal string")
    if not all(ch in "0123456789." for ch in rate) or rate.count(".") > 1:
        raise ValueError("rate must contain only digits and at most one decimal point")
    try:
        value = Decimal(rate)
    except InvalidOperation as exc:
        raise ValueError("rate is not a decimal number") from exc
    if value <= 0:
        raise ValueError("rate must be positive")
    return value


def convert_minor(source_minor: int, source_exponent: int, rate: str, target_exponent: int, rounding: str) -> int:
    """Convert minor units of one currency into minor units of another.

    target_minor = round((source_minor / 10**source_exponent) * rate * 10**target_exponent)

    `rate` is target units per one source unit. Quoting direction is the caller's
    responsibility: invert the published rate first if it is quoted the other way.
    """
    if isinstance(source_minor, bool) or not isinstance(source_minor, int):
        raise ValueError("source_minor must be an integer")
    if rounding not in ROUNDING_MODES:
        raise ValueError(f"undeclared rounding mode: {rounding}")
    for exponent in (source_exponent, target_exponent):
        if isinstance(exponent, bool) or not isinstance(exponent, int) or not 0 <= exponent <= 6:
            raise ValueError("currency exponent must be an integer between 0 and 6")
    if abs(source_minor) > MAX_ABS_MINOR:
        raise ValueError("source_minor is outside the supported range")
    scale = Decimal(1).scaleb(target_exponent - source_exponent, context=_EXACT)
    exact = _EXACT.multiply(_EXACT.multiply(Decimal(source_minor), parse_rate(rate)), scale)
    return int(exact.quantize(Decimal(1), rounding=ROUNDING_MODES[rounding], context=_EXACT))


def convert_minor_inverse(
    source_minor: int, source_exponent: int, rate: str, target_exponent: int, rounding: str
) -> int:
    """Convert with a rate quoted the other way round: `rate` is source units per one target unit.

    target_minor = round((source_minor / 10**source_exponent) / rate * 10**target_exponent)

    The quotient is held as an exact fraction and rounded once, so no precision is chosen anywhere.
    """
    if isinstance(source_minor, bool) or not isinstance(source_minor, int):
        raise ValueError("source_minor must be an integer")
    if rounding not in ROUNDING_MODES:
        raise ValueError(f"undeclared rounding mode: {rounding}")
    for exponent in (source_exponent, target_exponent):
        if isinstance(exponent, bool) or not isinstance(exponent, int) or not 0 <= exponent <= 6:
            raise ValueError("currency exponent must be an integer between 0 and 6")
    if abs(source_minor) > MAX_ABS_MINOR:
        raise ValueError("source_minor is outside the supported range")
    exact = Fraction(source_minor) * Fraction(10) ** (target_exponent - source_exponent) / Fraction(parse_rate(rate))
    return round_fraction(exact, rounding)


def round_fraction(value: Fraction, rounding: str) -> int:
    """Round an exact fraction to an integer. half_up rounds halves away from zero; half_even to the even neighbour."""
    if rounding not in ROUNDING_MODES:
        raise ValueError(f"undeclared rounding mode: {rounding}")
    below = value.numerator // value.denominator  # floor, for negative values too
    rest = value - below
    if rest != Fraction(1, 2):
        return below + (1 if rest > Fraction(1, 2) else 0)
    if rounding == "half_even":
        return below if below % 2 == 0 else below + 1
    return below + 1 if value > 0 else below


def format_minor(amount_minor: int, exponent: int, currency: str) -> str:
    """Render minor units for humans, for example 250000 at exponent 2 -> '2500.00 KZT'."""
    sign = "-" if amount_minor < 0 else ""
    digits = str(abs(amount_minor)).rjust(exponent + 1, "0")
    major = digits[: len(digits) - exponent] if exponent else digits
    fraction = f".{digits[-exponent:]}" if exponent else ""
    return f"{sign}{major}{fraction} {currency}"
