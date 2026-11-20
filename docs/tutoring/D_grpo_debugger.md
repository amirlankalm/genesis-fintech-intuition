# Prompt D - GRPO debugger, not a hype explainer

One audit episode, four rollouts. First the arithmetic, then what a zero-variance group can and cannot tell you, then what counts as training. Numbers are accepted within 0.001 (advantages within 0.01).

Run it interactively, one question at a time, answers checked only after you type yours:

```
uv run python -m genesis_audit tutor D
```

## Teaching assumptions (not Genesis rules)

- The advantage is the standard group-normalized outcome advantage with the population standard deviation.
- A real trainer adds its own loss terms, clipping and reference-policy handling; check a pinned version before relying on details.
- The rewards are the toy numbers of the prompt, not results from this environment.

## Questions

**Q1.** (group_statistics) One audit episode, four rollouts, rewards [0.74, 0.34, -0.46, -1]. What is the group mean?

<details><summary>Answer</summary>

`-0.095` - (0.74 + 0.34 - 0.46 - 1) / 4 = -0.38 / 4.

If you answered differently, one counterexample: The mean is taken over all four rollouts, including the two failures; it is not the mean of the good ones.

</details>

**Q1, smaller follow-up.** (group_statistics) What is the sum of the four rewards?

<details><summary>Answer</summary>

`-0.38` - 0.74 + 0.34 = 1.08; 1.08 - 0.46 = 0.62; 0.62 - 1 = -0.38.

</details>

**Q2.** (group_statistics) What is the population standard deviation of that group (divide by 4, not 3)?

<details><summary>Answer</summary>

`0.677993` - Squared deviations 0.697225 + 0.189225 + 0.133225 + 0.819025 = 1.8387; / 4 = 0.459675; square root.

If you answered differently, one counterexample: Dividing by 3 gives the sample standard deviation, 0.783. The group baseline uses the population form.

</details>

**Q2, smaller follow-up.** (group_statistics) What is the deviation of the first rollout from the mean?

<details><summary>Answer</summary>

`0.835` - 0.74 - (-0.095).

</details>

**Q3.** (group_statistics) Give the four normalized advantages A_i = (reward_i - mean) / std, in order.

<details><summary>Answer</summary>

`1.231575  0.641599  -0.538353  -1.334821` - Each deviation divided by 0.678. They sum to zero by construction.

If you answered differently, one counterexample: Advantages are not the rewards themselves: -0.46 is below the mean of -0.095, so its advantage is negative.

</details>

**Q3, smaller follow-up.** (group_statistics) Give only the advantage of the first rollout.

<details><summary>Answer</summary>

`1.231575` - 0.835 / 0.678.

</details>

**Q4.** (advantage_meaning) Rollout 2 scored 0.34, far from perfect. Its advantage is (a) positive (b) negative (c) zero

<details><summary>Answer</summary>

`a` - It beat its group's mean, so the update tends to make its sampled actions more likely, flaws included.

If you answered differently, one counterexample: The comparison is with the group mean of -0.095, not with a perfect score.

</details>

**Q4, smaller follow-up.** (advantage_meaning) Is 0.34 above the group mean of -0.095? (yes/no)

<details><summary>Answer</summary>

`yes` - Better than group average is all a group-relative advantage measures.

</details>

**Q5.** (advantage_meaning) The reward arrives only at the end of a rollout. A positive advantage for rollout 1 tells you (a) each of its inspections was useful (b) the rollout as a whole beat its group, not which step caused that

<details><summary>Answer</summary>

`b` - Terminal reward gives one number per rollout. Every action token in it shares that credit, useful or not.

If you answered differently, one counterexample: A rollout can waste ten inspections and still win its group; those wasted steps get reinforced too.

</details>

**Q5, smaller follow-up.** (advantage_meaning) How many reward numbers does one rollout produce under a terminal-only reward?

<details><summary>Answer</summary>

`1` - One, at the end. Inspection steps return 0.

</details>

**Q6.** (flat_groups) All four rollouts score -1. Give the four reward advantages.

<details><summary>Answer</summary>

`0  0  0  0` - Every deviation is 0, so every advantage is 0 / (0 + epsilon) = 0.

If you answered differently, one counterexample: A group of equally bad rollouts does not produce negative advantages: nothing is worse than the group mean.

</details>

**Q6, smaller follow-up.** (flat_groups) What is the population standard deviation of [-1, -1, -1, -1]?

<details><summary>Answer</summary>

`0` - No spread at all.

</details>

**Q7.** (flat_groups) All four rollouts score +0.94. Does that alone prove the task is too easy? (yes/no)

<details><summary>Answer</summary>

`no` - It is a zero-advantage group and a reason to look: the task may be easy, or the policy may already be good on this one episode. Read the trajectories before changing anything.

If you answered differently, one counterexample: An oracle-like scripted policy scores 0.94 on a hard episode too. One flat group identifies neither.

</details>

**Q7, smaller follow-up.** (flat_groups) Is the reward advantage of each rollout in that group zero? (yes/no)

<details><summary>Answer</summary>

`yes` - Equal rewards, zero deviations. Other loss terms, such as regularization, may still be non-zero.

</details>

**Q8.** (failure_diagnosis) All four rollouts score -1. The evaluator log shows termination_cause = malformed_submission for all four. First suspect (a) weak audit reasoning (b) an impossible task (c) the output format or tool adapter (d) a scorer bug

<details><summary>Answer</summary>

`c` - Malformed is its own branch with its own log entry. Fix the JSON path before judging the policy's auditing.

If you answered differently, one counterexample: A policy with perfect audit reasoning also gets -1 if its final JSON has one extra key.

</details>

**Q8, smaller follow-up.** (failure_diagnosis) Which logged field separates 'malformed' from 'valid but wrong'? (a) reward (b) termination_cause

<details><summary>Answer</summary>

`b` - Both rewards are -1 after clipping; the termination cause and validation error differ.

</details>

**Q9.** (failure_diagnosis) All four score -1 with valid submissions. The evaluator-only oracle, submitting the truth with full evidence on the same episode, also scores -1. First suspect (a) the policy (b) truth, matching, evidence or reward code (c) the step budget (d) clipping

<details><summary>Answer</summary>

`b` - The oracle is the score ceiling. If the ceiling is low, the environment is wrong, not the task hard.

If you answered differently, one counterexample: Calling that episode 'hard' would blame every policy for a bug in the grader.

</details>

**Q9, smaller follow-up.** (failure_diagnosis) What should a correct environment give the oracle with zero inspections?

<details><summary>Answer</summary>

`1` - F1 = 1 and no step cost.

</details>

**Q10.** (failure_diagnosis) All four score -1 with valid submissions. The oracle scores 1.0. A reachability check shows one required evidence record cannot be fetched within the step budget. This is (a) a weak policy (b) an impossible task: a generator or budget fault (c) malformed output (d) a scorer bug

<details><summary>Answer</summary>

`b` - The oracle proves truth and scoring agree; it does not prove the answer is reachable through the tools.

If you answered differently, one counterexample: No investigator, however good, can cite a record the tools cannot return in time.

</details>

**Q10, smaller follow-up.** (failure_diagnosis) Does a high oracle score show that a budgeted investigator can solve the episode? (yes/no)

<details><summary>Answer</summary>

`no` - It shows the ceiling exists. Reachability under the budget is measured separately.

</details>

**Q11.** (training_vs_inference) You sample 8 answers per episode and report the best-scoring one. No weights change. This is (a) RL (b) SFT (c) best-of-N at inference (d) rollout logging

<details><summary>Answer</summary>

`c` - Selection can raise a displayed score without training anything.

If you answered differently, one counterexample: The model that produced the eight answers is byte-for-byte the model you started with.

</details>

**Q11, smaller follow-up.** (training_vs_inference) After best-of-N, has any weight changed? (yes/no)

<details><summary>Answer</summary>

`no` - Nothing was updated.

</details>

**Q12.** (training_vs_inference) You fine-tune a model to imitate 500 selected demonstration transcripts. This is (a) RL (b) SFT (c) best-of-N (d) prompt editing

<details><summary>Answer</summary>

`b` - Supervised fine-tuning imitates chosen outputs. RL instead uses the reward to shift action probabilities.

If you answered differently, one counterexample: No reward enters that loss: a demonstration with a wrong finding is imitated as faithfully as a right one.

</details>

**Q12, smaller follow-up.** (training_vs_inference) Does SFT change weights? (yes/no)

<details><summary>Answer</summary>

`yes` - It is training, but it is not reinforcement learning.

</details>

**Q13.** (training_vs_inference) You ran a policy, scored every rollout and wrote trajectories.jsonl. What has been trained? (a) nothing (b) the policy (c) the verifier

<details><summary>Answer</summary>

`a` - Sampling, scoring and logging produce evaluation or training data. Training needs a checkpoint you can update, tokenization, action masks, a loss, gradient steps and saved new weights.

If you answered differently, one counterexample: A closed API that only returns text gives you logs. Your local loop cannot update its weights.

</details>

**Q13, smaller follow-up.** (training_vs_inference) Which artifact proves training happened? (a) a JSONL of rewards (b) a new checkpoint that differs from the base

<details><summary>Answer</summary>

`b` - Changed weights, with the run that produced them, are the evidence.

</details>

**Q14.** (action_masks) In a multi-turn rollout the transcript mixes the policy's actions with tool results. The policy loss should cover (a) every token (b) only the tokens the policy generated (c) only the tool results

<details><summary>Answer</summary>

`b` - Tool results are environment output. Masking them keeps the update on what the policy actually chose.

If you answered differently, one counterexample: Without the mask you train the model to generate bank statements, as if records were its own actions.

</details>

**Q14, smaller follow-up.** (action_masks) Is the content of a get_document result a policy action? (yes/no)

<details><summary>Answer</summary>

`no` - It is an observation. The action was the request for it.

</details>

## Weak spots and drills

The runner ranks concepts by your own misses and prints the three weakest with their drills.

This page cannot do that for you: it has not seen your answers. All drills, by concept:

- **group_statistics**: Redo mean, population std and advantages for rewards [0.94, 0.54, 0.54, -1]. Check that the advantages sum to zero.
- **advantage_meaning**: Write two rollouts with equal reward where one wasted 20 inspections. Say what the update does to those wasted steps.
- **flat_groups**: For 10 groups of which 4 are flat, give the flat fraction, then list three causes you would check before filtering any group.
- **failure_diagnosis**: For each of bad policy, impossible task, malformed JSON and scorer bug, name the one log field or check that confirms it.
- **training_vs_inference**: Sort into 'weights change' and 'weights do not change': prompt editing, best-of-N, SFT, rollout logging, GRPO.
- **action_masks**: Mark each segment of a three-turn rollout as policy-generated or environment output, then say which segments carry loss.

## The toy group, computed

Rewards `[0.74, 0.34, -0.46, -1]`. Mean `-0.095`, population standard deviation `0.678`.

| Rollout | Reward | Deviation | Advantage |
|---|---|---|---|
| 1 | 0.74 | +0.835 | +1.232 |
| 2 | 0.34 | +0.435 | +0.642 |
| 3 | -0.46 | -0.365 | -0.538 |
| 4 | -1.00 | -0.905 | -1.335 |

Group-relative update, in one sentence: sampled actions from rollouts with positive advantage tend to
become more likely and those with negative advantage less likely, subject to the trainer's actual loss,
clipping and regularization. It says nothing about which single inspection earned the reward.

A flat group, all -1 or all +0.94, has zero reward advantage for every rollout. That is a prompt to
diagnose, not a verdict: other loss terms may still be non-zero, and dropping flat groups silently
changes the training distribution.

These numbers are arithmetic. Nothing in this repository was trained.
