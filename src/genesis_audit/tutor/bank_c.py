"""Prompt C: derive the reward. Every key is computed by genesis_audit.scoring."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

from .. import scoring
from .core import Bank, Question

STEPS = 30
ISSUES = 3
CAP = 30


def dec(value: Fraction | int) -> Decimal:
    value = Fraction(value)
    return (Decimal(value.numerator) / Decimal(value.denominator)).quantize(Decimal("0.000001"))


def _case(concept: str, story: str, tp: int, fp: int, fn: int, lesson: str, slip: str, steps: int = STEPS) -> Question:
    f1, reward = scoring.f1(tp, fp, fn), scoring.common_reward(tp, fp, fn, steps)
    return Question(
        concept=concept,
        prompt=f"{story} The agent used {steps} inspection steps. Give TP FP FN F1 reward (five numbers).",
        kind="numbers",
        answer=(dec(tp), dec(fp), dec(fn), dec(f1), dec(reward)),
        explanation=f"F1 = {f1} and reward = {reward} = {float(reward):.3f}. {lesson}",
        counterexample=slip,
        smaller=Question(
            concept=concept,
            prompt="Give just the counts for that case: TP FP FN (three numbers).",
            kind="numbers",
            answer=(dec(tp), dec(fp), dec(fn)),
            explanation="Counts come first; F1 and the reward are arithmetic on them.",
        ),
    )


_BEFORE_CLIP = scoring.reward_before_clip(0, 0, ISSUES, STEPS)
_ABSTAIN_MEAN = Fraction(5 * scoring.common_reward(0, 0, 0, 0) + 15 * scoring.common_reward(0, 0, ISSUES, 0), 20)

QUESTIONS = (
    _case(
        "reward_arithmetic",
        f"Truth has {ISSUES} issues. The agent submits all {ISSUES}, each fully supported.",
        ISSUES,
        0,
        0,
        "Accuracy dominates: the only loss is the step cost, 0.002 x 30 = 0.06.",
        "A perfect answer is not 1.0 here: 30 inspections cost 0.06.",
    ),
    _case(
        "false_negatives",
        f"Truth has {ISSUES} issues. The agent submits 2 of them, fully supported, and nothing else.",
        2,
        0,
        1,
        "One missed issue costs 0.4 of reward at this size.",
        "The missed issue is a false negative, not a false positive: nothing false was claimed.",
    ),
    _case(
        "false_positives",
        f"Truth has {ISSUES} issues. The agent submits all {ISSUES}, plus one claim about a clean invoice.",
        ISSUES,
        1,
        0,
        "One false claim on top of a perfect answer costs about 0.29.",
        "The extra claim does not reduce TP. It adds one FP, which lowers precision and F1.",
    ),
    _case(
        "duplicates",
        f"Truth has {ISSUES} issues. The agent submits all {ISSUES}, then repeats the first one word for word.",
        ISSUES,
        1,
        0,
        "A repeat is scored exactly like a false claim: matching is one-to-one, so it earns nothing and costs precision.",
        "TP cannot exceed the number of truth issues. The repeat is the fourth finding and has no issue left to match.",
    ),
    _case(
        "clean_cases",
        "Truth is empty: the books are clean. The agent submits an empty findings list.",
        0,
        0,
        0,
        "Truth and findings both empty is the explicit special case F1 = 1. Correct abstention scores like a perfect find.",
        "0/0 is not scored as 0 here. Without the special case, a correct 'nothing wrong' would be punished.",
    ),
    _case(
        "flag_all",
        f"Truth has {ISSUES} issues. The agent submits {CAP} findings, the cap: the {ISSUES} right ones and {CAP - ISSUES} others.",
        ISSUES,
        CAP - ISSUES,
        0,
        "Finding everything by accusing everything scores far below finding two of three honestly.",
        "Recall is 1, but F1 also counts the 27 false positives. Volume is not rewarded.",
    ),
    Question(
        concept="clipping",
        prompt=(
            f"Truth has {ISSUES} issues. The agent submits nothing after {STEPS} inspections. Give the reward "
            "before clipping and the reward after clipping (two numbers)."
        ),
        kind="numbers",
        answer=(dec(_BEFORE_CLIP), dec(scoring.common_reward(0, 0, ISSUES, STEPS))),
        explanation="2 x 0 - 1 - 0.06 = -1.06, clipped to -1. The step cost disappears below the floor.",
        counterexample="A malformed submission is also exactly -1, so after clipping these two failures look identical.",
        smaller=Question(
            concept="clipping",
            prompt="What is F1 when truth has 3 issues and the submission is empty?",
            kind="numbers",
            answer=(dec(0),),
            explanation="TP = 0, so F1 = 0. Only the both-empty case is 1.",
        ),
    ),
    Question(
        concept="clean_cases",
        prompt=(
            "A lazy policy always submits an empty list with zero inspections. Of 20 episodes, 5 are clean and "
            f"15 have {ISSUES} issues each. What is its mean reward?"
        ),
        kind="numbers",
        answer=(dec(_ABSTAIN_MEAN),),
        explanation="(5 x 1 + 15 x (-1)) / 20. With a clean share p the lazy mean is 2p - 1.",
        counterexample="If all 20 episodes were clean, this policy would average +1 while doing no auditing at all.",
        smaller=Question(
            concept="clean_cases",
            prompt="What does that policy score on one clean episode, with zero inspections?",
            kind="numbers",
            answer=(dec(scoring.common_reward(0, 0, 0, 0)),),
            explanation="F1 = 1 by the special case and there is no step cost.",
        ),
    ),
)

DRILLS = {
    "reward_arithmetic": "Recompute the perfect case at 0, 50 and 99 inspections. State the price of 50 extra inspections.",
    "false_negatives": "Truth has 4 issues. Tabulate F1 and reward at 30 inspections for 4, 3, 2, 1 and 0 found, with no false claims.",
    "false_positives": "Find 2 of 3 and add 1 false claim, at 30 inspections. Compare with finding 2 of 3 and stopping.",
    "duplicates": "Submit one correct finding five times on books with one issue. Give TP, FP, FN and the reward at 10 inspections.",
    "clean_cases": "For clean shares 0%, 25%, 50% and 75%, give the mean reward of always-abstain at zero inspections.",
    "flag_all": "With a cap of 30 findings and 12 real issues all included, what is the best reward flag-all can reach at 40 inspections?",
    "clipping": "List three different failures that all return exactly -1, and one logged field that tells each apart.",
}


def _table() -> str:
    rows = [
        ("Find all 3, supported", 3, 0, 0),
        ("Find 2 of 3", 2, 0, 1),
        ("Find 2, add 1 false claim", 2, 1, 1),
        ("Find 3, submit 27 false claims", 3, 27, 0),
        ("Abstain on faulty books", 0, 0, 3),
        ("Correctly abstain on clean books", 0, 0, 0),
        ("One false claim on clean books", 0, 1, 0),
    ]
    lines = [
        "## The reward, computed",
        "",
        "`F1 = 2TP / (2TP + FP + FN)`; `reward = clip(2*F1 - 1 - 0.002*n, -1, 1)`; both empty gives `F1 = 1`;",
        "a malformed final submission is `-1` directly. Evidence-invalid and repeated claims are false positives.",
        "",
        f"Calculated at n = {STEPS} inspections by `genesis_audit.scoring`. These are worked examples, not measured runs.",
        "",
        "| Behaviour | TP / FP / FN | F1 | Reward | Before clipping |",
        "|---|---|---|---|---|",
    ]
    for label, tp, fp, fn in rows:
        f1, reward = scoring.f1(tp, fp, fn), scoring.common_reward(tp, fp, fn, STEPS)
        before = scoring.reward_before_clip(tp, fp, fn, STEPS)
        lines.append(f"| {label} | {tp} / {fp} / {fn} | {float(f1):.3f} | {float(reward):.3f} | {float(before):.3f} |")
    return "\n".join(lines)


BANK = Bank(
    key="C",
    title="Prompt C - derive the reward",
    intro=(
        "Six cases, one at a time, then two questions on clipping and clean-case frequency. You compute the "
        "counts, F1 and the reward before anything is checked. Answers within 0.001 are accepted."
    ),
    assumptions=(
        "This is the exact teaching reward of prompt C, which is also the draft's proposed common reward.",
        "No smooth partial credit for amounts: a finding is a true positive or it is not.",
        "The step cost uses inspection steps only; the submit step is not charged.",
    ),
    questions=QUESTIONS,
    drills=DRILLS,
    discussion=(
        (
            "Abstaining on faulty books, one false claim on clean books and a malformed submission all return "
            "-1. What does that do to learning, and what would you log?",
            "Clipping maps different failures to one number, so the reward cannot say which failure is less bad, "
            "and a group made only of such rollouts has zero reward advantage. Log TP, FP, FN, the value before "
            "clipping, the inspection count and the termination cause, and diagnose from those. Do not change "
            "the common reward to fix it.",
        ),
        (
            "How does the share of clean episodes change what a lazy policy learns?",
            "With no clean episodes, accusing something is never punished by a clean case, and abstaining is "
            "never right. With mostly clean episodes, always-abstain averages 2p - 1 and looks good while "
            "auditing nothing. Clean cases make always-accuse lose and faulty cases make always-abstain lose: "
            "both must be present, and the clean-case false-positive rate should be reported on its own.",
        ),
    ),
    appendix=_table(),
)
