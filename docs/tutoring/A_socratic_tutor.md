# Prompt A - Socratic tutor: RL environment design for a synthetic audit task

Ten questions, one at a time. Answer with a letter, a number, or yes/no; no reasoning is asked for. A wrong answer gets one counterexample and a smaller question.

Run it interactively, one question at a time, answers checked only after you type yours:

```
uv run python -m genesis_audit tutor A
```

## Teaching assumptions (not Genesis rules)

- KZT and USD have exponent 2 and JPY has exponent 0 in these questions.
- The FX rates 500, 490 and 3.30 are invented, and are quoted as KZT per one unit of the foreign currency.
- The cutoff questions assume a policy of recognising a service at completion time in a +05:00 company timezone. The draft case schema has no completion-time field, so this is an assumption of the exercise.
- Ids such as I7, P9 and L11 follow the guide's worked example, not an official fixture.

## Questions

**Q1.** (state_vs_observation) At reset the agent receives the task, manifest, policy summary and remaining budget. Which of these belongs to the STATE but not to the OBSERVATION? (a) the reporting period (b) the remaining step budget (c) the list of injected errors (d) the rounding policy

<details><summary>Answer</summary>

`c` - The state is the whole world, including hidden errors; the observation is only what was exposed.

If you answered differently, one counterexample: If the injected-error list were observable, a policy could submit it with zero inspections and score the maximum. The environment would then measure nothing.

</details>

**Q1, smaller follow-up.** (state_vs_observation) The agent has not fetched ledger row L11 yet. L11's credit amount is in (a) the state only (b) the observation only (c) both

<details><summary>Answer</summary>

`a` - It exists in the world, but no tool has returned it yet.

</details>

**Q2.** (roles) A fixed script lists invoices, payments and ledger rows, reconciles them and submits findings. No weights change. It is (a) a trainer (b) a policy (c) a verifier (d) a transition

<details><summary>Answer</summary>

`b` - Anything that chooses the next action is a policy, scripted or learned.

If you answered differently, one counterexample: A trainer changes a policy using many scored rollouts. This script changes nothing; it only acts.

</details>

**Q2, smaller follow-up.** (roles) Sampling 8 answers and keeping the best-scoring one, with no weight update: is that training? (yes/no)

<details><summary>Answer</summary>

`no` - That is best-of-N selection at inference time. The weights are unchanged.

</details>

**Q3.** (transition_and_budget) The budget is 100 steps and 11 are used. The agent calls get_record with an id that does not exist. How many steps remain after the call?

<details><summary>Answer</summary>

`88` - An unknown id returns a bounded error and still consumes a step.

If you answered differently, one counterexample: If failed lookups were free, a policy could probe guessed ids without limit.

</details>

**Q3, smaller follow-up.** (transition_and_budget) What reward does that failed lookup return?

<details><summary>Answer</summary>

`0` - Every inspection step returns reward 0, successful or not. Only the terminal step is scored.

</details>

**Q4.** (roles) Which component may read truth.json? (a) the policy, to check its work (b) the tool bridge, to filter records (c) the verifier, to score the final submission (d) the trainer, to build prompts

<details><summary>Answer</summary>

`c` - Truth becomes a scalar reward after submission. It never becomes policy input.

If you answered differently, one counterexample: A trainer that puts truth into prompts has leaked the labels into the policy's input.

</details>

**Q4, smaller follow-up.** (roles) truth.json is moved into another Python module of a package the agent can read. Is it hidden now? (yes/no)

<details><summary>Answer</summary>

`no` - A module or a package is not a permission boundary. A readable file is a readable file.

</details>

**Q5.** (allocation_arithmetic) Invoice I7 is 100,000 minor units. Bank document P9 proves a 100,000 receipt for I7. The ledger allocates 60,000 of P9 to I7 and nothing else. What is the discrepancy, in minor units?

<details><summary>Answer</summary>

`40000` - Required allocation 100,000 minus recorded allocation 60,000.

If you answered differently, one counterexample: The whole payment is not the discrepancy, because 60,000 was allocated correctly. And 40,000 KZT would be 4,000,000 minor units at exponent 2.

</details>

**Q5, smaller follow-up.** (allocation_arithmetic) What should I7's outstanding balance be after P9, in minor units?

<details><summary>Answer</summary>

`0` - The receipt covers the invoice in full, so nothing should remain open.

</details>

**Q6.** (decoys) Invoice I3 is 100,000. Two bank receipts for I3 arrive, 60,000 and 40,000, and each is allocated to I3 in full. How many findings should you submit for I3?

<details><summary>Answer</summary>

`0` - A split payment that is fully allocated is valid. Same invoice, same total, no error.

If you answered differently, one counterexample: Flagging it is a false positive. On otherwise clean books one false claim takes F1 from 1 to 0.

</details>

**Q6, smaller follow-up.** (decoys) What is I3's recorded outstanding balance after both receipts, in minor units?

<details><summary>Answer</summary>

`0` - 60,000 + 40,000 settles the 100,000 invoice.

</details>

**Q7.** (fx_units) A payment of USD 100.00 must be translated at the payment-date rate of 500 KZT per USD. The ledger used 490. What is the discrepancy in KZT minor units?

<details><summary>Answer</summary>

`100000` - Correct 5,000,000 minus booked 4,900,000 KZT minor units.

If you answered differently, one counterexample: 1,000 is the gap in KZT major units (10 KZT x 100 USD). Findings use minor units: x 100.

</details>

**Q7, smaller follow-up.** (fx_units) What is the correct base amount, in KZT minor units?

<details><summary>Answer</summary>

`5000000` - (10,000 / 10^2) x 500 x 10^2.

</details>

**Q8.** (fx_units) A payment of JPY 10,000 (exponent 0, so 10,000 minor units) is translated at 3.30 KZT per JPY into KZT (exponent 2). What is the base amount in KZT minor units?

<details><summary>Answer</summary>

`3300000` - (10,000 / 10^0) x 3.30 x 10^2. The source exponent is 0, not 2.

If you answered differently, one counterexample: Assuming two decimals reads 10,000 minor units as JPY 100.00 and gives 33,000: wrong by 100x.

</details>

**Q8, smaller follow-up.** (fx_units) How many whole KZT (major units) is that?

<details><summary>Answer</summary>

`33000` - Divide KZT minor units by 10^2.

</details>

**Q9.** (cutoff_timezone) Policy: recognise a service at completion, in the company timezone (+05:00). The period ends 2026-10-31T23:59:59+05:00. A service is completed at 2026-10-31T20:30:00+00:00. Which period does it belong to? (a) October (b) November

<details><summary>Answer</summary>

`b` - In company time the completion is 2026-11-01T01:30:00+05:00.

If you answered differently, one counterexample: Reading the UTC date as the local date moves a November event into October.

</details>

**Q9, smaller follow-up.** (cutoff_timezone) What is the local hour (0-23) of that completion in the company timezone?

<details><summary>Answer</summary>

`1` - 20:30 UTC plus five hours.

</details>

**Q10.** (evidence_sufficiency) Under that completion policy you suspect a posting sits in the wrong period. Which public fact is indispensable evidence? (a) the invoice due date (b) the invoice amount (c) the service completion time (d) the customer id

<details><summary>Answer</summary>

`c` - The policy is defined on completion time, so only that fact, the posting and the policy decide it.

If you answered differently, one counterexample: An invoice issued on 30 October for a service completed on 2 November looks like October by invoice date and is November under the policy.

</details>

**Q10, smaller follow-up.** (evidence_sufficiency) If no public record carries a completion time, is that issue decidable by the agent? (yes/no)

<details><summary>Answer</summary>

`no` - Then the fixture is unsolvable and must be repaired; a decisive fact may not live only in truth.

</details>

## Weak spots and drills

The runner ranks concepts by your own misses and prints the three weakest with their drills.

This page cannot do that for you: it has not seen your answers. All drills, by concept:

- **state_vs_observation**: For the teaching episode write two lists: what is in the state at reset, and what is in the observation at reset. Repeat after one list_records call on the ledger.
- **roles**: Label each as generator, environment, verifier, policy or trainer: a mutation that removes an allocation; the step budget counter; maximum matching of findings to truth; a reconciliation script; an optimizer that updates weights from scored rollouts.
- **transition_and_budget**: With a 100-step budget, compute steps_remaining and inspection_steps after 3 list calls, 1 unknown id and 1 submit. Then say what happens if step 100 is a list call rather than a submit.
- **allocation_arithmetic**: Invoice 80,000; one receipt of 80,000; recorded allocation 50,000: give the discrepancy. Now take two receipts of 50,000 and 45,000 with allocations 50,000 and 30,000 under an 'allocate up to the open balance' policy: explain what the remaining 15,000 is.
- **decoys**: Name three valid situations that look like errors (split payment, a legitimately repeated monthly amount, an unpaid invoice with no receipt) and the single record that separates each from its error twin.
- **fx_units**: Convert EUR 250.50 (exponent 2) at 560.25 KZT per EUR into KZT minor units with half-up rounding. Then redo it when the rate is quoted as EUR per KZT, and state which direction your formula expects.
- **cutoff_timezone**: For a period ending 2026-10-31T23:59:59+05:00, classify 2026-10-31T18:59:59+00:00 and 2026-10-31T19:00:00+00:00 as inside or outside the period.
- **evidence_sufficiency**: For each family (duplicate, allocation, FX, cutoff) write the minimum evidence set, and one tempting record that is not sufficient on its own.
