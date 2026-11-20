# Grading criteria

## RL environment for synthetic financial-audit models

**Team Intuition internal verification rubric.** It evaluates our *environment*: generator, tools, hidden verifier, and scoring against the five core categories and requirements of the Genesis Hackathon 2026 FinTech case [S1].

## How to use it

1. Work from a fresh checkout. After dependencies are installed, turn the network off.
2. Run the team's documented one-command check. If it fails, stop: see *Blockers*.
3. For each criterion, find the named test, command or artifact and reproduce it yourself.
4. In each category, make two spot attacks of your own, for example: repeat a correct finding, change its currency, cite an invented evidence id, send an action after submit.
5. Fill in the score sheet. Write the command you used next to each score.
6. Have someone other than the author do the grading. A score the author gives their own work is a self-assessment.

**Scoring one criterion**

| Score | When |
|---|---|
| Full points | You reproduced the evidence, and a test or command pins the behaviour. |
| Half points | The behaviour is there, but no test pins it, or the evidence covers only part of the criterion. |
| Zero | Absent, not reproducible, or only claimed. A claim without a command, artifact or measured result scores zero. |

**Stages.** Every criterion carries a stage tag.

- **S (slice)** can be met by a generic engine and one vertical slice: one error family, one hand-verified episode and its clean twin. 63 points.
- **B (breadth)** needs the released case: a seeded generator, four families, interaction scenarios, shipped episodes. 37 points.

Report two numbers: **Stage 1 = S points earned / 63** and **Full case = all points earned / 100**. A team is ready to start breadth when every blocker is clear and Stage 1 is at least 54 / 63 (85%).

## Blockers

No score is recorded until each of these is repaired [S1, section 7]:

- the policy can reach truth, provenance or a private seed by any path;
- the policy can write to the scorer or to evaluator files;
- any real company, person, bank, card or payment data is present;
- the core does not run from a fresh checkout.

**Never rewarded:** interface polish; model training without a controlled held-out comparison; difficulty that comes from contradictory or unsolvable data; a high oracle score by itself.

## A. Contract and isolation - 25 points

| ID | Stage | Pts | Criterion | Evidence to reproduce |
|---|---|---|---|---|
| A1 | S | 3 | **Lifecycle contract.** `reset` returns task, manifest, policy summary and remaining budget. `step` returns observation, reward, terminated, truncated, info. Every value is JSON-serializable. Inspection reward is exactly 0. | A scripted episode and a schema test. |
| A2 | S | 3 | **Budget and termination.** The step total includes the submit. A submit on the last allowed step is accepted. An inspection that exhausts the budget gives `truncated` with an empty final submission. A wall-time limit also truncates. The precedence rule is written down. | Tests for the last-step submit, the exhausting inspection and the time limit. |
| A3 | S | 3 | **Narrow, bounded tools.** Only list, get record, get document, calculator and submit. Pages hold at most 50 rows and cursors are stable. An unknown id or action returns a bounded error and costs a step. No shell, SQL, filesystem or network tool. | Tool tests; error messages come from a closed list. |
| A4 | S | 2 | **The calculator is a parser.** Decimal arithmetic only. Names, calls, attributes and imports are rejected. Length, nesting and magnitude are bounded. | A test in which an injection attempt provably executes nothing. |
| A5 | S | 3 | **Malformed final versus invalid inspection.** A malformed final submission ends the episode at -1, and its validation error appears only in the evaluator log. An invalid inspection action costs a step and does not end the episode. The caps of 30 findings, 10 evidence ids and 1,000 characters are enforced. | One test per branch and per cap. |
| A6 | S | 2 | **One submission, isolated resets.** Nothing is accepted after the end and the score cannot change. Each reset starts from fresh state. | After-submit and after-truncation tests. |
| A7 | S | 3 | **Enforced truth boundary.** The policy runs outside the evaluator process and cannot read truth, provenance or seeds because of operating-system permissions, a sandbox or mounts. A module or package name is not a boundary. It also cannot kill, stall or exhaust the evaluator: a policy that never reads, never answers, floods, or leaves a child process behind ends in a defined way. | A probe policy that tries and fails under confinement, and succeeds with confinement off. Hostile policies run under the real boundary. A written statement of what the containment does and does not protect. |
| A8 | S | 2 | **No leak through outputs or process metadata.** Observations, info, errors, exception text and policy-visible logs contain no truth, issue ids, private paths or seeds. Private ids do not encode the answer. The evaluator's command line carries no episode name or seed. Evaluation mode withholds reward and diagnostics until the run ends. | A canary scan over everything a policy received; a probe that looks for a needle in the evaluator's arguments. |
| A9 | B | 4 | **Contract at case scale.** All of the above on 200 to 2,000-row episodes. Paging cost is measured. Every labelled issue is reachable within 100 steps through the real tools. Time and memory are measured at the largest size. | Measured run at maximum size inside the stated envelope. |

## B. Data and truth - 25 points

| ID | Stage | Pts | Criterion | Evidence to reproduce |
|---|---|---|---|---|
| B1 | S | 2 | **Causal construction.** Latent history first, then derived clean records, then a typed mutation with before and after values recorded. Truth is computed from the resulting discrepancy, not copied from the mutation label and never asked of a language model. | Builder code and provenance file; undoing the provenance gives the clean books. |
| B2 | S | 2 | **Accounting identities.** Declared identities are checked in code before and after injection. The check can fail. The documentation states that balanced books can still be wrong. | Identity test with a corrupted ledger. |
| B3 | S | 2 | **Solvable from public evidence.** Each issue is decidable from records the tools return. Evidence sets cite only reachable ids. An episode whose truth needs an unpublished fact, or that no well-formed finding could match, is rejected at build or load. A policy that reads no truth solves it within the budget. | Refusal tests; a truth-blind solver's measured score. |
| B4 | S | 2 | **Independent validation.** A checker that shares no code with the generator or verifier, ideally written by someone else, re-derives truth from public records. Each implemented family has a hand-calculated fixture. The checker is shown to fail on corrupted input. | Checker run on good and corrupted episodes. |
| B5 | S | 1 | **Money and time semantics.** Integer minor units. Declared exponents, not assumed to be 2. Decimal-string rates with a stated direction. Declared rounding. Offsets on every timestamp. A period and timezone policy. | Conversion tests with exponents 0 and 2. |
| B6 | B | 4 | **Seeded generator.** Consistent synthetic companies in the 200 to 2,000-row range from a seed and a config. No real data. | Generated episodes pass the identity and independent checks. |
| B7 | B | 6 | **Four families.** Duplicate invoice; missing or partial allocation; FX rate or date mismatch; period cutoff. Each is independently configurable and has published amount, affected-id and evidence conventions, a hand-verified fixture and an independent check. 1.5 points each. | One fixture and checker run per family. |
| B8 | B | 2 | **Clean cases and valid decoys.** Clean companies; split payments, refunds and legitimate repeats. Each decoy shares the suspicious surface feature of its error twin. | Baselines on clean and decoy episodes. |
| B9 | B | 2 | **Interaction scenarios.** At least two. Overlapping rows are defined so that one discrepancy is not counted twice. | Hand-verified interaction fixtures. |
| B10 | B | 2 | **Shortcut audit.** Error position, ids, filenames, currencies and templates carry no label. Nuisance features are counterbalanced. Random and flag-all baselines stay low. | Shortcut tests and baseline results. |

## C. Reward integrity - 25 points

| ID | Stage | Pts | Criterion | Evidence to reproduce |
|---|---|---|---|---|
| C1 | S | 3 | **Exact common reward.** `F1 = 2TP/(2TP+FP+FN)`; `reward = clip(2*F1 - 1 - 0.002*inspection_steps, -1, 1)`. Both-empty gives F1 = 1. Undefined precision or recall is 0. The cost uses inspection steps only. Malformed is -1. | A hand-computed table reproduced by tests. |
| C2 | S | 5 | **Strict true positives.** Type, affected ids, currency, amount tolerance and complete evidence are each individually necessary. No partial credit. One invented evidence id voids the finding. | One failing case per condition. |
| C3 | S | 4 | **One-to-one maximum matching.** Repeats earn nothing and count as false positives. A case where greedy matching depends on order is tested. Counts are invariant under every permutation. Tie-breaking is published. | Permutation and greedy-counterexample tests. |
| C4 | S | 4 | **Behaviours the case requires**, on the real environment: supported findings beat abstention on faulty books; abstention beats false alarms on clean books; a valid flag-all at the cap scores poorly; fewer inspections separate equal results only slightly. The lazy cases are measured and reported too: always-abstain, and a policy that never acts. | Four environment-level tests; the lazy rows in the result sheet. |
| C5 | S | 1 | **Tolerance boundary.** Just inside passes, just outside fails, as declared. | Boundary test. |
| C6 | S | 1 | **Prose is not scored.** The explanation never changes a score. | Test with a persuasive wrong claim. |
| C7 | S | 1 | **Raw components kept.** TP, FP, FN, F1, the value before clipping, inspections and termination cause are in the evaluator report. An experimental reward, if any, is reported beside the common one, never instead of it. | Evaluator report. |
| C8 | B | 4 | **Attack matrix per family.** The same attacks pass for all four families and for the interaction scenarios. | Per-family attack tests. |
| C9 | B | 2 | **Published semantics for every family.** Amount meaning, sign, tolerance and canonical affected ids for all four. Unresolved official rules are listed as questions, not presented as rules. | Spec. |

## D. Reproducibility and generalization - 15 points

| ID | Stage | Pts | Criterion | Evidence to reproduce |
|---|---|---|---|---|
| D1 | S | 3 | **Exact replay.** The same seed, config, version and actions give byte-identical records, transitions and rewards. A tampered log is detected. Digests are committed, so a second machine or Python version can be checked against them. | Replay command; tamper test; committed digests reproduced elsewhere. |
| D2 | S | 2 | **Id and order invariance.** Consistent id renaming plus row shuffling preserves the oracle's findings, after renaming, and its reward. Truth derived again from the perturbed records equals the renamed truth. A real policy's F1 and step count are compared separately. | Paired perturbation test. |
| D3 | S | 2 | **Determinism hygiene.** Local seeded randomness, no global generator. Canonical serialization. Stable ordering. Lockfile. Committed fixtures regenerate byte for byte. | Regeneration test. |
| D4 | S | 1 | **No seed leakage.** The seed is absent from everything the policy sees. Episode ids and renamed ids cannot be inverted to the seed without an evaluator secret. | Leak test. |
| D5 | B | 2 | **Reproducible generation.** The same seed and config give identical episodes on another machine and Python patch version. | Cross-environment digest. |
| D6 | B | 3 | **Paired checks at scale.** 20 id and order pairs over generated episodes pass. | Paired run. |
| D7 | B | 2 | **Split discipline.** 10 train and 10 dev episodes are shipped. Held-out seeds and configurations are separate. Related variants stay in one split. | Episode manifests and split file. |

## E. Engineering and explanation - 10 points

Five criteria, each 0, 1 or 2 [S1]. Level 1 is reachable at stage S. Level 2 needs the whole case, except E2.

| ID | Criterion | 1 point | 2 points |
|---|---|---|---|
| E1 | **One-command run** | One command on a fresh checkout reproduces every number reported for the slice, offline. | The same for the whole case, inside the stated envelope, with container instructions. |
| E2 | **Versioned configuration** | Environment, schema and policy versions appear in manifests and logs. | Plus a dependency lockfile and a license. Both points are stage S. |
| E3 | **Trajectory logs** | `trajectories.jsonl` has episode id, step, action, observation, reward, terminated, truncated. The policy-visible view is separate from evaluator diagnostics. | The same for all four baselines over the shipped episodes. |
| E4 | **Measured failure analysis** | Four baseline policies measured on the same episodes. One failed trajectory traced to its earliest externally visible failure, with a patch and a regression test. | A result sheet per family, with clean and interaction status, mean episode F1 and pooled F1. |
| E5 | **Honest limitations** | States what is not built, what the containment does not protect, and which numbers are calculated rather than measured. Says what a memoriser would score. No training claim without a controlled comparison. | Also covers the generator's limits and the open official questions. |

## Point summary

| Category | S | B | Total |
|---|---|---|---|
| A. Contract and isolation | 21 | 4 | 25 |
| B. Data and truth | 9 | 16 | 25 |
| C. Reward integrity | 19 | 6 | 25 |
| D. Reproducibility and generalization | 8 | 7 | 15 |
| E. Engineering and explanation | 6 | 4 | 10 |
| **Total** | **63** | **37** | **100** |

## Score sheet

| ID | Available | Earned | Command or artifact used |
|---|---|---|---|
| A1 - A9 | 25 | | |
| B1 - B10 | 25 | | |
| C1 - C9 | 25 | | |
| D1 - D7 | 15 | | |
| E1 - E5 | 10 | | |
| **Stage 1 (S only)** | **63** | | |
| **Full case** | **100** | | |

Blockers found: ____ . Spot attacks tried: ____ .

## Limits of this rubric

An independent grader used this rubric on its author's own repository and was asked to criticise the instrument. Its main points, kept here so that nobody mistakes the rubric for more than it is:

- **The stage split fits the author's build plan.** Stage S describes what a generic engine and one slice can reach, which is where the author's repository stood. Only 36% of "data and truth" is stage S, against 84% of "contract and isolation". The 85% gate is a number the author set. **For comparing teams, use the 100-point total and the blockers, not the stage score.**
- **Some criteria assume one design.** B1 expects recorded before and after values; D4 expects keyed id renaming; C3 pays for maximum matching even where a team forbids ambiguous truth outright, which is an equally sound answer. A3, A5, E3 and E4 fix tool names, caps, a file name and a baseline count: those are taken from the draft case [S1], which is not part of the graded repository, so check them against the case you were actually given.
- **Some criteria are easy.** A1, A6, C5, C6 and C7 are 8 points that any strict environment has. B5 can be met by a conversion helper that no scored path uses. E5 pays for listing limits and cannot tell whether the list is complete.
- **Things a good environment needs that are not asked for:** evidence of learning signal, such as reward spread across policies and the share of flat groups; more than one latent company before breadth; a spread of difficulty; throughput; an adapter for a real agent; uncertainty on the result sheet; proof that each check can fail; a threat model that names the reference backend; and a rule for a tree that is not committed.
- **A passing probe is not the property.** A8 was first met by a probe that looked in one place while the leak was in another. Grade the property with an attack of your own, not the team's own test.

## Sources

- [S1] Genesis FinTech case specification: the five categories, their weights, the blockers and the behaviours listed under C4.
- Official Genesis Hackathon check definitions and evaluation criteria (20 November 2026).
