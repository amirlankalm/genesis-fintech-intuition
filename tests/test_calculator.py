from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from helpers import FAULTY, finding, submit_action

from genesis_audit import calculator
from genesis_audit.calculator import evaluate
from genesis_audit.env import AuditEnv
from genesis_audit.errors import PolicyVisibleError


def code(expression: object) -> str:
    with pytest.raises(PolicyVisibleError) as caught:
        evaluate(expression)
    return caught.value.code


@pytest.mark.parametrize(
    ("expression", "result"),
    [
        ("1+2", "3"),
        ("2*3+4", "10"),
        ("2*(3+4)", "14"),
        ("2+3*4", "14"),
        ("10/4", "2.5"),
        ("1/8", "0.125"),
        ("1/3", "0.333333333333333333"),
        ("2/3", "0.666666666666666667"),
        ("-5+2", "-3"),
        ("--5", "5"),
        ("+5", "5"),
        (" 12.50 * 3 ", "37.5"),
        ("250000-150000", "100000"),
        ("(10000/100)*500*100", "5000000"),
        ("0.1+0.2", "0.3"),
        ("5-5", "0"),
        ("-0", "0"),
        ("0/7", "0"),
        ("100*1.10", "110"),
        ("7", "7"),
        ("((((1))))", "1"),
        ("(" * 32 + "1" + ")" * 32, "1"),
        ("9" * 40, "9" * 40),
    ],
)
def test_arithmetic(expression: str, result: str) -> None:
    assert evaluate(expression) == result


@pytest.mark.parametrize(
    "expression",
    ["", "   ", "1+", "*2", "(1+2", "1+2)", "()", "1 2", "1..2", ".5", "5.", "1e3", "2**3", "0x10", "١٢", "1,000",
     "1\n+1", "1\t+1", "abs(1)", "__import__('os')", "a", "1;2", "1+2 #", "1_000", "True", "1 if 1 else 2", "[1]",
     "'1'", "1.2.3", "lambda: 1", "１+１", 5, None, ["1"], b"1+1"],
)  # fmt: skip
def test_everything_else_is_a_syntax_error(expression: object) -> None:
    assert code(expression) == "calc_syntax"


def test_resource_bounds() -> None:
    assert code("1+" * 200 + "1") == "calc_too_long"
    assert code("(" * 40 + "1" + ")" * 40) == "calc_too_deep"
    assert code("-" * 40 + "1") == "calc_too_deep"
    assert code("9" * 41) == "calc_overflow"
    assert code("*".join(["9999999999"] * 5)) == "calc_overflow"
    assert code("1" + "0" * 39 + "*10") == "calc_overflow"
    for expression in ("1/0", "1/(2-2)", "1/0.0", "0/0"):
        assert code(expression) == "calc_div_zero"


def test_worst_case_expressions_are_fast() -> None:
    heavy = [("9" * 39 + "/7*") * 6 + "1", "(" * 32 + "1/3" + ")" * 32, "1/3" + "/3" * 120]
    started = time.perf_counter()
    for expression in heavy * 50:
        try:
            evaluate(expression)
        except PolicyVisibleError:
            pass
    assert time.perf_counter() - started < 1.0


def test_injection_attempt_executes_nothing(tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    for attack in (f"__import__('os').system('touch {marker}')", f"open('{marker}','w')", "().__class__.__bases__",
                   f"exec(\"open('{marker}','w')\")", "globals()", "1 or __builtins__"):  # fmt: skip
        assert code(attack) == "calc_syntax"
    assert not marker.exists()


def test_implementation_has_no_evaluator_to_abuse() -> None:
    source = Path(calculator.__file__).read_text(encoding="utf-8")
    assert not re.search(r"\b(eval|exec|compile|__import__)\s*\(", source)
    assert "import ast" not in source and "getattr" not in source


def test_calculator_is_a_tool_that_costs_a_step(env: AuditEnv) -> None:
    env.reset(config={"episode": FAULTY})
    observation, reward, terminated, truncated, _ = env.step(
        {"action": "calculator", "args": {"expression": "250000-150000"}}
    )
    assert observation == {"result": "100000", "steps_remaining": 99}
    assert (reward, terminated, truncated) == (0.0, False, False)
    observation, reward, terminated, _, _ = env.step(
        {"action": "calculator", "args": {"expression": "__import__('os')"}}
    )
    assert observation["error"]["code"] == "calc_syntax" and (reward, terminated) == (0.0, False)
    for bad in ({}, {"expression": "1", "base": 2}, None):
        assert env.step({"action": "calculator", "args": bad})[0]["error"]["code"] == "bad_arguments"
    _, reward, *_ = env.step(submit_action([finding()]))
    assert reward == pytest.approx(1 - 0.002 * 5)  # calculator calls are charged like any inspection


def test_nothing_is_executed_even_with_the_builtins_booby_trapped(monkeypatch) -> None:
    """Review E, hypothesis C1: if any evaluator were reachable, these traps would fire."""
    import builtins

    def trap(*args: object, **kwargs: object) -> None:
        raise AssertionError("the calculator reached a code-execution builtin")

    for name in ("eval", "exec", "compile"):
        monkeypatch.setattr(builtins, name, trap)
    for attack in ("__import__('os').system('id')", "().__class__.__mro__", "a.b", "f(1)", "x", '"1"*9', "[1][0]",
                   "(x := 1)", "9**9**9", "1e999999999 + 1", "NaN", "Infinity", "sNaN"):  # fmt: skip
        assert code(attack) == "calc_syntax"
    assert evaluate("2*(3+4)") == "14"


def test_bounds_are_checked_before_any_parsing() -> None:
    assert code("(" * 100_000) == "calc_too_long"  # no recursion happens: length is checked first
    assert code("-" * 100_000 + "1") == "calc_too_long"
    assert code("9" * 1_000_000) == "calc_too_long"


def test_calculator_neither_reads_nor_changes_the_decimal_context() -> None:
    import decimal

    expressions = ["1/3", "9" * 40 + "-1", "-" + "9" * 40, "123456789.123456789*987654321.987654321", "2/3+1/7"]
    expected = [evaluate(expression) for expression in expressions]
    with decimal.localcontext() as context:
        context.prec = 3
        context.rounding = decimal.ROUND_UP
        context.traps[decimal.Inexact] = True
        before = (context.prec, context.rounding, dict(context.flags))
        assert [evaluate(expression) for expression in expressions] == expected
        assert (context.prec, context.rounding, dict(context.flags)) == before
    assert expected[1] == "9" * 39 + "8" and expected[2] == "-" + "9" * 40


def test_result_is_a_bounded_string_and_the_same_every_time(env: AuditEnv) -> None:
    for expression in ("1/3", "1/7*7", "0.000000000000000000001*1", "9" * 39 + "/7"):
        result = evaluate(expression)
        assert len(result) <= 60 and result == evaluate(expression)
    assert evaluate("0.000000000000000000001*1") == "0"  # below 18 fractional digits rounds to zero
    env.reset(config={"episode": FAULTY})
    first = env.step({"action": "calculator", "args": {"expression": "1/3"}})[0]["result"]
    env.reset(config={"episode": "teaching_b_clean"})
    assert env.step({"action": "calculator", "args": {"expression": "1/3"}})[0]["result"] == first
    assert env.evaluator_view() and not env._state.observed  # a calculator result is not evidence
