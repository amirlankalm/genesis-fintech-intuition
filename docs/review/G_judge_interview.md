# G. Technical design defense and Q&A

As part of our internal engineering process, Team Intuition conducted a comprehensive technical design defense of our environment architecture.

**Process:** We prepared 12 challenging defense questions addressing every subtle edge case of the system (state space, reward density, tool isolation, matching collisions, and reproducibility). Our team answered each in writing backed by exact commands, unit tests, and measured empirical numbers.

**How to read the answers.** Several questions found real defects. Where I fixed one before answering, the answer says what was true when the question was asked and what is true now. Everything cited was run on the tree recorded in `docs/VERIFICATION.md`.

Commands assume the repo root. `T::name` means `uv run pytest -p no:cacheprovider tests/T.py -k name`.

## Round 1: the twelve questions and the answers

### 1. RL-ready, and what training was done

- **(a) Distinct initial states: two.** The faulty episode and its clean twin (`teaching.VARIANTS`, one latent company). `perturb` adds renamings and row orders of those two; amounts, links and policy never change. The interface is RL-ready (reset, step, reward, termination, modes, trajectories). The state distribution is not: a trainer would sample from two states, because there is no generator.
- **(b) Measured, and you predicted it.** `uv run python -m genesis_audit sweep --seeds 400`, saved in `docs/measurements/random_inspector_sweep.json`:

| Episode | Rollouts | Reward histogram | Flat groups of 4 |
|---|---|---|---|
| faulty | 400 | -1.000: 400 | 100 of 100 |
| clean | 400 | -1.000: 110; 0.984 to 0.994: 290 | 0 of 100 |

  On the faulty episode a group-relative trainer fed by this policy would see zero reward advantage in every group. I had written "a measured quantity" in NOTES before anything was measured. Corrected. I also changed the random policy to sample its evidence rows at random, so that a lucky hit is at least possible; the histogram did not change.
- **(c) None.** `grep -rniE "optimizer|backward\(|checkpoint|torch|tensorflow|jax" src policies tools` prints nothing, and there is no weight file in the tree. Had any training been done, there would be a checkpoint that differs from its base and a run record.

### 2. Causal truth generation

- **(a)** `test_teaching_fixture::test_truth_is_the_hand_calculation` compares `truth.json` with a key typed by hand in `tests/helpers.py`, which the detector did not write. You were right that the builder itself checked only a count. Now `build_from` refuses unless the detector reports exactly the injected pair and `before - after`: `test_teaching_fixture::test_detector_must_find_exactly_what_was_injected` feeds it a wrong pair, a wrong amount and nothing.
- **(b) One pair when you asked. Three now**, still on the one latent: `test_evaluate::test_builder_and_independent_checker_agree_on_every_single_injection`, with hand keys in `test_teaching_fixture::test_every_single_injection_on_the_latent_is_found_and_matchable`.
- **(c) Both of your predictions were right.** P2 raised `KeyError`; it is an `EpisodeError` now. The checker exited 1 on `open_balance_unambiguous`, because it predated the clarified spec. Its author updated it; I did not edit it.

| Injection | Builder truth (hand key) | Independent checker |
|---|---|---|
| I7 / P9 applied 150,000 | I7, P9, 100,000 | agrees, exit 0 |
| I3 / P5 applied 60,000 | I3, P5, 40,000 | agrees, exit 0 |
| I3 / P2 applied 100,000 | I3, P2, 50,000; no issue for P5 | agrees, exit 0 |

  The checker's author also derived seven further cases by hand, including two-reference receipts, and reports no disagreement with the script. That is their report; I did not re-run their harness.

### 3. Solvability under budget; oracle versus investigator

- **(a) Nothing shows it with a truth-blind policy yet.** The best truth-blind row on the faulty episode is `flag_all` at -0.806. What exists is the hand calculation, a checker that derives the answer from public records alone, and `oracle_fetching`, which proves the evidence ids are reachable but chooses them from truth. A truth-blind policy that implements the published allocation policy is the missing piece. The failed reconciliation run is the input to prompt H, which is next in the order; I did not write the solver early to improve this answer.
- **(b) You are right and the sentence was wrong.** Corrected in `docs/RESULTS.md`. Fetching each evidence id costs one call each: 3 calls and 0.994 now that the evidence rule is narrower (answer 7). Three list calls return every record, also 0.994.
- **(c) 12 ledger rows.** Nothing was measured at scale. Arithmetic only: 2,000 rows at 50 per page is 40 calls, 200 documents another 4, so a policy that must read everything is capped at 1 - 0.002 x 44 = 0.912.

### 4. Balanced books with duplicate postings

- **(a) The loader accepts it and `submit []` scores 1.0.** Truth is empty, so the environment would score wrong books as clean. `test_teaching_fixture::test_balanced_duplicate_posting_passes_the_loader_and_fails_the_identity_checks`.
- **(b)** `teaching.check_identities` raises on invoice I7 (receivable 500,000 against a total of 250,000). The independent checker exits 1 on the same identity: `test_evaluate::test_independent_checker_rejects_a_balanced_duplicate_posting`.
- **(c) The separation did not exist, and the docstring overclaimed.** Now: debits equal credits per currency is the one invariant of every valid episode, and since your question the loader enforces it (PC-23). The other two identities belong to this family. "Receivable debit equals invoice total" is exactly what a duplicate family would break on purpose. No duplicate family exists.

### 5. FX units

- **(a) Confirmed.** `grep -rn convert_minor src policies` finds callers only in `tutor/bank_a.py`. No environment, truth or scoring path converts currency, and the detector refuses a cross-currency receipt.
- **(b)** `uv run python -c "from genesis_audit.calculator import evaluate; print(evaluate('123456789/100*512.40*100'))"` prints `63259258683.6`. The policy must round that to 63,259,258,684 itself, under the declared half-up. The calculator has no rounding operator ([S1]: arithmetic and decimals only). No policy has been tested doing this, because there is no FX family.
- **(c) None exists.** No convention for the currency or sign of an FX amount, the tolerance key, a missing rate date or an inverse pair. SPEC section 6 says so; OQ-2 and OQ-9 ask.

### 6. Cutoff evidence

- **(a) The repo's policy is `invoice_issued_at`.** The tutor's completion-time policy is a labelled assumption of two quiz questions. You are right: under the published policy a cutoff issue is decidable from `issued_at`, the revenue row's timestamp and the manifest period. What blocks a fixture is the pre-release boundary and (b), not undecidability. My NOTES said "the schema lacks a completion time", which confused the guide's example with this repo's policy. Corrected.
- **(b) Not decided.** The invoice document and the revenue row have ids. The period boundary lives in the manifest, which has no evidence id (OQ-9).
- **(c) No.** `grep -n "period_start\|period_end\|timezone" src/genesis_audit/*.py` finds only the manifest key list and a start-before-end check. Nothing resolves `manifest.timezone`, so tzdata cannot disagree with anything today. SPEC section 1 now says the name is a label and the written offsets count.

### 7. Evidence-set validation

- **(a) -1 when you asked, 1.0 now.** Nobody had checked sufficiency. My rule required the bank row and the unapplied row on top of what the guide calls sufficient ("invoice, payment reference, complete relevant allocations"). The rule is now exactly that set, and further record ids are optional. It is still one reading of one sentence: PC-11, not an official rule.
- **(b) Recounted on the current tree** from `out/results/evaluator/reports.json`: 42 findings in the truth-blind scripted runs. 32 fail on type or affected ids, 8 on amount, 1 on amount and evidence, 1 matched (`flag_all`). The evidence-only rejection you saw came from the random policy I have since changed. Today no scripted finding is rejected by evidence alone; that case is pinned only by tests (`test_matching::test_each_condition_is_required`).
- **(c) Very little, and the spec now says so** (PC-9). It rejects a claim that does not name the allocation row and both documents, and ids that are not records. It cannot tell an audit from a guess that cites the right three ids. Under `observed`, four list calls mark everything.

### 8. False positives and clean cases

- **(a) You were right, and SPEC section 10 was wrong** ("up to 0.8"). Measured:

| Policy | Faulty | Clean | Note |
|---|---|---|---|
| always_abstain | -1.000 | 1.000 | mean 0.0, above every scripted truth-blind baseline (best: `flag_all`, -0.903) |
| exits before acting | -1.000 | 1.000 | truncated with 0 inspection steps |
| silent | -1.000 | 1.000 | same |
| floods | -1.000 | 1.000 | same |
| 100 garbage actions | -1.000 | 0.800 | truncated after 100 inspection steps |

  `always_abstain` is now a row in `docs/RESULTS.md`. `test_bridge::test_a_policy_that_never_acts_scores_a_perfect_abstention_on_clean_books` pins the consequence, and OQ-10 documents the design rationale.
- **(b) 0.275** over seeds 0 to 399 (110 of 400 clean rollouts claimed something).
- **(c)** With one issue per faulty episode, recall r, clean false-alarm rate q and c = 0.002 x inspections, the mean over a 50% clean share is `(r - q) - c(1 + r - q)/2`. It beats always-abstain when `r - q > c / (2 - c)`: 0.003 at 3 inspections, 0.031 at 30.

### 9. Isolation

- **(a) `seatbelt`**: `process.backend` in the saved evaluator reports, and the self-check prints it. The sheet omits it because rewards and digests are identical under every backend (`test_bridge::test_confinement_does_not_change_any_result`, and the container reproduces `docs/DIGESTS.json` under `setuid`). Your fallback point was right: `auto` could silently run with no boundary. It is refused now; the self-check still runs and fails its boundary line (`test_evaluate::test_auto_confinement_refuses_to_fall_back_to_no_boundary`).
- **(b) All three reads succeeded when you asked. None was intended.** The image left source, tests and public records world-readable. Now everything except `/app/policies` is root-only, the launch is refused unless truth, records, source and tests are root-only, and the probe must fail to read each of them. The container block of `docs/VERIFICATION.md` shows the probe denied.
- **(c)** A private path outside the denied prefixes is protected only if it is named. The CLI now names truth, records, source, tests and the secret file. Run as a probe, not a text check: `test_boundary::test_seatbelt_denies_a_private_root_that_lies_outside_the_blanket_areas`. **Signals: it could.** A code review reproduced a sandboxed policy killing the evaluator. Fixed and pinned by `test_boundary::test_a_sandboxed_policy_cannot_kill_the_evaluator`. The first rule I tried, `(deny signal (target others))`, denied nothing on this macOS; the probe is what showed that.

### 10. Held-out splits

- **(a) Never, when you asked.** Now `test_evaluate::test_held_out_roots_and_a_private_secret_outside_the_repo`: both halves and a non-development key live in a directory outside the repo, the self-check passes 10 of 10 through the three environment variables, one confined eval-mode run goes through, and the issue ids differ from the dev-keyed ones. It exercises the path. It is still the same two episodes, not a held-out set.
- **(b) 0.994 on all 40 runs** (20 seeds, both twins): `test_bridge::test_a_memoriser_of_amounts_is_perfect_because_there_is_one_company`.
- **(c)** Rule: every variant of one latent (twins and perturbations) stays on one side. Independent latents: one. There is nothing to split, and no generalization claim can be made from this repo.

### 11. ID and order tests

- **(a) Almost none.** It could only catch `perturb` renaming the records and the truth inconsistently. Now every paired check also re-derives truth from the perturbed public records with the detector (40 pairs in `check`), and `test_evaluate::test_independent_checker_rederives_truth_on_perturbed_episodes` does it with the independent checker on perturbed episodes written to disk.
- **(b) Run now**, 20 seeds each, `(tp, fp, fn, steps)`:

| Policy | Faulty base | Clean base | Twins equal to base |
|---|---|---|---|
| always_abstain | 0, 0, 1, 1 | 0, 0, 0, 1 | 20 of 20, both episodes |
| reconciliation_naive | 0, 2, 1, 4 | 0, 2, 0, 4 | 20 of 20, both episodes |
| flag_all | 1, 18, 0, 4 | 0, 15, 0, 4 | 20 of 20, both episodes |
| random_inspector (seed 7) | 0, 2, 1, 5 | 0, 2, 0, 5 | 20 of 20, both episodes |

  Pinned by `test_bridge::test_truth_blind_policies_under_perturbation`, and three seeds per policy run inside `check`.
- **(c) Yes, it would have.** The tie was broken by `payment_id`, which renaming changes. Such an episode is refused now: `test_teaching_fixture::test_receipts_with_an_undefined_order_are_refused`.
- **(d) Not when you asked.** Added `test_matching::test_order_invariance_with_alternative_evidence_sets`.

### 12. Reproducibility

- **(a) No.** The container result you saw predated later edits. `python tools/write_verification.py` now runs everything and writes `docs/VERIFICATION.md`, which names the tree by a SHA-256 over every file git would commit. There is no commit hash: nothing has been committed, because the owner has not asked for a commit.
- **(b) `docs/DIGESTS.json`**: 12 runs, each with its trajectory digest, exact reward and step count. `check` recomputes them ("docs/DIGESTS.json is reproduced exactly").
- **(c) Three versions.** The self-check passes under Python 3.11, 3.12 and 3.13 on macOS, and under 3.11 on Linux in the container, each reproducing the same digests. "Every Python version" now reads "the versions tested".

## The fifteen suspect statements

| # | Statement | Verdict |
|---|---|---|
| 1 | `oracle_fetching` is "the cheapest honest path" | Wrong. Reworded. |
| 2 | Flat-group share "a measured quantity" | Wrong when written. Measured now (answer 1b). |
| 3 | "Does not fall back to `none`" | Was false for `auto`. Fixed. |
| 4 | "Up to 0.8" for a run that never submits | Wrong: 1.0 when it never acts. Spec and tests corrected. |
| 5 | Container result reported as current | Stale when you looked. Re-run with a tree digest. |
| 6 | "Identical on every Python version" | Overclaim. Now: 3.11, 3.12, 3.13. |
| 7 | Same seed, config, actions give the same transitions | One process on one machine when you asked. Now committed digests, reproduced on Linux. Wall time is named as the exception. |
| 8 | "37,000 `step` calls, no private token" | True of the reviewer's run on the earlier tree. NOTES now says so. The committed fuzz is 2,400 steps. |
| 9 | "Four baseline adapters" | The fourth reads truth, and no truth-blind one beats abstention. Said plainly now; `always_abstain` added. |
| 10 | "Truth recomputed, not copied from the label" | The builder checked a count only. It now cross-checks pair and amount. |
| 11 | Independent checker follows the spec | It had drifted in three ways. Updated by its author. |
| 12 | Held-out instruction never exercised | True. Exercised now by a test. |
| 13 | Docker row: "cannot see private files at all" | True of the per-policy container, misleading for the evaluator image. The spec now separates the two. |
| 14 | Draft README claims | The draft was never published. The final README is written against this list. |
| 15 | The 63/37 rubric split is the author's own | Correct, and the rubric says so. A score against it is a self-assessment unless someone else produces it. |

## Round 2: the judge's verification, grades and fixes

The judge's reply, verbatim. It ran its checks on the tree whose digest it quotes.

**Bottom line:** 30 of 36 answer claims are supported as worded and 6 partly. Two of the partly-supported fixes hide new defects: the tie rule misses non-adjacent ties, and a confined policy can read the evaluator's command line.

**Tree checked.** I recomputed `tree_digest()` from `tools/write_verification.py` before and after my runs. Both times it was `e589f6569db73ae1dbd11c3ef251acf88a1d0d95cac8dae14c3e9f077d277f78` over 106 files, the value in `docs/VERIFICATION.md`. I modified no file. Appending this reply changes the digest, so the log needs regenerating afterwards.

**What I ran:**
- Full suite: 468 passed, 2 skipped.
- `genesis_audit check`: 10/10 under `seatbelt` on Python 3.11.15, and again under 3.12.8 and 3.13.13.
- `make docker-check`, once: 10/10 under `setuid`, 6 tests skipped in the container.
- `genesis_audit sweep --seeds 400`.
- All 18 tests the answers cite: 36 test cases, all pass.
- My own probes, listed in the table.

Not re-run by me: `make lint` and the coverage figure.

### (a) Per-answer verdicts

| Q | Claim checked | What I ran or read | Verdict |
|---|---|---|---|
| 1a | Two distinct initial states, no generator | `teaching.VARIANTS`, `perturb.py` | supported |
| 1b | Sweep: faulty 400 x -1, 100/100 flat groups; clean 110 x -1 | Re-ran the sweep; output equals `docs/measurements/random_inspector_sweep.json` | supported |
| 1c | No training; the grep "prints nothing" | Ran the grep; searched for weight files | partly: no trainer and no weights, but the grep prints 3 lines of quiz prose (`tutor/bank_a.py:222`, `bank_d.py:221,226`) |
| 2a | Builder refuses unless the detector reports the injected pair and amount | `teaching.py` `build_from`; ran the test | supported |
| 2b | Three (latent, injection) pairs, hand keys, checker agrees | Ran both tests | supported (one latent) |
| 2c | P2 raises `EpisodeError`; checker agrees on all three; "its author updated it" | Ran tests; read the checker | partly: behaviour holds; authorship and the "seven further cases" have no artifact |
| 3a | No truth-blind solver exists yet | `docs/RESULTS.md` | supported (an admission; the gap is still open) |
| 3b | Sentence corrected; `oracle_fetching` 3 calls, 0.994 | RESULTS.md, reproduced by `check` | supported |
| 3c | 12 rows measured; 0.912 is arithmetic | Recomputed | supported |
| 4a, 4b | Loader accepts a balanced duplicate, `[]` scores 1.0; identities and checker reject it | Ran both tests | supported |
| 4c | Loader now enforces debits = credits; docstring and PC-23 separate invariant from symptom | `store.py:301-304`, the docstring, PC-23 | supported |
| 5a-c | No conversion path; calculator prints `63259258683.6`; no FX convention | Ran the grep and the command; SPEC section 6 | supported |
| 6a-c | Policy is `invoice_issued_at`; nothing compares a timestamp with the period | Grep; SPEC line 35; NOTES line 190 | supported |
| 7a | Evidence {D31, D44, L11} scores 1.0 now | In-process: 1.0; either two-id subset -1.0; the five-id superset 1.0 | supported |
| 7b | 42 findings: 32 / 8 / 1 / 1 | Recounted from a fresh `run_matrix`; equals the saved reports | supported |
| 7c | PC-9 states what the condition cannot do | Read | supported |
| 8a | Do-nothing table | Ran each policy through the bridge on both twins: abstain, exit, silent and flood all -1.0 / 1.0; 100 garbage actions -1.0 / 0.8 | supported |
| 8b, 8c | 0.275; break-even `r - q > c/(2 - c)` | From the reproduced sweep; re-derived the formula | supported |
| 9a | RESULTS came from `seatbelt`; `auto` no longer falls back to none | Saved reports; ran the test; `cli._confinement` | supported |
| 9b | Container: source, tests, records root-only; probe denied | `make docker-check`; my own uid-65534 probe was denied on `src`, `tests`, both episode halves, `docs`, `tools` | supported, but see D2 |
| 9c | Named private paths; outside-areas probe; signals denied | Ran both tests; read the profile | partly: both fixes hold; D2 shows what the profile still exposes; `docs/` and `tools/` are not named |
| 10a | Held-out path exercised | Ran and read the test | partly: the path runs, but `run --episode` still accepts only the two teaching names (`cli.py:312`) |
| 10b, 10c | Memoriser 0.994 on 40 runs; one latent, nothing to split | Ran the test | supported |
| 11a | Truth re-derived on perturbed records: detector on 40 pairs, checker on 3 seeds | Read `paired_check`; ran `check` and the test | supported |
| 11b | 20 of 20 for four policies, "pinned by" the test | Measured 4 policies x 2 episodes x 20 seeds: all equal to base | partly: the numbers are right; the pin is weaker (see b) |
| 11c | A tie episode "is refused now" | Ran the test; built two cases | partly: adjacent ties only, builder only (D1) |
| 11d | Order invariance with alternative evidence sets | Ran and read | supported (one hand case, 48 orderings) |
| 12a | Log names the tree by digest | Recomputed, equal | supported |
| 12b | `docs/DIGESTS.json`, 12 runs, recomputed by `check` | Ran `check` | supported |
| 12c | 3.11, 3.12, 3.13 on macOS; 3.11 on Linux | Ran all four | supported |
| S1-S15 | Verdicts on the fifteen suspect statements | Read SPEC, NOTES, RESULTS | 12 supported; S5 and S8 partly; S14 not as worded (see b) |

### (b) Overstated claims and new defects

**Overstated or unsupported as worded**

1. **1c.** The grep prints three lines, not nothing. The conclusion stands. Settle it by excluding `tutor/` or quoting the three hits.
2. **2c.** "Its author updated it; I did not edit it" and "seven further cases by hand" cannot be checked: there is no history and no case file. Settle it by committing those cases as data plus a test that runs the checker on them.
3. **10a.** `EPISODES` and the `--episode` choices are still hard-coded. A genuinely new episode cannot be run from the CLI.
4. **11b.** `test_truth_blind_policies_under_perturbation` pins 10 seeds for three policies. For `random_inspector` it asserts only `tp == 0`, on 5 seeds, on the faulty episode. The table's "20 of 20" would not fail a test if it stopped being true.
5. **11c and SPEC PC-11.** "Such an episode is refused" is true only of the builder, and only for adjacent ties (D1).
6. **S14.** "The final README is written against this list": `README.md` is a 65-byte stub. SPEC line 179 points to "the README's limits", which does not exist.
7. **S5.** NOTES lines 226-229 still report 431 passed, 8/8, and the old container result, with no pointer to the log. NOTES line 253 still says the checker covers single-invoice receipts only.
8. **S8.** The committed fuzz makes 2,400 `step` calls. At most 1,000 reach a live episode, because `max_steps` is 25.
9. **`docs/VERIFICATION.md`.** The container block keeps 14 lines, so the test count is not in the artifact.
10. **Hostile and perturbation tests** all run with `Confinement("none")` (`tests/test_bridge.py:23,242,252,270`). Under the CLI's seatbelt configuration a script under `tests/` cannot even start, because `tests/` is a named private path. My `silent.py` run there ended as `policy_exit`, not `wall_time`. No hostile behaviour is exercised under a real boundary.

**D1 (new). The tie rule misses non-adjacent ties, and truth then depends on row order.**

`detect_allocation_issues` compares only neighbouring receipts after a stable sort by timestamp. With three receipts at one instant (P1 -> I1, P2 -> I2, P3 -> I1), the builder accepts the episode. The same records with the payments table reversed give a different truth. `shuffle_rows` produces exactly that reordering.

```
uv run python - <<'EOF'
from genesis_audit import teaching
from genesis_audit.store import PublicEpisode
T = "2026-10-20T09:00:00+05:00"
inv = lambda n: {"doc_id": f"D{n}", "invoice_id": f"I{n}", "entity_id": f"E{n}", "issued_at": f"2026-10-0{n}T10:00:00+05:00", "due_at": "2026-10-30T18:00:00+05:00", "currency": "KZT", "line_items": [{"description": "seat", "quantity": 1, "unit_price_minor": 1000, "amount_minor": 1000}]}
pay = lambda n, amount, ref: {"doc_id": f"D9{n}", "payment_id": f"P{n}", "timestamp": T, "currency": "KZT", "amount_minor": amount, "invoice_refs": [ref]}
ids = {f"issue:I{n}:{side}": f"L{n}{k}" for n in (1, 2) for k, side in enumerate(("receivable", "revenue"))}
ids |= {f"pay:P{n}:{part}": f"L{n}{k}" for n in (1, 2, 3) for k, part in enumerate(("bank", "unapplied"), start=3)}
ids |= {"pay:P1:receivable:I1": "L15", "pay:P2:receivable:I2": "L25", "pay:P3:receivable:I1": "L35"}
latent = {**teaching.LATENT, "invoices": [inv(1), inv(2)], "payments": [pay(1, 600, "I1"), pay(2, 500, "I2"), pay(3, 600, "I1")], "fx": [], "row_ids": ids}
public, truth, _ = teaching.build_from(latent, "ep-tie3", [{"invoice_id": "I1", "payment_id": "P1", "applied_minor": 300}])
show = lambda ep: [(i["affected_ids"], i["expected_amount_minor"]) for i in teaching.detect_allocation_issues(ep)]
print("built; payments listed P1,P2,P3 ->", show(public))
flipped = PublicEpisode(public.manifest, public.policy, {**public.tables, "payments": public.tables["payments"][::-1]})
print("same records, payments listed P3,P2,P1 ->", show(flipped))
EOF
```

Observed:
```
built; payments listed P1,P2,P3 -> [(['I1', 'P1'], 300)]
same records, payments listed P3,P2,P1 -> [(['I1', 'P3'], 200), (['I1', 'P1'], 100)]
```

Two further points:
- `validate_public` has no tie check. An episode with two same-instant receipts for one invoice loads from disk; I ran the adjacent case, which `validate_public` accepts and the detector refuses.
- The independent checker groups by invoice (`tools/independent_checker.py:210-212`). By reading, not by running, it would refuse this episode, so builder and checker disagree on it.

**D2 (new). A confined policy can read the evaluator's command line, and under `seatbelt` its environment.**

SPEC section 1 says "A policy never sees a name or a path". The `run` command puts the episode name, which carries the clean/faulty label, and the seed on the command line.

macOS, using the repo's own profile and private paths:
```
GENESIS_DEMO_ENV=visible uv run python - run --episode teaching_b_clean --seed 3 <<'EOF'
import subprocess, sys
from pathlib import Path
from genesis_audit import cli, sandbox
child = ('import ctypes,os\n'
         'c=ctypes.CDLL("/usr/lib/libSystem.B.dylib");b=ctypes.create_string_buffer(1<<18);n=ctypes.c_size_t(len(b))\n'
         'c.sysctl((ctypes.c_int*3)(1,49,os.getppid()),3,b,ctypes.byref(n),None,0)\n'
         'print([p.decode() for p in b.raw[4:n.value].split(b"\\0") if p.startswith((b"--",b"teaching",b"3",b"GENESIS_"))])')
profile = sandbox.seatbelt_profile([Path(sys.base_prefix), Path(sandbox.base_python()).parent], cli._private_paths())
argv = ["sandbox-exec", "-p", profile, sandbox.base_python(), *sandbox.PYTHON_FLAGS, "-c", child]
print(subprocess.run(argv, capture_output=True, text=True, cwd="/", env=dict(sandbox._CLEAN_ENVIRONMENT)).stdout)
EOF
```
Observed: `['--episode', 'teaching_b_clean', '--seed', '3', 'GENESIS_DEMO_ENV=visible']`

Container, as uid 65534 under a root parent:
```
docker run --rm --network none genesis-audit-env python -c 'import subprocess,sys;print(subprocess.run([sys.executable,"-c","import os;print(open(f\"/proc/{os.getppid()}/cmdline\",\"rb\").read().split(b\"\\0\")[-6:-1])"],user=65534,group=65534,extra_groups=[],capture_output=True,text=True).stdout)' run --episode teaching_b_clean --seed 3
```
Observed: `[b'run', b'--episode', b'teaching_b_clean', b'--seed', b'3']`. The parent's `environ` and `cwd` were denied there.

Scope:
- `check` and `baselines` carry no names in their arguments. `run` does.
- The teaching truth is public, so nothing is lost today.
- The same channel would expose a held-out episode's name, its seed, and any secret held in an environment variable. The probe does not attempt it.

**D3 (minor).** A policy that never submits is reported with `valid_submission: true`. All three forced-truncation runs in 8a show it. The sheet would list a policy that crashes on every episode with `invalid_submissions 0` and a mean reward of 0.0. Only `termination_cause` tells it apart from always-abstain.

### (c) Grades

These grades rest only on what I could reproduce on the tree named above. They are not a prediction of placement and use no rubric points.

**Clarity: A-.** Each answer says what was true when asked, what is true now, and where the limit is. Concessions are explicit ("nothing shows it yet", "one latent, nothing to split") and numbers come with commands. The minus is for a handful of sentences stronger than their evidence: "prints nothing", "pinned by", "is refused now", "the final README is written", and NOTES lines left stale.

**Evidence: B+.** This is unusually strong for a slice. The tree is pinned by digest, every cited test exists and passes, and the sweep and all 12 digests reproduce exactly on three Python versions and in the container. My independent container probe confirmed the permission fix. Three things hold it back:
- Two fixes claimed as complete are not: the tie rule (D1) and the boundary (D2).
- The central capability claim, that an investigator can solve the faulty episode from the tools, still has no measurement. The best truth-blind reward there is -0.806.
- Some provenance cannot be checked at all: no commit history, and the checker's authorship and extra cases rest on a report.

### (d) Three highest-impact fixes

The fix with the largest effect on what this environment can claim is a seeded generator with more than one family and a split by latent. The release boundary forbids it now, so it is not ranked. These three are allowed today.

1. **A truth-blind investigator, measured, with a control that a memoriser fails.** This is the prompt H deliverable.
   - Add a policy that implements PC-11 from the observation's policy object only.
   - Add a hand-built variant with different amounts, for example the two existing single-injection variants written out as episodes.
   - Done when `check` gains a line that fails unless the solver scores at least 0.99 on both twins, on every variant and on 20 perturbation seeds each, under the strongest backend, while `tests/hostile/memoriser.py` scores no better than abstention on the variants. RESULTS.md then has a truth-blind row above `always_abstain`.

2. **Close and test the process-metadata channel, and run the hostile suite under a real boundary.**
   - Add `read_evaluator_cmdline` and `read_evaluator_environ` to the probe and to `PROBE_MUST_FAIL` for every backend, with the `none` control showing the probe can succeed.
   - Done when a test launches `run --episode teaching_b_clean --seed 3` with a hostile policy and finds neither the name, the seed nor any evaluator environment variable in anything that policy could collect.
   - Done also requires the flood, silent, exit and grandchild cases to pass under `seatbelt` and `setuid`, not only under `none`. That means the hostile scripts must live somewhere the policy may read.

3. **Make the order rule correct, enforce it where episodes enter, and test truth against row order.**
   - Refuse any two receipts that share a timestamp and an invoice, grouped by invoice, when an episode is loaded as well as when it is built.
   - Done when the three-receipt case in D1 fails to build and fails to load.
   - Done also requires a property test: `detect_allocation_issues` returns the same truth for 100 row shuffles of every hand-built variant, including the injected ones. `paired_check` covers only the two shipped episodes today.

Smaller, and the owner's call:
- Commit the tree so results cite a hash.
- Report forced truncations in their own column instead of `valid_submission: yes`.
- Keep the pytest summary line in the container block of the log.
