"""Prompt A: Socratic tutor. Ten questions; numeric keys are computed, not typed in."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..money import convert_minor
from .core import Bank, Question

_ALMATY = timezone(timedelta(hours=5))
_COMPLETED = datetime.fromisoformat("2026-10-31T20:30:00+00:00").astimezone(_ALMATY)
_FX_RIGHT = convert_minor(10_000, 2, "500", 2, "half_up")
_FX_BOOKED = convert_minor(10_000, 2, "490", 2, "half_up")
_JPY_BASE = convert_minor(10_000, 0, "3.30", 2, "half_up")

QUESTIONS = (
    Question(
        concept="state_vs_observation",
        prompt=(
            "At reset the agent receives the task, manifest, policy summary and remaining budget. Which of "
            "these belongs to the STATE but not to the OBSERVATION? (a) the reporting period (b) the remaining "
            "step budget (c) the list of injected errors (d) the rounding policy"
        ),
        kind="choice",
        answer="c",
        explanation="The state is the whole world, including hidden errors; the observation is only what was exposed.",
        counterexample=(
            "If the injected-error list were observable, a policy could submit it with zero inspections and "
            "score the maximum. The environment would then measure nothing."
        ),
        smaller=Question(
            concept="state_vs_observation",
            prompt=(
                "The agent has not fetched ledger row L11 yet. L11's credit amount is in (a) the state only "
                "(b) the observation only (c) both"
            ),
            kind="choice",
            answer="a",
            explanation="It exists in the world, but no tool has returned it yet.",
        ),
    ),
    Question(
        concept="roles",
        prompt=(
            "A fixed script lists invoices, payments and ledger rows, reconciles them and submits findings. No "
            "weights change. It is (a) a trainer (b) a policy (c) a verifier (d) a transition"
        ),
        kind="choice",
        answer="b",
        explanation="Anything that chooses the next action is a policy, scripted or learned.",
        counterexample="A trainer changes a policy using many scored rollouts. This script changes nothing; it only acts.",
        smaller=Question(
            concept="roles",
            prompt="Sampling 8 answers and keeping the best-scoring one, with no weight update: is that training? (yes/no)",
            kind="yesno",
            answer=False,
            explanation="That is best-of-N selection at inference time. The weights are unchanged.",
        ),
    ),
    Question(
        concept="transition_and_budget",
        prompt=(
            "The budget is 100 steps and 11 are used. The agent calls get_record with an id that does not "
            "exist. How many steps remain after the call?"
        ),
        kind="int",
        answer=100 - 12,
        explanation="An unknown id returns a bounded error and still consumes a step.",
        counterexample="If failed lookups were free, a policy could probe guessed ids without limit.",
        smaller=Question(
            concept="transition_and_budget",
            prompt="What reward does that failed lookup return?",
            kind="int",
            answer=0,
            explanation="Every inspection step returns reward 0, successful or not. Only the terminal step is scored.",
        ),
    ),
    Question(
        concept="roles",
        prompt=(
            "Which component may read truth.json? (a) the policy, to check its work (b) the tool bridge, to "
            "filter records (c) the verifier, to score the final submission (d) the trainer, to build prompts"
        ),
        kind="choice",
        answer="c",
        explanation="Truth becomes a scalar reward after submission. It never becomes policy input.",
        counterexample="A trainer that puts truth into prompts has leaked the labels into the policy's input.",
        smaller=Question(
            concept="roles",
            prompt="truth.json is moved into another Python module of a package the agent can read. Is it hidden now? (yes/no)",
            kind="yesno",
            answer=False,
            explanation="A module or a package is not a permission boundary. A readable file is a readable file.",
        ),
    ),
    Question(
        concept="allocation_arithmetic",
        prompt=(
            "Invoice I7 is 100,000 minor units. Bank document P9 proves a 100,000 receipt for I7. The ledger "
            "allocates 60,000 of P9 to I7 and nothing else. What is the discrepancy, in minor units?"
        ),
        kind="int",
        answer=100_000 - 60_000,
        explanation="Required allocation 100,000 minus recorded allocation 60,000.",
        counterexample=(
            "The whole payment is not the discrepancy, because 60,000 was allocated correctly. And 40,000 KZT "
            "would be 4,000,000 minor units at exponent 2."
        ),
        smaller=Question(
            concept="allocation_arithmetic",
            prompt="What should I7's outstanding balance be after P9, in minor units?",
            kind="int",
            answer=0,
            explanation="The receipt covers the invoice in full, so nothing should remain open.",
        ),
    ),
    Question(
        concept="decoys",
        prompt=(
            "Invoice I3 is 100,000. Two bank receipts for I3 arrive, 60,000 and 40,000, and each is allocated "
            "to I3 in full. How many findings should you submit for I3?"
        ),
        kind="int",
        answer=0,
        explanation="A split payment that is fully allocated is valid. Same invoice, same total, no error.",
        counterexample="Flagging it is a false positive. On otherwise clean books one false claim takes F1 from 1 to 0.",
        smaller=Question(
            concept="decoys",
            prompt="What is I3's recorded outstanding balance after both receipts, in minor units?",
            kind="int",
            answer=100_000 - 60_000 - 40_000,
            explanation="60,000 + 40,000 settles the 100,000 invoice.",
        ),
    ),
    Question(
        concept="fx_units",
        prompt=(
            "A payment of USD 100.00 must be translated at the payment-date rate of 500 KZT per USD. The "
            "ledger used 490. What is the discrepancy in KZT minor units?"
        ),
        kind="int",
        answer=_FX_RIGHT - _FX_BOOKED,
        explanation=f"Correct {_FX_RIGHT:,} minus booked {_FX_BOOKED:,} KZT minor units.",
        counterexample="1,000 is the gap in KZT major units (10 KZT x 100 USD). Findings use minor units: x 100.",
        smaller=Question(
            concept="fx_units",
            prompt="What is the correct base amount, in KZT minor units?",
            kind="int",
            answer=_FX_RIGHT,
            explanation="(10,000 / 10^2) x 500 x 10^2.",
        ),
    ),
    Question(
        concept="fx_units",
        prompt=(
            "A payment of JPY 10,000 (exponent 0, so 10,000 minor units) is translated at 3.30 KZT per JPY "
            "into KZT (exponent 2). What is the base amount in KZT minor units?"
        ),
        kind="int",
        answer=_JPY_BASE,
        explanation="(10,000 / 10^0) x 3.30 x 10^2. The source exponent is 0, not 2.",
        counterexample="Assuming two decimals reads 10,000 minor units as JPY 100.00 and gives 33,000: wrong by 100x.",
        smaller=Question(
            concept="fx_units",
            prompt="How many whole KZT (major units) is that?",
            kind="int",
            answer=_JPY_BASE // 100,
            explanation="Divide KZT minor units by 10^2.",
        ),
    ),
    Question(
        concept="cutoff_timezone",
        prompt=(
            "Policy: recognise a service at completion, in the company timezone (+05:00). The period ends "
            "2026-10-31T23:59:59+05:00. A service is completed at 2026-10-31T20:30:00+00:00. Which period does "
            "it belong to? (a) October (b) November"
        ),
        kind="choice",
        answer="b" if _COMPLETED.month == 11 else "a",
        explanation=f"In company time the completion is {_COMPLETED.isoformat()}.",
        counterexample="Reading the UTC date as the local date moves a November event into October.",
        smaller=Question(
            concept="cutoff_timezone",
            prompt="What is the local hour (0-23) of that completion in the company timezone?",
            kind="int",
            answer=_COMPLETED.hour,
            explanation="20:30 UTC plus five hours.",
        ),
    ),
    Question(
        concept="evidence_sufficiency",
        prompt=(
            "Under that completion policy you suspect a posting sits in the wrong period. Which public fact is "
            "indispensable evidence? (a) the invoice due date (b) the invoice amount (c) the service "
            "completion time (d) the customer id"
        ),
        kind="choice",
        answer="c",
        explanation="The policy is defined on completion time, so only that fact, the posting and the policy decide it.",
        counterexample=(
            "An invoice issued on 30 October for a service completed on 2 November looks like October by "
            "invoice date and is November under the policy."
        ),
        smaller=Question(
            concept="evidence_sufficiency",
            prompt="If no public record carries a completion time, is that issue decidable by the agent? (yes/no)",
            kind="yesno",
            answer=False,
            explanation="Then the fixture is unsolvable and must be repaired; a decisive fact may not live only in truth.",
        ),
    ),
)

DRILLS = {
    "state_vs_observation": (
        "For the teaching episode write two lists: what is in the state at reset, and what is in the "
        "observation at reset. Repeat after one list_records call on the ledger."
    ),
    "roles": (
        "Label each as generator, environment, verifier, policy or trainer: a mutation that removes an "
        "allocation; the step budget counter; maximum matching of findings to truth; a reconciliation script; "
        "an optimizer that updates weights from scored rollouts."
    ),
    "transition_and_budget": (
        "With a 100-step budget, compute steps_remaining and inspection_steps after 3 list calls, 1 unknown id "
        "and 1 submit. Then say what happens if step 100 is a list call rather than a submit."
    ),
    "allocation_arithmetic": (
        "Invoice 80,000; one receipt of 80,000; recorded allocation 50,000: give the discrepancy. Now take two "
        "receipts of 50,000 and 45,000 with allocations 50,000 and 30,000 under an 'allocate up to the open "
        "balance' policy: explain what the remaining 15,000 is."
    ),
    "decoys": (
        "Name three valid situations that look like errors (split payment, a legitimately repeated monthly "
        "amount, an unpaid invoice with no receipt) and the single record that separates each from its error twin."
    ),
    "fx_units": (
        "Convert EUR 250.50 (exponent 2) at 560.25 KZT per EUR into KZT minor units with half-up rounding. Then "
        "redo it when the rate is quoted as EUR per KZT, and state which direction your formula expects."
    ),
    "cutoff_timezone": (
        "For a period ending 2026-10-31T23:59:59+05:00, classify 2026-10-31T18:59:59+00:00 and "
        "2026-10-31T19:00:00+00:00 as inside or outside the period."
    ),
    "evidence_sufficiency": (
        "For each family (duplicate, allocation, FX, cutoff) write the minimum evidence set, and one tempting "
        "record that is not sufficient on its own."
    ),
}

BANK = Bank(
    key="A",
    title="Prompt A - Socratic tutor: RL environment design for a synthetic audit task",
    intro=(
        "Ten questions, one at a time. Answer with a letter, a number, or yes/no; no reasoning is asked for. "
        "A wrong answer gets one counterexample and a smaller question."
    ),
    assumptions=(
        "KZT and USD have exponent 2 and JPY has exponent 0 in these questions.",
        "The FX rates 500, 490 and 3.30 are invented, and are quoted as KZT per one unit of the foreign currency.",
        "The cutoff questions assume a policy of recognising a service at completion time in a +05:00 company "
        "timezone. The draft case schema has no completion-time field, so this is an assumption of the exercise.",
        "Ids such as I7, P9 and L11 follow the guide's worked example, not an official fixture.",
    ),
    questions=QUESTIONS,
    drills=DRILLS,
)
