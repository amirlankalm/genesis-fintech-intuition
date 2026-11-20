"""A calculator that parses decimal arithmetic. It never evaluates code.

Grammar (spaces allowed between tokens):

    expr   := term (("+" | "-") term)*
    term   := unary (("*" | "/") unary)*
    unary  := ("+" | "-") unary | atom
    atom   := NUMBER | "(" expr ")"
    NUMBER := DIGIT+ ("." DIGIT+)?

There are no names, calls, attributes, exponents or strings, so there is nothing
to execute. Length, nesting, literal size and magnitude are all bounded, and the
length is checked before any parsing. Arithmetic uses the module's own decimal
context: it neither reads nor changes the caller's.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Context, Decimal, DecimalException

from .errors import PolicyVisibleError

MAX_CHARS = 256
MAX_DEPTH = 32
MAX_LITERAL_CHARS = 40
MAX_FRACTION_DIGITS = 18
PRECISION = 50
_LIMIT = Decimal(10) ** 40
_ALLOWED = frozenset("0123456789.+-*/() ")
_DIGITS = frozenset("0123456789")
_CONTEXT = Context(prec=PRECISION, rounding=ROUND_HALF_EVEN)


class _Parser:
    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0
        self._depth = 0

    def parse(self) -> Decimal:
        value = self._expr()
        self._skip()
        if self._pos != len(self._text):
            raise PolicyVisibleError("calc_syntax")
        return value

    def _skip(self) -> None:
        while self._pos < len(self._text) and self._text[self._pos] == " ":
            self._pos += 1

    def _peek(self) -> str:
        self._skip()
        return self._text[self._pos] if self._pos < len(self._text) else ""

    def _nest(self) -> None:
        self._depth += 1
        if self._depth > MAX_DEPTH:
            raise PolicyVisibleError("calc_too_deep")

    def _expr(self) -> Decimal:
        value = self._term()
        while self._peek() in ("+", "-"):
            operator = self._text[self._pos]
            self._pos += 1
            right = self._term()
            value = _bounded(_CONTEXT.add(value, right) if operator == "+" else _CONTEXT.subtract(value, right))
        return value

    def _term(self) -> Decimal:
        value = self._unary()
        while self._peek() in ("*", "/"):
            operator = self._text[self._pos]
            self._pos += 1
            right = self._unary()
            if operator == "/" and right == 0:
                raise PolicyVisibleError("calc_div_zero")
            value = _bounded(_CONTEXT.multiply(value, right) if operator == "*" else _CONTEXT.divide(value, right))
        return value

    def _unary(self) -> Decimal:
        if self._peek() in ("+", "-"):
            negative = self._text[self._pos] == "-"
            self._pos += 1
            self._nest()
            value = self._unary()
            self._depth -= 1
            return _CONTEXT.minus(value) if negative else value
        return self._atom()

    def _atom(self) -> Decimal:
        if self._peek() == "(":
            self._pos += 1
            self._nest()
            value = self._expr()
            if self._peek() != ")":
                raise PolicyVisibleError("calc_syntax")
            self._pos += 1
            self._depth -= 1
            return value
        return self._number()

    def _digits(self) -> int:
        start = self._pos
        while self._pos < len(self._text) and self._text[self._pos] in _DIGITS:
            self._pos += 1
        return self._pos - start

    def _number(self) -> Decimal:
        self._skip()
        start = self._pos
        if self._digits() == 0:
            raise PolicyVisibleError("calc_syntax")
        if self._pos < len(self._text) and self._text[self._pos] == ".":
            self._pos += 1
            if self._digits() == 0:
                raise PolicyVisibleError("calc_syntax")
        literal = self._text[start : self._pos]
        if len(literal) > MAX_LITERAL_CHARS:
            raise PolicyVisibleError("calc_overflow")
        return Decimal(literal)


def _bounded(value: Decimal) -> Decimal:
    if not value.is_finite() or _CONTEXT.abs(value) >= _LIMIT:
        raise PolicyVisibleError("calc_overflow")
    return value


def evaluate(expression: object) -> str:
    """Evaluate an arithmetic expression and return a plain decimal string.

    Results carry 50 significant digits internally (half-even) and are printed
    with at most 18 fractional digits, trailing zeros removed.
    """
    if not isinstance(expression, str):
        raise PolicyVisibleError("calc_syntax")
    if len(expression) > MAX_CHARS:
        raise PolicyVisibleError("calc_too_long")
    if not expression.strip(" ") or not set(expression) <= _ALLOWED:
        raise PolicyVisibleError("calc_syntax")
    try:
        value = _bounded(_Parser(expression).parse())
        if value.as_tuple().exponent < -MAX_FRACTION_DIGITS:  # type: ignore[operator]
            value = value.quantize(Decimal(1).scaleb(-MAX_FRACTION_DIGITS), rounding=ROUND_HALF_EVEN, context=_CONTEXT)
    except DecimalException as error:  # no decimal signal may escape as an exception
        raise PolicyVisibleError("calc_overflow") from error
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text
