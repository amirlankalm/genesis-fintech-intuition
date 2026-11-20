from __future__ import annotations

from decimal import Decimal

import pytest

from genesis_audit import cli, tutor
from genesis_audit.tutor.core import Bank, Question, check, weakest_concepts

BANKS = tutor.banks()


def scripted(bank: Bank, answers: list[str]) -> tuple[tutor.SessionResult, list[str]]:
    queue, said = list(answers), []
    result = tutor.run_session(bank, lambda prompt: queue.pop(0), said.append)
    assert not queue, "the script supplied more answers than the session asked for"
    return result, said


def key_answers(bank: Bank) -> list[str]:
    return [question.shown_answer() for question in bank.questions] + ["" for _ in bank.discussion]


@pytest.mark.parametrize("key", sorted(BANKS))
def test_every_bank_accepts_its_own_key_and_has_drills(key: str) -> None:
    bank = BANKS[key]
    result, _ = scripted(bank, key_answers(bank))
    assert result.first_try_correct == result.asked == len(bank.questions)
    assert result.weakest == () and len(result.drills) == 3
    assert {question.concept for question in bank.questions} <= set(bank.drills)
    for question in bank.questions:
        if question.smaller is not None:
            assert check(question.smaller, question.smaller.shown_answer())
            assert question.counterexample


@pytest.mark.parametrize("key", sorted(BANKS))
def test_committed_worked_page_matches_the_bank(key: str) -> None:
    page = cli.DOCS_TUTORING / cli.TUTOR_DOCS[key]
    assert page.read_text(encoding="utf-8") == tutor.render_markdown(BANKS[key])


def test_prompt_a_has_ten_questions_and_covers_the_requested_concepts() -> None:
    bank = BANKS["A"]
    assert len(bank.questions) == 10
    concepts = [question.concept for question in bank.questions]
    assert concepts[:4] == ["state_vs_observation", "roles", "transition_and_budget", "roles"]
    assert {"allocation_arithmetic", "decoys", "fx_units", "cutoff_timezone"} <= set(concepts)


def test_wrong_answers_get_a_counterexample_a_smaller_question_and_a_ranking() -> None:
    bank = BANKS["A"]
    answers = key_answers(bank)
    answers[6:7] = ["1000", "wrong again"]  # Q7 (fx) wrong, smaller question wrong too
    answers[9:10] = ["a", "1"]  # Q9 (cutoff) wrong, smaller question right
    result, said = scripted(bank, answers)
    assert result.first_try_correct == 8
    assert result.misses == {"fx_units": 2, "cutoff_timezone": 1}
    assert result.weakest == ("fx_units", "cutoff_timezone")
    assert result.drills[:2] == (bank.drills["fx_units"], bank.drills["cutoff_timezone"])
    assert sum(line.startswith("Not yet. Counterexample:") for line in said) == 2


def test_answer_is_not_revealed_before_the_learner_answers() -> None:
    bank = BANKS["A"]
    prompts: list[str] = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return "x"

    tutor.run_session(bank, ask, lambda text: None)
    first = bank.questions[4]  # the allocation question: its numeric key must not be in the prompt
    assert f"{first.answer:,}" not in prompts[8] and str(first.answer) not in prompts[8]


@pytest.mark.parametrize(
    ("kind", "answer", "raw", "expected"),
    [
        ("choice", "c", " (C) ", True),
        ("choice", "c", "b", False),
        ("yesno", False, "No", True),
        ("yesno", False, "maybe", False),
        ("int", 40000, "40,000", True),
        ("int", 40000, "40000.5", False),
        ("int", 40000, "", False),
        ("numbers", (Decimal("0.8"), Decimal("0.54")), "0.8, 0.5401", True),
        ("numbers", (Decimal("0.8"), Decimal("0.54")), "0.8", False),
        ("numbers", (Decimal("-1"),), "−1", True),
        ("ids", frozenset({"I7", "P9"}), "P9, I7", True),
        ("ids", frozenset({"I7", "P9"}), "I7", False),
    ],
)
def test_answer_checking(kind: str, answer: object, raw: str, expected: bool) -> None:
    question = Question(concept="c", prompt="p", kind=kind, answer=answer, explanation="e")
    assert check(question, raw) is expected


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValueError):
        Question(concept="c", prompt="p", kind="essay", answer="", explanation="e")


def test_weakest_ranking_breaks_ties_by_first_appearance() -> None:
    bank = BANKS["A"]
    misses = {"decoys": 1, "roles": 1, "fx_units": 2, "cutoff_timezone": 1}
    assert weakest_concepts(bank, misses) == ("fx_units", "roles", "decoys")
