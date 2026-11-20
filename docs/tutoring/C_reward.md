# Prompt C - derive the reward

Six cases, one at a time, then two questions on clipping and clean-case frequency. You compute the counts, F1 and the reward before anything is checked. Answers within 0.001 are accepted.

Run it interactively, one question at a time, answers checked only after you type yours:

```
uv run python -m genesis_audit tutor C
```

## Teaching assumptions (not Genesis rules)

- This is the exact teaching reward of prompt C, which is also the draft's proposed common reward.
- No smooth partial credit for amounts: a finding is a true positive or it is not.
- The step cost uses inspection steps only; the submit step is not charged.

## Questions

**Q1.** (reward_arithmetic) Truth has 3 issues. The agent submits all 3, each fully supported. The agent used 30 inspection steps. Give TP FP FN F1 reward (five numbers).

<details><summary>Answer</summary>

`3  0  0  1  0.94` - F1 = 1 and reward = 47/50 = 0.940. Accuracy dominates: the only loss is the step cost, 0.002 x 30 = 0.06.

If you answered differently, one counterexample: A perfect answer is not 1.0 here: 30 inspections cost 0.06.

</details>

**Q1, smaller follow-up.** (reward_arithmetic) Give just the counts for that case: TP FP FN (three numbers).

<details><summary>Answer</summary>

`3  0  0` - Counts come first; F1 and the reward are arithmetic on them.

</details>

**Q2.** (false_negatives) Truth has 3 issues. The agent submits 2 of them, fully supported, and nothing else. The agent used 30 inspection steps. Give TP FP FN F1 reward (five numbers).

<details><summary>Answer</summary>

`2  0  1  0.8  0.54` - F1 = 4/5 and reward = 27/50 = 0.540. One missed issue costs 0.4 of reward at this size.

If you answered differently, one counterexample: The missed issue is a false negative, not a false positive: nothing false was claimed.

</details>

**Q2, smaller follow-up.** (false_negatives) Give just the counts for that case: TP FP FN (three numbers).

<details><summary>Answer</summary>

`2  0  1` - Counts come first; F1 and the reward are arithmetic on them.

</details>

**Q3.** (false_positives) Truth has 3 issues. The agent submits all 3, plus one claim about a clean invoice. The agent used 30 inspection steps. Give TP FP FN F1 reward (five numbers).

<details><summary>Answer</summary>

`3  1  0  0.857143  0.654286` - F1 = 6/7 and reward = 229/350 = 0.654. One false claim on top of a perfect answer costs about 0.29.

If you answered differently, one counterexample: The extra claim does not reduce TP. It adds one FP, which lowers precision and F1.

</details>

**Q3, smaller follow-up.** (false_positives) Give just the counts for that case: TP FP FN (three numbers).

<details><summary>Answer</summary>

`3  1  0` - Counts come first; F1 and the reward are arithmetic on them.

</details>

**Q4.** (duplicates) Truth has 3 issues. The agent submits all 3, then repeats the first one word for word. The agent used 30 inspection steps. Give TP FP FN F1 reward (five numbers).

<details><summary>Answer</summary>

`3  1  0  0.857143  0.654286` - F1 = 6/7 and reward = 229/350 = 0.654. A repeat is scored exactly like a false claim: matching is one-to-one, so it earns nothing and costs precision.

If you answered differently, one counterexample: TP cannot exceed the number of truth issues. The repeat is the fourth finding and has no issue left to match.

</details>

**Q4, smaller follow-up.** (duplicates) Give just the counts for that case: TP FP FN (three numbers).

<details><summary>Answer</summary>

`3  1  0` - Counts come first; F1 and the reward are arithmetic on them.

</details>

**Q5.** (clean_cases) Truth is empty: the books are clean. The agent submits an empty findings list. The agent used 30 inspection steps. Give TP FP FN F1 reward (five numbers).

<details><summary>Answer</summary>

`0  0  0  1  0.94` - F1 = 1 and reward = 47/50 = 0.940. Truth and findings both empty is the explicit special case F1 = 1. Correct abstention scores like a perfect find.

If you answered differently, one counterexample: 0/0 is not scored as 0 here. Without the special case, a correct 'nothing wrong' would be punished.

</details>

**Q5, smaller follow-up.** (clean_cases) Give just the counts for that case: TP FP FN (three numbers).

<details><summary>Answer</summary>

`0  0  0` - Counts come first; F1 and the reward are arithmetic on them.

</details>

**Q6.** (flag_all) Truth has 3 issues. The agent submits 30 findings, the cap: the 3 right ones and 27 others. The agent used 30 inspection steps. Give TP FP FN F1 reward (five numbers).

<details><summary>Answer</summary>

`3  27  0  0.181818  -0.696364` - F1 = 2/11 and reward = -383/550 = -0.696. Finding everything by accusing everything scores far below finding two of three honestly.

If you answered differently, one counterexample: Recall is 1, but F1 also counts the 27 false positives. Volume is not rewarded.

</details>

**Q6, smaller follow-up.** (flag_all) Give just the counts for that case: TP FP FN (three numbers).

<details><summary>Answer</summary>

`3  27  0` - Counts come first; F1 and the reward are arithmetic on them.

</details>

**Q7.** (clipping) Truth has 3 issues. The agent submits nothing after 30 inspections. Give the reward before clipping and the reward after clipping (two numbers).

<details><summary>Answer</summary>

`-1.06  -1` - 2 x 0 - 1 - 0.06 = -1.06, clipped to -1. The step cost disappears below the floor.

If you answered differently, one counterexample: A malformed submission is also exactly -1, so after clipping these two failures look identical.

</details>

**Q7, smaller follow-up.** (clipping) What is F1 when truth has 3 issues and the submission is empty?

<details><summary>Answer</summary>

`0` - TP = 0, so F1 = 0. Only the both-empty case is 1.

</details>

**Q8.** (clean_cases) A lazy policy always submits an empty list with zero inspections. Of 20 episodes, 5 are clean and 15 have 3 issues each. What is its mean reward?

<details><summary>Answer</summary>

`-0.5` - (5 x 1 + 15 x (-1)) / 20. With a clean share p the lazy mean is 2p - 1.

If you answered differently, one counterexample: If all 20 episodes were clean, this policy would average +1 while doing no auditing at all.

</details>

**Q8, smaller follow-up.** (clean_cases) What does that policy score on one clean episode, with zero inspections?

<details><summary>Answer</summary>

`1` - F1 = 1 by the special case and there is no step cost.

</details>

## Weak spots and drills

The runner ranks concepts by your own misses and prints the three weakest with their drills.

This page cannot do that for you: it has not seen your answers. All drills, by concept:

- **reward_arithmetic**: Recompute the perfect case at 0, 50 and 99 inspections. State the price of 50 extra inspections.
- **false_negatives**: Truth has 4 issues. Tabulate F1 and reward at 30 inspections for 4, 3, 2, 1 and 0 found, with no false claims.
- **false_positives**: Find 2 of 3 and add 1 false claim, at 30 inspections. Compare with finding 2 of 3 and stopping.
- **duplicates**: Submit one correct finding five times on books with one issue. Give TP, FP, FN and the reward at 10 inspections.
- **clean_cases**: For clean shares 0%, 25%, 50% and 75%, give the mean reward of always-abstain at zero inspections.
- **flag_all**: With a cap of 30 findings and 12 real issues all included, what is the best reward flag-all can reach at 40 inspections?
- **clipping**: List three different failures that all return exactly -1, and one logged field that tells each apart.

## The reward, computed

`F1 = 2TP / (2TP + FP + FN)`; `reward = clip(2*F1 - 1 - 0.002*n, -1, 1)`; both empty gives `F1 = 1`;
a malformed final submission is `-1` directly. Evidence-invalid and repeated claims are false positives.

Calculated at n = 30 inspections by `genesis_audit.scoring`. These are worked examples, not measured runs.

| Behaviour | TP / FP / FN | F1 | Reward | Before clipping |
|---|---|---|---|---|
| Find all 3, supported | 3 / 0 / 0 | 1.000 | 0.940 | 0.940 |
| Find 2 of 3 | 2 / 0 / 1 | 0.800 | 0.540 | 0.540 |
| Find 2, add 1 false claim | 2 / 1 / 1 | 0.667 | 0.273 | 0.273 |
| Find 3, submit 27 false claims | 3 / 27 / 0 | 0.182 | -0.696 | -0.696 |
| Abstain on faulty books | 0 / 0 / 3 | 0.000 | -1.000 | -1.060 |
| Correctly abstain on clean books | 0 / 0 / 0 | 1.000 | 0.940 | 0.940 |
| One false claim on clean books | 0 / 1 / 0 | 0.000 | -1.000 | -1.060 |

## Discussion

**Abstaining on faulty books, one false claim on clean books and a malformed submission all return -1. What does that do to learning, and what would you log?**

<details><summary>One sound answer</summary>

Clipping maps different failures to one number, so the reward cannot say which failure is less bad, and a group made only of such rollouts has zero reward advantage. Log TP, FP, FN, the value before clipping, the inspection count and the termination cause, and diagnose from those. Do not change the common reward to fix it.

</details>

**How does the share of clean episodes change what a lazy policy learns?**

<details><summary>One sound answer</summary>

With no clean episodes, accusing something is never punished by a clean case, and abstaining is never right. With mostly clean episodes, always-abstain averages 2p - 1 and looks good while auditing nothing. Clean cases make always-accuse lose and faulty cases make always-abstain lose: both must be present, and the clean-case false-positive rate should be reported on its own.

</details>
