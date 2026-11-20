"""A small deterministic tutor: one question at a time, answers checked by arithmetic.

It follows the tutoring prompts' rules without a language model: ask, wait for the
learner's own answer, and on a wrong answer show one counterexample and ask a
smaller question. Weak spots are computed from what the learner actually answered.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

KINDS = ("choice", "yesno", "int", "numbers", "ids")
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class Question:
    concept: str
    prompt: str
    kind: str
    answer: Any  # choice: letter; yesno: bool; int: int; numbers: tuple of Decimal; ids: frozenset of str
    explanation: str
    counterexample: str = ""
    smaller: Question | None = None
    tolerance: Decimal = Decimal("0.001")

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown question kind: {self.kind}")

    def shown_answer(self) -> str:
        if self.kind == "yesno":
            return "yes" if self.answer else "no"
        if self.kind == "numbers":
            return "  ".join(format(value.normalize(), "f") for value in self.answer)
        if self.kind == "ids":
            return ", ".join(sorted(self.answer))
        return str(self.answer)


@dataclass(frozen=True)
class Bank:
    key: str
    title: str
    intro: str
    assumptions: tuple[str, ...]
    questions: tuple[Question, ...]
    drills: Mapping[str, str]
    discussion: tuple[tuple[str, str], ...] = ()  # (question, model answer), shown after the scored part
    appendix: str = ""  # extra markdown for the worked page, typically a computed table


@dataclass(frozen=True)
class SessionResult:
    asked: int
    first_try_correct: int
    misses: Mapping[str, int]
    weakest: tuple[str, ...]
    drills: tuple[str, ...]


def check(question: Question, raw: str) -> bool:
    """Compare a typed answer with the key. Unparseable input is simply wrong."""
    text = raw.strip().lower()
    if question.kind == "choice":
        return text.strip("()") == str(question.answer).lower()
    if question.kind == "yesno":
        return text in ("yes", "y", "no", "n") and (text[0] == "y") == question.answer
    if question.kind == "ids":
        return frozenset(token for token in re.split(r"[\s,;]+", raw.strip()) if token) == question.answer
    numbers = _NUMBER.findall(text.replace(",", "").replace("_", "").replace("−", "-"))
    try:
        values = [Decimal(number) for number in numbers]
    except InvalidOperation:
        return False
    expected = [Decimal(question.answer)] if question.kind == "int" else list(question.answer)
    tolerance = Decimal(0) if question.kind == "int" else question.tolerance
    return len(values) == len(expected) and all(abs(v - e) <= tolerance for v, e in zip(values, expected, strict=True))


def weakest_concepts(bank: Bank, misses: Mapping[str, int], count: int = 3) -> tuple[str, ...]:
    """Concepts ranked by misses, ties broken by first appearance in the bank."""
    order = list(dict.fromkeys(question.concept for question in bank.questions))
    ranked = sorted((c for c in order if misses.get(c, 0) > 0), key=lambda c: (-misses[c], order.index(c)))
    return tuple(ranked[:count])


def run_session(bank: Bank, ask: Callable[[str], str], say: Callable[[str], None]) -> SessionResult:
    """Run the scored questions one at a time, then report weak spots and drills."""
    say(f"{bank.title}\n{bank.intro}")
    for assumption in bank.assumptions:
        say(f"Teaching assumption: {assumption}")
    misses: dict[str, int] = {}
    first_try = 0
    for number, question in enumerate(bank.questions, start=1):
        if check(question, ask(f"\nQ{number}. {question.prompt}\n> ")):
            first_try += 1
            say(f"Correct. {question.explanation}")
            continue
        misses[question.concept] = misses.get(question.concept, 0) + 1
        say(f"Not yet. Counterexample: {question.counterexample}")
        smaller = question.smaller
        if smaller is not None:
            if check(smaller, ask(f"Smaller question: {smaller.prompt}\n> ")):
                say(f"Correct. {smaller.explanation}")
            else:
                misses[question.concept] += 1
                say(f"The answer is {smaller.shown_answer()}. {smaller.explanation}")
        say(f"Answer to Q{number}: {question.shown_answer()}. {question.explanation}")
    weakest = weakest_concepts(bank, misses)
    order = list(dict.fromkeys(question.concept for question in bank.questions))
    drill_concepts = list(weakest) + [c for c in reversed(order) if c not in weakest]
    drills = tuple(bank.drills[c] for c in drill_concepts[:3])
    say(f"\nFirst-try score: {first_try}/{len(bank.questions)}.")
    if weakest:
        say("Weakest concepts, from your answers: " + ", ".join(weakest) + ".")
    else:
        say("No concept was missed, so there is no weak-spot ranking to report.")
    for number, drill in enumerate(drills, start=1):
        say(f"Drill {number}: {drill}")
    for prompt, model_answer in bank.discussion:
        ask(f"\nDiscussion (not scored): {prompt}\n> ")
        say(f"One sound answer: {model_answer}")
    return SessionResult(len(bank.questions), first_try, dict(misses), weakest, drills)


def render_markdown(bank: Bank) -> str:
    """The worked version of a bank: every question, with answers folded away."""

    def block(label: str, question: Question) -> list[str]:
        lines = [f"**{label}** ({question.concept}) {question.prompt}", "", "<details><summary>Answer</summary>", ""]
        lines += [f"`{question.shown_answer()}` - {question.explanation}", ""]
        if question.counterexample:
            lines += [f"If you answered differently, one counterexample: {question.counterexample}", ""]
        return [*lines, "</details>", ""]

    out = [f"# {bank.title}", "", bank.intro, ""]
    out += ["Run it interactively, one question at a time, answers checked only after you type yours:", ""]
    out += ["```", f"uv run python -m genesis_audit tutor {bank.key}", "```", ""]
    if bank.assumptions:
        out += ["## Teaching assumptions (not Genesis rules)", ""]
        out += [f"- {assumption}" for assumption in bank.assumptions] + [""]
    out += ["## Questions", ""]
    for number, question in enumerate(bank.questions, start=1):
        out += block(f"Q{number}.", question)
        if question.smaller is not None:
            out += block(f"Q{number}, smaller follow-up.", question.smaller)
    out += ["## Weak spots and drills", ""]
    out += ["The runner ranks concepts by your own misses and prints the three weakest with their drills.", ""]
    out += ["This page cannot do that for you: it has not seen your answers. All drills, by concept:", ""]
    out += [f"- **{concept}**: {drill}" for concept, drill in bank.drills.items()] + [""]
    if bank.appendix:
        out += [bank.appendix, ""]
    if bank.discussion:
        out += ["## Discussion", ""]
        for prompt, model_answer in bank.discussion:
            out += [f"**{prompt}**", "", "<details><summary>One sound answer</summary>", "", model_answer, ""]
            out += ["</details>", ""]
    return "\n".join(out)
