"""Prompt D: group-relative RL as arithmetic and diagnosis. Keys are computed by group_math."""

from __future__ import annotations

from decimal import Decimal

from .core import Bank, Question
from .group_math import group_stats

REWARDS = (0.74, 0.34, -0.46, -1.0)
STATS = group_stats(REWARDS)
ALL_FAIL = group_stats((-1.0, -1.0, -1.0, -1.0))
ALL_PASS = group_stats((0.94, 0.94, 0.94, 0.94))
_SHOWN = "[0.74, 0.34, -0.46, -1]"


def dec(value: float) -> Decimal:
    return Decimal(str(round(value, 6))) + Decimal(0)


def _choice(
    concept: str, prompt: str, answer: str, explanation: str, counterexample: str, smaller: Question
) -> Question:
    return Question(concept, prompt, "choice", answer, explanation, counterexample, smaller)


QUESTIONS = (
    Question(
        concept="group_statistics",
        prompt=f"One audit episode, four rollouts, rewards {_SHOWN}. What is the group mean?",
        kind="numbers",
        answer=(dec(STATS.mean),),
        explanation="(0.74 + 0.34 - 0.46 - 1) / 4 = -0.38 / 4.",
        counterexample="The mean is taken over all four rollouts, including the two failures; it is not the mean of the good ones.",
        smaller=Question(
            concept="group_statistics",
            prompt="What is the sum of the four rewards?",
            kind="numbers",
            answer=(dec(sum(REWARDS)),),
            explanation="0.74 + 0.34 = 1.08; 1.08 - 0.46 = 0.62; 0.62 - 1 = -0.38.",
        ),
    ),
    Question(
        concept="group_statistics",
        prompt="What is the population standard deviation of that group (divide by 4, not 3)?",
        kind="numbers",
        answer=(dec(STATS.population_std),),
        explanation="Squared deviations 0.697225 + 0.189225 + 0.133225 + 0.819025 = 1.8387; / 4 = 0.459675; square root.",
        counterexample="Dividing by 3 gives the sample standard deviation, 0.783. The group baseline uses the population form.",
        smaller=Question(
            concept="group_statistics",
            prompt="What is the deviation of the first rollout from the mean?",
            kind="numbers",
            answer=(dec(REWARDS[0] - STATS.mean),),
            explanation="0.74 - (-0.095).",
        ),
        tolerance=Decimal("0.001"),
    ),
    Question(
        concept="group_statistics",
        prompt="Give the four normalized advantages A_i = (reward_i - mean) / std, in order.",
        kind="numbers",
        answer=tuple(dec(value) for value in STATS.advantages),
        explanation="Each deviation divided by 0.678. They sum to zero by construction.",
        counterexample="Advantages are not the rewards themselves: -0.46 is below the mean of -0.095, so its advantage is negative.",
        smaller=Question(
            concept="group_statistics",
            prompt="Give only the advantage of the first rollout.",
            kind="numbers",
            answer=(dec(STATS.advantages[0]),),
            explanation="0.835 / 0.678.",
            tolerance=Decimal("0.01"),
        ),
        tolerance=Decimal("0.01"),
    ),
    _choice(
        "advantage_meaning",
        "Rollout 2 scored 0.34, far from perfect. Its advantage is (a) positive (b) negative (c) zero",
        "a",
        "It beat its group's mean, so the update tends to make its sampled actions more likely, flaws included.",
        "The comparison is with the group mean of -0.095, not with a perfect score.",
        Question(
            concept="advantage_meaning",
            prompt="Is 0.34 above the group mean of -0.095? (yes/no)",
            kind="yesno",
            answer=True,
            explanation="Better than group average is all a group-relative advantage measures.",
        ),
    ),
    _choice(
        "advantage_meaning",
        "The reward arrives only at the end of a rollout. A positive advantage for rollout 1 tells you (a) each "
        "of its inspections was useful (b) the rollout as a whole beat its group, not which step caused that",
        "b",
        "Terminal reward gives one number per rollout. Every action token in it shares that credit, useful or not.",
        "A rollout can waste ten inspections and still win its group; those wasted steps get reinforced too.",
        Question(
            concept="advantage_meaning",
            prompt="How many reward numbers does one rollout produce under a terminal-only reward?",
            kind="int",
            answer=1,
            explanation="One, at the end. Inspection steps return 0.",
        ),
    ),
    Question(
        concept="flat_groups",
        prompt="All four rollouts score -1. Give the four reward advantages.",
        kind="numbers",
        answer=tuple(dec(value) for value in ALL_FAIL.advantages),
        explanation="Every deviation is 0, so every advantage is 0 / (0 + epsilon) = 0.",
        counterexample="A group of equally bad rollouts does not produce negative advantages: nothing is worse than the group mean.",
        smaller=Question(
            concept="flat_groups",
            prompt="What is the population standard deviation of [-1, -1, -1, -1]?",
            kind="numbers",
            answer=(dec(ALL_FAIL.population_std),),
            explanation="No spread at all.",
        ),
    ),
    Question(
        concept="flat_groups",
        prompt="All four rollouts score +0.94. Does that alone prove the task is too easy? (yes/no)",
        kind="yesno",
        answer=False,
        explanation=(
            "It is a zero-advantage group and a reason to look: the task may be easy, or the policy may already "
            "be good on this one episode. Read the trajectories before changing anything."
        ),
        counterexample="An oracle-like scripted policy scores 0.94 on a hard episode too. One flat group identifies neither.",
        smaller=Question(
            concept="flat_groups",
            prompt="Is the reward advantage of each rollout in that group zero? (yes/no)",
            kind="yesno",
            answer=ALL_PASS.flat,
            explanation="Equal rewards, zero deviations. Other loss terms, such as regularization, may still be non-zero.",
        ),
    ),
    _choice(
        "failure_diagnosis",
        "All four rollouts score -1. The evaluator log shows termination_cause = malformed_submission for all "
        "four. First suspect (a) weak audit reasoning (b) an impossible task (c) the output format or tool "
        "adapter (d) a scorer bug",
        "c",
        "Malformed is its own branch with its own log entry. Fix the JSON path before judging the policy's auditing.",
        "A policy with perfect audit reasoning also gets -1 if its final JSON has one extra key.",
        Question(
            concept="failure_diagnosis",
            prompt="Which logged field separates 'malformed' from 'valid but wrong'? (a) reward (b) termination_cause",
            kind="choice",
            answer="b",
            explanation="Both rewards are -1 after clipping; the termination cause and validation error differ.",
        ),
    ),
    _choice(
        "failure_diagnosis",
        "All four score -1 with valid submissions. The evaluator-only oracle, submitting the truth with full "
        "evidence on the same episode, also scores -1. First suspect (a) the policy (b) truth, matching, "
        "evidence or reward code (c) the step budget (d) clipping",
        "b",
        "The oracle is the score ceiling. If the ceiling is low, the environment is wrong, not the task hard.",
        "Calling that episode 'hard' would blame every policy for a bug in the grader.",
        Question(
            concept="failure_diagnosis",
            prompt="What should a correct environment give the oracle with zero inspections?",
            kind="numbers",
            answer=(Decimal(1),),
            explanation="F1 = 1 and no step cost.",
        ),
    ),
    _choice(
        "failure_diagnosis",
        "All four score -1 with valid submissions. The oracle scores 1.0. A reachability check shows one "
        "required evidence record cannot be fetched within the step budget. This is (a) a weak policy (b) an "
        "impossible task: a generator or budget fault (c) malformed output (d) a scorer bug",
        "b",
        "The oracle proves truth and scoring agree; it does not prove the answer is reachable through the tools.",
        "No investigator, however good, can cite a record the tools cannot return in time.",
        Question(
            concept="failure_diagnosis",
            prompt="Does a high oracle score show that a budgeted investigator can solve the episode? (yes/no)",
            kind="yesno",
            answer=False,
            explanation="It shows the ceiling exists. Reachability under the budget is measured separately.",
        ),
    ),
    _choice(
        "training_vs_inference",
        "You sample 8 answers per episode and report the best-scoring one. No weights change. This is (a) RL "
        "(b) SFT (c) best-of-N at inference (d) rollout logging",
        "c",
        "Selection can raise a displayed score without training anything.",
        "The model that produced the eight answers is byte-for-byte the model you started with.",
        Question(
            concept="training_vs_inference",
            prompt="After best-of-N, has any weight changed? (yes/no)",
            kind="yesno",
            answer=False,
            explanation="Nothing was updated.",
        ),
    ),
    _choice(
        "training_vs_inference",
        "You fine-tune a model to imitate 500 selected demonstration transcripts. This is (a) RL (b) SFT (c) "
        "best-of-N (d) prompt editing",
        "b",
        "Supervised fine-tuning imitates chosen outputs. RL instead uses the reward to shift action probabilities.",
        "No reward enters that loss: a demonstration with a wrong finding is imitated as faithfully as a right one.",
        Question(
            concept="training_vs_inference",
            prompt="Does SFT change weights? (yes/no)",
            kind="yesno",
            answer=True,
            explanation="It is training, but it is not reinforcement learning.",
        ),
    ),
    _choice(
        "training_vs_inference",
        "You ran a policy, scored every rollout and wrote trajectories.jsonl. What has been trained? (a) "
        "nothing (b) the policy (c) the verifier",
        "a",
        "Sampling, scoring and logging produce evaluation or training data. Training needs a checkpoint you can "
        "update, tokenization, action masks, a loss, gradient steps and saved new weights.",
        "A closed API that only returns text gives you logs. Your local loop cannot update its weights.",
        Question(
            concept="training_vs_inference",
            prompt="Which artifact proves training happened? (a) a JSONL of rewards (b) a new checkpoint that differs from the base",
            kind="choice",
            answer="b",
            explanation="Changed weights, with the run that produced them, are the evidence.",
        ),
    ),
    _choice(
        "action_masks",
        "In a multi-turn rollout the transcript mixes the policy's actions with tool results. The policy loss "
        "should cover (a) every token (b) only the tokens the policy generated (c) only the tool results",
        "b",
        "Tool results are environment output. Masking them keeps the update on what the policy actually chose.",
        "Without the mask you train the model to generate bank statements, as if records were its own actions.",
        Question(
            concept="action_masks",
            prompt="Is the content of a get_document result a policy action? (yes/no)",
            kind="yesno",
            answer=False,
            explanation="It is an observation. The action was the request for it.",
        ),
    ),
)

DRILLS = {
    "group_statistics": "Redo mean, population std and advantages for rewards [0.94, 0.54, 0.54, -1]. Check that the advantages sum to zero.",
    "advantage_meaning": "Write two rollouts with equal reward where one wasted 20 inspections. Say what the update does to those wasted steps.",
    "flat_groups": "For 10 groups of which 4 are flat, give the flat fraction, then list three causes you would check before filtering any group.",
    "failure_diagnosis": "For each of bad policy, impossible task, malformed JSON and scorer bug, name the one log field or check that confirms it.",
    "training_vs_inference": "Sort into 'weights change' and 'weights do not change': prompt editing, best-of-N, SFT, rollout logging, GRPO.",
    "action_masks": "Mark each segment of a three-turn rollout as policy-generated or environment output, then say which segments carry loss.",
}


def _table() -> str:
    lines = [
        "## The toy group, computed",
        "",
        f"Rewards `{_SHOWN}`. Mean `{STATS.mean:.3f}`, population standard deviation `{STATS.population_std:.3f}`.",
        "",
        "| Rollout | Reward | Deviation | Advantage |",
        "|---|---|---|---|",
    ]
    for number, (reward, advantage) in enumerate(zip(REWARDS, STATS.advantages, strict=True), start=1):
        lines.append(f"| {number} | {reward:.2f} | {reward - STATS.mean:+.3f} | {advantage:+.3f} |")
    lines += [
        "",
        "Group-relative update, in one sentence: sampled actions from rollouts with positive advantage tend to",
        "become more likely and those with negative advantage less likely, subject to the trainer's actual loss,",
        "clipping and regularization. It says nothing about which single inspection earned the reward.",
        "",
        "A flat group, all -1 or all +0.94, has zero reward advantage for every rollout. That is a prompt to",
        "diagnose, not a verdict: other loss terms may still be non-zero, and dropping flat groups silently",
        "changes the training distribution.",
        "",
        "These numbers are arithmetic. Nothing in this repository was trained.",
    ]
    return "\n".join(lines)


BANK = Bank(
    key="D",
    title="Prompt D - GRPO debugger, not a hype explainer",
    intro=(
        "One audit episode, four rollouts. First the arithmetic, then what a zero-variance group can and cannot "
        "tell you, then what counts as training. Numbers are accepted within 0.001 (advantages within 0.01)."
    ),
    assumptions=(
        "The advantage is the standard group-normalized outcome advantage with the population standard deviation.",
        "A real trainer adds its own loss terms, clipping and reference-policy handling; check a pinned version before relying on details.",
        "The rewards are the toy numbers of the prompt, not results from this environment.",
    ),
    questions=QUESTIONS,
    drills=DRILLS,
    appendix=_table(),
)
