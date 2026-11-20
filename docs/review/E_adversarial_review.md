# E. Adversarial review of the public spec and code

Reviewer role: internal adversarial verifier testing by Team Intuition (20 November 2026).

## 1. Summary

- 45 rows: 7 ACTUAL FAILURE, 12 SPEC GAP, 15 COVERED, 7 UNTESTED-PASS, 4 HYPOTHESIS.
- Most serious: PC-11's evidence convention collides with the 10-id evidence cap. A receipt carried by more than 8 ledger rows gives a required evidence set above 10 ids, the exactly-correct finding is then malformed (-1), and the loader accepts such truth (row 36). It is latent: neither shipped episode triggers it.
- No path was found by which truth, provenance, a private path or an issue id reaches an observation, `info` or a policy error message: 37,000 fuzzed `step` calls gave 0 exceptions and 0 hits. Nothing here is rated critical in the reviewed state.

### What was reviewed, and how

- State: `docs/SPEC.md` (md5 `91b47f90...`), `src/genesis_audit/` (`env.py` `3c275fa5...`, `schemas.py` `0c16c974...`, `matching.py` `8c2929fa...`, `store.py` `cc6c779b...`, `truth.py` `1cc76283...`), the two teaching episodes, `tests/`. File times show no change to `src/genesis_audit/` after 00:30:48, which is before the first run; the md5 values were checked twice during the runs and matched.
- The existing suite was run before and after: 261 tests, all pass.
- Every "Observed" cell below was produced by code run in this session against that state. Runs used `uv run --no-sync python` with `PYTHONDONTWRITEBYTECODE=1`. Cases that need a modified episode used a copy in a temporary directory outside the repo, deleted afterwards.
- Not reviewed and not run: `tools/`, `policies/`, `out/staging/` (calculator, bridge, sandbox, perturbation files appeared there during the review), `Dockerfile`, `.dockerignore`, `docs/GRADING_CRITERIA.*`. Section 5 is about those areas and contains no observed results.
- Shorthand in the table: `F()` is `finding()` from `tests/helpers.py` (the one correct finding for `teaching_b`); `E` is its evidence list `["D31","D44","L11","L19","L26"]`. Unless stated, the input is the first and only action: `env.step(submit_action([...]))` on `teaching_b` with zero inspections. Counts are written (TP, FP, FN).

## 2. Attack table

| # | Attack | Minimal reproducible input | Expected reward / transition (per spec) | Observed | Class | Test location (existing or proposed) | Severity |
|---|---|---|---|---|---|---|---|
| 1 | Exact duplicate claim | `[F(), F()]`; `[F()]*30` | (1,1,0), reward 1/3; (1,29,0), 4/31 - 1. Terminated. PC-10 | `0.3333333333333333`, (1,1,0), reasons `matched` / `repeat_of_matched_issue`; `-0.8709677419354839`, (1,29,0) | COVERED | `tests/test_reward_integrity.py::test_duplicates_add_no_credit`; `tests/test_matching.py::test_repeats_earn_nothing_and_cost_precision` | low |
| 2 | Near-duplicate claims | `[F(), F(explanation="other")]`; `[F(), F(affected_ids=["P9","I7"], evidence_ids=E[::-1])]`; `[F(), F(evidence_ids=E+["L05"])]`; on a tolerance-5 copy: `[F(), F(claimed_amount_minor=100003)]` | (1,1,0), 1/3 in each case. PC-7, PC-10 | `0.3333333333333333`, (1,1,0) in all four | UNTESTED-PASS | Unit level pins the explanation and in-tolerance variants (`test_repeats_earn_nothing_and_cost_precision`). Reordered ids and extra-evidence repeats are pinned nowhere. Proposed: `tests/test_reward_integrity.py::test_near_duplicates_add_no_credit` | low |
| 3 | Repeats inside one id list, against the caps | `F(evidence_ids=E+E)` (10 entries, 5 unique); `F(evidence_ids=E+E+["D31"])` (11 entries, 5 unique); `F(affected_ids=["I7","P9"]*10+["I7"])` (21 entries, 2 unique) | PC-7: repeats do not matter, so a true positive. PC-6: at most 10 (20), so malformed. The spec does not say which applies first | 10 entries: `1.0`. 11 entries: `-1.0`, `malformed_submission`. 21 entries: `-1.0`, `malformed_submission` | SPEC GAP | Proposed: `tests/test_schemas.py::test_caps_apply_to_the_list_as_sent` | low |
| 4 | Amount hedging and shotgun claims | `[F(), F(claimed_amount_minor=250000)]`; the same plus `F(claimed_amount_minor=1000)`; `[F(claimed_amount_minor=i) for i in range(1,31)]`; `[F(claimed_amount_minor=1)]`; `[]` | By the formula: 1/3; 0; -1; -1; -1 | `0.3333333333333333` (1,1,0); `0.0` (1,2,0); `-1.0` (0,30,1); `-1.0` (0,1,1); `-1.0` (0,0,1) | UNTESTED-PASS | Proposed: `tests/test_reward_integrity.py::test_hedged_amounts_have_the_calculated_values`. See note N1 | medium |
| 5 | Wrong currency | `F(currency="USD")`; `F(currency="ZZZ")`; on a tolerance-5 copy: `F(currency="USD", claimed_amount_minor=19516)` (converted at 512.40) and `F(currency="USD", claimed_amount_minor=100002)` | (0,1,1), -1. Currency is compared before the amount | `-1.0`, (0,1,1), reason `currency_mismatch` in all four | COVERED | `tests/test_reward_integrity.py::test_wrong_or_unsupported_claims_score_like_a_miss_plus_a_false_alarm`; `tests/test_matching.py::test_each_condition_is_required` | low |
| 6 | Amount: tolerance boundary, sign, size, type | Tolerance 0 (shipped): 99999, 100000, 100001, -100000, 0, `2**53-1`. Tolerance 5 (temp copy of `teaching_b`, manifest `KZT: 5`): 99994, 99995, 100005, 100006. Types: `2**53`, `-(2**53)`, `10**30`, `True`, `False`, `100000.0`, `"100000"`, `None`, `[100000]`, `nan`, `inf` | Inclusive absolute bound (PC-8): inside is a match, outside is (0,1,1). Not a JSON integer or above 2^53 - 1: malformed, -1 | 100000: `1.0`. 99999, 100001, -100000, 0, `2**53-1`: `-1.0` (0,1,1). Tolerance 5: 99995 and 100005 `1.0`; 99994 and 100006 `-1.0` (0,1,1). Every listed type: `-1.0`, `malformed_submission` | COVERED | `tests/test_matching.py::test_tolerance_boundary_is_inclusive_and_binary`; `tests/test_schemas.py::test_malformed_submissions`. No shipped episode has a non-zero tolerance, so the boundary is unpinned at environment level | low |
| 7 | Guessed and wrong-kind affected ids | `F(affected_ids=["I1","P1"])`; `["D31","D44"]`; `["I7","P9","L11"]`; `["i7","P9"]`; `["I7"]` | (0,1,1), -1 | `-1.0`, (0,1,1), reason `no_issue_with_this_type_and_affected_ids` for all five | COVERED | `tests/test_matching.py::test_each_condition_is_required`; `tests/test_reward_integrity.py::test_wrong_or_unsupported_claims_score_like_a_miss_plus_a_false_alarm` | low |
| 8 | Evidence that was never fetched; a policy that never inspects | First action `submit [F()]` on `teaching_b`; first action `submit []` on `teaching_b_clean`; one policy that branches on `obs["manifest"]["counts"]["ledger_rows"] == 12` | PC-9 only asks that cited ids exist, so 1.0 with no inspection. OQ-1 leaves "must it be retrieved" open | `1.0` with `inspection_steps` 0 on both episodes. `_EpisodeState.observed` is filled by every tool call and read by nothing; `match(observed=...)` exists and the environment never passes it | SPEC GAP | Proposed: `tests/test_env_lifecycle.py::test_the_declared_evidence_rule_is_the_one_enforced` | high |
| 9 | Incomplete, empty and invented evidence | `F(evidence_ids=["D31","D44","L11","L19"])`; `F(evidence_ids=[])`; `F(evidence_ids=E+["L77"])`; `F(evidence_ids=E+["truth-29d7352524bd"])`; `F(evidence_ids=E+["ep-4c1f09"])` | (0,1,1), -1. One invented id voids the finding | `-1.0`, (0,1,1); reasons `evidence_set_incomplete` (first two) and `evidence_id_not_in_public_records` | COVERED | `tests/test_env_lifecycle.py::test_strict_scoring_on_the_faulty_episode`; `tests/test_matching.py::test_each_condition_is_required` | low |
| 10 | Padded evidence | `F(evidence_ids=E+["L03","L05","L08","L09","L14"])` (10 ids, 5 unrelated) | True positive: extra real ids are allowed up to the cap (PC-9) | `1.0`, (1,0,0) | COVERED | `tests/test_matching.py::test_extra_real_evidence_is_allowed_and_alternatives_work` (one extra id, unit level). See note N2 | medium |
| 11 | A real public id of another kind cited as extra evidence | `F(evidence_ids=E+["I7"])`; `E+["P9"]`; `E+["E4"]`; compare `E+["2026-10-14\|USD\|KZT"]` | PC-9: "valid when every cited id exists in the public records ... Extra real ids are allowed". I7, P9 and E4 are in the public records, so 1.0 | `-1.0`, (0,1,1), reason `evidence_id_not_in_public_records` for I7, P9 and E4. The FX key gives `1.0` | ACTUAL FAILURE | Proposed: `tests/test_reward_integrity.py::test_extra_public_id_of_another_kind_follows_the_published_rule` | high |
| 12 | Unicode, whitespace and case variants of ids, types, currencies, tables, actions | Evidence `"l26"`, `"L26 "`, fullwidth `"Ｌ26"`, `"L26\u200b"`. Currency `"kzt"`, `"KZT "`, `"KZТ"` (Cyrillic Т), `"KZT\n"`. Type `"Payment_Allocation"`, `"payment_allocation "`, `"payment-allocation"`, `"payment_allocation\n"`. `episode_id` `"ep-4c1f09 "`, `"EP-4C1F09"`. Table `"Ledger"`, `"ledger "`. Record id `" L11"`, `"l11"`, `"Ｌ11"`. Action `"Submit"`, `"submit "` | Exact string comparison, nothing normalised (PC-7). Token rules decide malformed (PC-6). Tool errors are bounded | `"l26"`: `-1.0` (0,1,1). The other evidence, currency, type and `episode_id` variants: `-1.0`, `malformed_submission`. Tables: `unknown_table`. Record ids: `unknown_id`. Actions: `unknown_action`, the episode continues. None matched | UNTESTED-PASS | Tests pin `"kzt"`, `"has space"`, `"L11 "`. Homoglyph, zero-width and trailing-newline cases are unpinned. Proposed: `tests/test_schemas.py::test_lookalike_tokens_are_not_normalised` | low |
| 13 | Malformed final JSON of every shape | `args` = `None`, `"{"`, `[]`, `{}`, `{"findings": []}`, `{"findings": {...}, "note": 1}`, a JSON string holding the whole document, a wrong `episode_id`; each finding field replaced by junk (6,000 fuzz cases); junk inside the id lists (3,000 cases) | -1, `terminated=true`, observation `{"status": "episode_over", "steps_remaining": n}`, detail only in the evaluator report | As expected in every case, no exception. `validation_error` holds a field path and the limits, never the input | COVERED | `tests/test_schemas.py::test_malformed_submissions`, `::test_malformed_submit_envelopes`, `::test_wrong_episode_id_is_malformed`; `tests/test_env_lifecycle.py::test_malformed_submission_ends_the_episode_and_logs_privately`; `tests/test_reward_integrity.py::test_malformed_final_submission_is_minus_one_on_any_books` | low |
| 14 | One malformed finding voids a correct submission | `[{**F(), "confidence": 0.9}]`; `F()` without `explanation`; `[F(), F(affected_ids=["I3","P5"], currency="kzt")]`; compare `currency="ZZZ"` in the same place | PC-6: -1 for the first three; (1,1,0) for `"ZZZ"`. What [S1] wants is open (OQ-4, OQ-11) | `-1.0`, `-1.0`, `-1.0`; `"ZZZ"`: `0.3333333333333333` (1,1,0) | SPEC GAP | Parse level is pinned in `test_malformed_submissions`. Proposed: `tests/test_reward_integrity.py::test_one_malformed_finding_voids_the_submission` | medium |
| 15 | A submit attempt with a broken envelope, also on the last step | `{"action": "submit"}`; `{"action": "submit", "args": {...}, "extra": 1}`; `{"action": "Submit", ...}`. Then on `teaching_b_clean` with `max_steps=1`: `{"action": "submit"}` against `{"action": "submit", "args": None}` | PC-1: invalid action, costs a step, episode continues. [S1]: "a malformed final submission is -1". The spec does not say which rule owns a submit attempt whose envelope is wrong | `invalid_action` / `unknown_action`, the episode continues. `max_steps=1`, clean books: `{"action": "submit"}` gives `0.998`, truncated, `step_limit`; `{"action": "submit", "args": None}` gives `-1.0`, terminated. Default budget after 99 garbage steps: `0.8` against `-1.0` | SPEC GAP | Proposed: `tests/test_reward_integrity.py::test_broken_submit_on_the_last_step_is_not_scored_above_a_malformed_one` | medium |
| 16 | A policy that only emits garbage | `env.step(None)` 100 times, on each episode; compare a malformed submit at step 1 on clean books | Truncated, scored as an empty submission (PC-14): clean 1 - 0.2 = 0.8, faulty -1 (OQ-10) | Clean: `0.8`, `truncated=True`, (0,0,0), before clip 0.8. Faulty: `-1.0`, before clip -1.2. Malformed submit at step 1 on clean books: `-1.0` | COVERED | `tests/test_reward_integrity.py::test_truncation_scores_an_empty_submission`; `tests/test_env_lifecycle.py::test_truncation_also_applies_to_an_invalid_last_action`. Consequence: a policy that cannot produce valid JSON scores 0.8 on every clean episode and beats one that submits malformed JSON | medium |
| 17 | Duplicate keys and NaN where JSON text enters (the `play` CLI) | `submit dup.json`, where the file has two `episode_id` keys (wrong first, right second) and two `claimed_amount_minor` keys (1 first, 100000 second); `raw {"action":"submit","action":"list_records","args":{"table":"fx"}}`; `raw {"action":"list_records","args":{"table":"ledger","limit":NaN}}` | Not stated. `canon.loads_strict` refuses duplicate keys, NaN and deep nesting, and is applied to episode files only | The file is scored: reward `1.0`, `tp` 1, `valid_submission` true (last key wins). The second `action` key wins and lists `fx`. `NaN` parses, then `bad_limit` | SPEC GAP | Proposed: `tests/test_teaching_fixture.py::test_play_reads_policy_json_strictly` | medium |
| 18 | Deep nesting through the `play` CLI | `raw ` followed by 200,000 `[` | The CLI prints `Could not read that: ...` and keeps going, as it does for other bad input | Uncaught `RecursionError: maximum recursion depth exceeded while decoding a JSON array from a unicode string`; traceback; exit status 1 | ACTUAL FAILURE | Proposed: `tests/test_teaching_fixture.py::test_play_reads_policy_json_strictly` | low |
| 19 | Hostile in-process objects: anything that makes `step` raise | 37,000 `env.step` calls: the whole action as junk (None, bools, `2**70`, nan, bytes, sets, objects, lambdas, dicts with int, None and tuple keys, nesting to depth 4, 10,000-char strings, a lone surrogate); junk as `args` of `list_records`, `get_record`, `get_document`, `submit`, `calc`, `calculator`, `reset`, `evaluator_report` | `step` always returns the 5-tuple. Errors are a code plus its fixed message. Nothing is echoed | 0 exceptions. 0 observations that fail `json.dumps(allow_nan=False)`. Every message equals its table entry. Reward always a float in [-1, 1]. `info` always `{}`. Codes reached: `bad_arguments`, `invalid_action`, `unknown_action`, `unknown_id`, `unknown_table` | UNTESTED-PASS | Proposed: `tests/test_env_fuzz.py::test_step_never_raises_and_errors_come_from_the_closed_list` | low |
| 20 | Oversized lists and strings at the caps | 31 findings; 11 evidence ids; 21 affected ids; 1,001-character explanation; 65-character id; the largest legal submission (30 findings, each 20 affected ids, 10 evidence ids, 1,000 characters: 41,695 bytes encoded) | Over a cap: malformed, -1. At the cap: scored | Over each cap: `-1.0`, `malformed_submission`. Largest legal submission: scored, (0,30,1), `-1.0` | COVERED | `tests/test_schemas.py::test_malformed_submissions`, `::test_valid_submission_is_canonicalized`; `tests/test_env_lifecycle.py::test_malformed_submission_ends_the_episode_and_logs_privately` | low |
| 21 | No total size limit; "characters" undefined; error codes outside the spec | `get_record` with a 50,000,000-character id; explanation of 1,000 times U+1F600; explanation `"\ud800"`; explanation `"\x00\x1b[2J"` | The spec has no size limit for an action and does not say how characters are counted. Its closed list has 9 codes | The 50 MB id is accepted and answered `unknown_id`. 1,000 astral characters are accepted (4,000 UTF-8 bytes, 2,000 UTF-16 units). The lone surrogate is accepted and cannot be encoded as UTF-8. Control characters are accepted. `errors.py` registers 15 codes; `action_too_large` and five `calc_*` codes are in no spec list and nothing raises them | SPEC GAP | Proposed: `tests/test_schemas.py::test_explanation_is_utf8_encodable`; `tests/test_env_lifecycle.py::test_registered_error_codes_equal_the_spec_list` | low |
| 22 | Actions after submit; last-step precedence | `submit []`, then `submit [F()]`, `list_records`, `get_document`, `None`, a malformed submit. Separately: 99 garbage steps, then a valid submit, and then a malformed submit, on step 100 | PC-13: `episode_over`, reward 0, nothing changes. PC-3: a submit on the last step is accepted | Five times `episode_over`, `0.0`, `terminated=True`; score and counts unchanged; `actions_after_end` 5. Valid submit on step 100: `0.802`, terminated, `submitted`. Malformed on step 100: `-1.0` | COVERED | `tests/test_env_lifecycle.py::test_no_action_is_accepted_after_the_end`, `::test_submit_on_the_last_allowed_step_is_accepted`; `tests/test_reward_integrity.py::test_reward_after_the_end_is_zero_and_changes_nothing` | low |
| 23 | Actions after truncation | `max_steps=2`; two `list_records`; then `submit [F()]`, `list_records`, a malformed submit | PC-13: `episode_over`, reward 0, `terminated=False`, `truncated=True`, nothing changes | As expected. The truncating step returned 12 records with `status: episode_over` and `-1.0`. The report is identical before and after apart from `actions_after_end` 3 | UNTESTED-PASS | Existing tests cover the after-submit case only. Proposed: `tests/test_env_lifecycle.py::test_no_action_is_accepted_after_truncation` | low |
| 24 | Repeated reset, seed, step budget override | `reset(seed=1, ...)`, `seed=2`, `seed=None`, `seed=-1`, `seed=2**64`; `reset(config={"episode": "teaching_b", "max_steps": 10**6})` | The spec gives `reset(seed, config)` and "at most 100 steps [S1]". It says nothing about what the seed does or which config keys exist | Observation and first ledger page are identical for every seed; any integer is accepted. `max_steps=10**6` is accepted: `steps_remaining` 1000000 while `manifest.limits.max_steps` reads 100. Isolation between resets holds | SPEC GAP | Isolation: `tests/test_env_lifecycle.py::test_reset_gives_isolated_state`. Proposed: `::test_config_cannot_raise_the_budget_above_the_manifest_limit` | low |
| 25 | Wrong exception type on evaluator-side misuse | `reset(config={"episode": "teaching_b", 1: 2})`; a `truth.json` whose issue has `"currency": ["KZT"]` | `LifecycleError`; `EpisodeError`. These are the two harness-facing types the tests rely on | `TypeError: '<' not supported between instances of 'int' and 'str'` (from `sorted(config)` while building the error text); `TypeError: unhashable type: 'list'` | ACTUAL FAILURE | Add both cases to `tests/test_env_lifecycle.py::test_lifecycle_misuse_is_a_harness_error` and `tests/test_teaching_fixture.py::test_malformed_truth_is_refused` | low |
| 26 | Reset failure: what stays live, what the text carries | One step on a live episode, then `reset(config={"episode": "missing"})`, then `step(list_records)`. Separately, a source whose public half exists and private half does not (temp directories) | Not stated | `EpisodeError: cannot read public episode files: [Errno 2] No such file or directory: '/Users/.../episodes/public/missing/manifest.json'`. With the private half missing: `cannot load truth: [Errno 2] No such file or directory: '<private root>/x1/truth.json'`. After the failed reset the old episode is still live: the next step returns `steps_remaining` 98 | SPEC GAP | Proposed: `tests/test_env_lifecycle.py::test_failed_reset_leaves_no_live_episode` | medium |
| 27 | Tools: id-type confusion, cursors, limits | `get_document` with `"I7"`, `"L11"`, the FX key; `get_record` invoices `"D31"`, payments `"I7"`, ledger `"P9"`, fx `"2026-10-14\|KZT\|USD"` and `"2026-10-14"`; tables `truth`, `policy`, `manifest`, `entities`; cursors `"ledger:0"`, `"ledger:12"`, `"ledger:1"` on invoices, `"ledger:+5"`, `"ledger:5\n"`, `"ledger: 5"`, `"ledger:005"`; limits 51, `1.0`, `True`, `10**30` | `unknown_id`, `unknown_table`, `bad_cursor`, `bad_limit`; one step each; reward 0 | As expected. One unpinned detail: `"ledger:005"` is accepted and returns the same page as `"ledger:5"` | COVERED | `tests/test_store.py::test_lookups`, `::test_bad_cursors`, `::test_bad_limits_are_errors_not_clamps`; `tests/test_env_lifecycle.py::test_invalid_inspection_costs_a_step_and_does_not_end_the_episode` | low |
| 28 | Truth, provenance, private path or issue id in a policy-visible value | Substring scan for `truth-`, `29d7352524bd`, `canary`, `inj-`, the private root path, `private`, `provenance`, `matched`, `teaching_b`, `/Users/`, `Traceback` over every observation of the 37,000-step fuzz (observations that hold records were excluded), and a read of the reset observation and `info` | None present (section 2 of the spec) | 0 hits. `info` is `{"env_version": "genesis-audit-env/0.1.0"}` at reset and `{}` on every step | UNTESTED-PASS | Only the `internal_error` path is pinned (`tests/test_env_lifecycle.py::test_internal_errors_are_bounded_for_the_policy_and_kept_for_the_evaluator`). Proposed: `tests/test_env_fuzz.py::test_canary_scan_of_everything_a_policy_receives` | low |
| 29 | The `play` CLI before submit | `list`, `get`, `doc` commands, `get truth x`, `raw null`, `raw 5`, `bogus`, `list ledger ²`; `submit episodes/private/teaching_b/truth.json`; `submit episodes/private/teaching_b/ANSWER_KEY.md`; `submit /bin/ls` | No evaluator detail before `Episode over.`; file errors do not echo file content | None of the scanned strings appears before `Episode over.`. `truth.json` is valid JSON, so it is sent as findings: malformed, the episode ends, no content echoed. `ANSWER_KEY.md`: `Could not read that: Expecting value: line 1 column 1 (char 0)`. The binary: a decode error naming one byte | COVERED | `tests/test_teaching_fixture.py::test_play_checks_only_on_submit`, `::test_play_can_be_left_without_scoring` | low |
| 30 | Issue ids are an unkeyed hash of the answer | Enumerate `"truth-" + sha256(canonical{type, affected_ids, expected_amount_minor, currency})[:12]` over public invoice and payment ids, declared currencies and amounts from 1 up | `teaching.py`: "A private, non-guessable-looking token; it must never reach a policy". The evaluator report and `play` print issue ids once the episode is over | The answer (I7, P9, 100000, KZT) is recovered from `truth-29d7352524bd` after 100,000 hashes in 0.2 s. End to end: `submit []` (`-1.0`), read `unmatched_issue_ids` from the report, brute-force with ids fetched through the tools, second attempt `0.994` (1,0,0) | ACTUAL FAILURE | Proposed: `tests/test_teaching_fixture.py::test_issue_ids_are_not_a_function_of_the_scored_fields` | medium |
| 31 | Predictable canary, labelled names, reused ids | `"canary-" + sha256("provenance:teaching_b")[:16]`; the public directory names; the ids on `docs/tutoring/A_socratic_tutor.md` | Not stated. `test_error_is_not_given_away_by_position_ids_or_names` states the intent | The formula equals the committed canary, so the canary can be computed from the episode name without the file. The public directory is called `teaching_b_clean`. Tutoring page A uses I7 and P9 for a partial allocation (Q5) and I3 for a valid split (Q6): the same ids in the same roles as `teaching_b`. `episode_id`: no match among 17 candidate strings under 4 hash functions, which proves nothing beyond those candidates | SPEC GAP | Proposed: extend `tests/test_teaching_fixture.py::test_error_is_not_given_away_by_position_ids_or_names` | low |
| 32 | The clean twin can be told from the faulty one at reset | Diff of the two reset observations | Not stated. The same test states the intent that the error is not given away | Exactly two fields differ: `manifest.episode_id` and `manifest.counts.ledger_rows` (12 against 11) | SPEC GAP | Proposed: `tests/test_teaching_fixture.py::test_twins_differ_at_reset_only_in_episode_id` | medium |
| 33 | The private half ships with the public tree | `git check-ignore -v episodes/private/teaching_b/truth.json episodes/private/teaching_b/ANSWER_KEY.md tests/helpers.py` | Section 1: "The two halves live under different roots" | Exit status 1: none is ignored. All of it is untracked, so `git add -A` commits `truth.json`, `provenance.json` and `ANSWER_KEY.md`. `tests/helpers.py` hard-codes the answer. `paths.PRIVATE_ROOT` defaults to a directory inside the repo | SPEC GAP | Proposed: `tests/test_repo_hygiene.py::test_private_root_is_ignored_or_declared_public` | medium |
| 34 | Truth that cites evidence no tool returns | Temp copy with `acceptable_evidence_sets = [["D31","D44","L11","bank-stmt-9"]]`, then `reset` | Rejected at load (section 1) | `EpisodeError: truth issue truth-29d7352524bd: evidence not in public records: ['bank-stmt-9']` | COVERED | `tests/test_teaching_fixture.py::test_truth_that_needs_an_inaccessible_fact_is_refused` | low |
| 35 | Truth that cites an affected id no tool returns; two indistinguishable issues | Temp copies: `affected_ids = ["I7","P404"]`; the one issue copied under a second `issue_id` | An issue that depends on an inaccessible fact is a broken episode (`truth.py`). "Repeated findings are false positives" (section 5) | Both load. P404 episode: the audit-correct `F()` scores `-1.0` (0,1,1); `F(affected_ids=["I7","P404"])` scores `1.0`. Twin issues: `[F()]` gives `0.3333333333333333` (1,0,1); `[F(), F()]` gives `1.0` (2,0,0) | ACTUAL FAILURE | Proposed: new cases in `tests/test_teaching_fixture.py::test_malformed_truth_is_refused` | medium |
| 36 | Truth that no well-formed finding can match | (a) evidence set of 11 real ids. (b) 21 affected ids. (c) expected amount `2**53`. (d) manifest issue type `"Payment-Allocation"`. (e) manifest currency code `"USDT"`. (f) the repo's own convention: one receipt allocated to 9 invoices with one partial allocation, truth derived by `teaching.detect_allocation_issues` | Every labelled issue can be expressed by a valid submission. Evidence cap 10 [S1] | All six load. (a): citing all 11 is `-1.0` malformed; citing 10 of them is `-1.0` (0,1,1); abstaining is `-1.0`. No 10-id list can contain an 11-id set, so the best reachable reward is -1. (b) to (e): the mirror finding is malformed. (f): the derived evidence set has 13 ids; `validate_truth` accepts it; the exactly-correct finding fails with `evidence_ids: must be a list of 0..10 ids` | ACTUAL FAILURE | Proposed: `tests/test_teaching_fixture.py::test_every_truth_issue_is_matchable_by_a_well_formed_finding` | high |
| 37 | PC-11 "open balance when the receipt arrives": recorded or ideal | `teaching_b` plus a later receipt P7 of 100,000 for I7, allocated in full (it settles what the books show open after the under-allocation) | Not stated. Either reading fits the text | `detect_allocation_issues` raises `EpisodeError: over-allocation is outside the teaching slice`. The code uses the policy-ideal running balance and refuses the episode | SPEC GAP | Proposed: `tests/test_teaching_fixture.py::test_chained_receipts_follow_the_declared_balance_rule` | medium |
| 38 | Maximum matching against greedy; order invariance | (a) 12 issues with amounts 1000+10i, tolerance 5; 12 findings 1005+10i (i < 11) plus 995; natural order, reversed, 500 shuffles of findings and truth. (b) 3,000 random cases (0 to 5 issues, 0 to 7 findings; amounts, two affected sets, two currencies, one or two alternative evidence sets) against an independent exhaustive search, each with 6 shuffles. (c) 30 by 30 dense. (d) through `env.step`: all 24 orders of [correct, near-duplicate, wrong amount, decoy] | PC-10: the count is the maximum and does not depend on order | (a) 12/0/0 in every order. (b) 0 size mismatches; 0 differences in counts, unmatched issue ids or key-to-issue assignment. (c) 30/0/0 in 0.4 ms. (d) one result: `-0.2`, (1,3,0) | COVERED | `tests/test_matching.py::test_maximum_matching_beats_greedy_and_ignores_order`, `::test_counts_and_assignment_are_invariant_under_every_permutation`, `::test_matching_size_equals_brute_force_on_random_cases`. The existing brute-force test varies amounts only; alternative evidence sets are not in it | low |
| 39 | Equal findings with different explanations | `[a, b]` and `[b, a]`: same scored fields, explanations `"first"` and `"second"`, one issue | (1,1,0) both ways. PC-10 orders findings by scored fields and is silent when those are equal | (1,1,0) both ways. The `matched` verdict goes to submission index 0 in both orders: the tie is broken by position | UNTESTED-PASS | Proposed: one assertion in `tests/test_matching.py::test_repeats_earn_nothing_and_cost_precision` | low |
| 40 | Integer and float edges in the reward | Perfect answer after 99 inspections; TP 1, FP 2 at 0 steps; `common_reward(1,0,0,10**6)`; reward type on an inspection, an error, the terminal step and a step after the end | 401/500 = 0.802; exactly 0; clipped to -1; a float each time | `0.802`; `0.0`; `-1`; `float` on all four. Exact values `401/500`, `1/3`, `-27/31`, `4/5`. No NaN and nothing outside [-1, 1] in 37,000 fuzz steps | COVERED | `tests/test_scoring.py::test_exact_values`, `::test_reward_is_clipped_to_the_unit_interval`, `::test_counts_must_be_non_negative_integers` | low |
| 41 | `money.convert_minor` is not exact past 28 digits | `convert_minor(3, 0, "0.166666666666666666666666666666", 0, "half_up")`; `convert_minor(1, 0, "0.499999999999999999999999999999", 0, "half_up")`; `convert_minor(10**28, 2, "500", 2, "half_up")` | Module text: "the conversion is exact up to the single declared rounding step": 0, 0 and 5 * 10^30. Bad input raises `ValueError` | `1`, `1` (the default decimal context rounds the product to 28 digits, then `quantize` rounds again); `decimal.InvalidOperation`. No policy can reach this today; the tutor bank uses it | ACTUAL FAILURE | Proposed: `tests/test_money.py::test_conversion_is_exact_beyond_28_significant_digits` | low |
| 42 | Calculator: execution and resource attacks | Today: `{"action": "calc", "args": {"expression": "1+1"}}` and `{"action": "calculator", "args": {"expr": "__import__('os').system('id')"}}` | No calculator action exists in the reviewed state | Both return `unknown_action` and cost a step. Nothing else could be run. See 5.1 | HYPOTHESIS | Proposed: `tests/test_calculator.py` | critical if violated |
| 43 | Bridge and sandbox: the truth boundary | Not runnable | `env.py`: sharing a process gives no confidentiality; the boundary is the bridge | Not run. See 5.2 | HYPOTHESIS | Proposed: `tests/test_bridge.py`, `tests/test_sandbox.py` | critical if violated |
| 44 | Trajectory logging | Not runnable | No logging in the reviewed state | Not run. See 5.3 | HYPOTHESIS | Proposed: `tests/test_logging.py` | high if violated |
| 45 | Seeds, id and order perturbation, seed leakage | Today: `reset(seed=1)` against `reset(seed=2)` | No seeded behaviour in the reviewed state | The seed is accepted and ignored (row 24). Nothing else could be run. See 5.4 | HYPOTHESIS | Proposed: `tests/test_perturbation.py` | high if violated |

Notes to the table.

- **N1 (row 4).** With one true issue, a submission of k claims that contains the answer scores 4/(k+1) - 1, and one claim drawn uniformly from the same k candidates averages 2/k - 1. The hedge is ahead for every k > 1 (k = 2: 0.333 against 0; k = 3: 0 against -0.333). When no claim is right the reward is -1 whether 1 or 30 claims were made, the same as abstaining on faulty books. This is the [S1] formula applied as written; the values above are the run results, the general statement is arithmetic.
- **N2 (row 10).** Padding to the cap costs nothing, so a policy that is unsure which rows are required cites everything near the payment. An episode with 10 or fewer evidence ids in total would make the evidence condition empty. `teaching_b` has 19.

## 3. Actual failures

Each block is paste-ready from the repo root. The output under it is copied from this session's run.

### AF-1 (row 36, high). Truth that no valid finding can match is accepted; PC-11 produces such truth

```bash
uv run python - <<'EOF'
import json
from genesis_audit import paths
from genesis_audit.store import load_public
from genesis_audit.truth import parse_truth, validate_truth
from genesis_audit.schemas import parse_submission
pub = load_public(paths.PUBLIC_ROOT / "teaching_b")
doc = json.loads((paths.PRIVATE_ROOT / "teaching_b" / "truth.json").read_text())
ev = sorted(pub.evidence_universe())[:11]
doc["issues"][0]["acceptable_evidence_sets"] = [ev]
validate_truth(parse_truth(doc), pub)
print("loader accepted a required evidence set of", len(ev), "ids")
f = {"type": "payment_allocation", "affected_ids": ["I7", "P9"], "claimed_amount_minor": 100000,
     "currency": "KZT", "evidence_ids": ev, "explanation": ""}
try:
    parse_submission({"findings": {"episode_id": "ep-4c1f09", "findings": [f]}}, "ep-4c1f09", pub.manifest["limits"])
except Exception as exc:
    print(type(exc).__name__, exc)
EOF
```

```
loader accepted a required evidence set of 11 ids
MalformedSubmission findings[0].evidence_ids: must be a list of 0..10 ids
```

The same thing produced by the repo's own builder functions and PC-11, with one receipt spread over nine invoices:

<details><summary>Builder reproduction (30 lines)</summary>

```bash
uv run python - <<'EOF'
from genesis_audit import teaching, SCHEMA_VERSION
from genesis_audit.store import PublicEpisode, validate_public
from genesis_audit.truth import TruthIssue, validate_truth
from genesis_audit.schemas import parse_submission
from genesis_audit.errors import MalformedSubmission
N = 9
invoices = [{"doc_id": f"D{i}", "invoice_id": f"I{i}", "entity_id": "E1", "issued_at": f"2026-10-0{i}T10:00:00+05:00", "due_at": "2026-10-30T18:00:00+05:00",
             "currency": "KZT", "line_items": [{"description": "seat", "quantity": 1, "unit_price_minor": 1000, "amount_minor": 1000}]} for i in range(1, N + 1)]
payment = {"doc_id": "D90", "payment_id": "P1", "timestamp": "2026-10-20T09:00:00+05:00", "currency": "KZT", "amount_minor": 1000 * N, "invoice_refs": [f"I{i}" for i in range(1, N + 1)]}
row_ids = {"pay:P1:bank": "L900", "pay:P1:unapplied": "L901"}
for i in range(1, N + 1):
    row_ids[f"issue:I{i}:receivable"] = f"L1{i}"; row_ids[f"issue:I{i}:revenue"] = f"L2{i}"; row_ids[f"pay:P1:receivable:I{i}"] = f"L3{i}"
latent = {**teaching.LATENT, "invoices": invoices, "payments": [payment], "fx": [], "row_ids": row_ids}
rows = teaching.derive_clean_ledger(latent); teaching.check_identities(rows, latent)
rows, _ = teaching.inject_partial_allocation(rows, latent, invoice_id="I5", payment_id="P1", applied_minor=400)
teaching.check_identities(rows, latent)
inv = tuple({k: ({**i, "total_minor": 1000})[k] for k in ("doc_id", "invoice_id", "entity_id", "issued_at", "due_at", "currency", "total_minor", "line_items")} for i in invoices)
manifest = {"schema_version": SCHEMA_VERSION, "episode_id": "ep-x", "base_currency": "KZT", "period_start": latent["period_start"], "period_end": latent["period_end"], "timezone": latent["timezone"],
            "counts": {"ledger_rows": len(rows), "documents": N + 1, "fx_rates": 0}, "currencies": latent["currencies"], "rounding": {"permitted": ["half_up"], "default": "half_up"},
            "amount_tolerance_minor": {"KZT": 0, "USD": 0}, "issue_types": [teaching.ISSUE_TYPE], "limits": teaching.LIMITS}
ep = PublicEpisode(manifest=manifest, policy=teaching.POLICY, tables={"ledger": tuple(rows), "invoices": inv, "payments": (payment,), "fx": ()})
validate_public(ep)
issues = teaching.detect_allocation_issues(ep)
print("issues derived by the repo's own PC-11 convention:", [(i["affected_ids"], i["expected_amount_minor"], len(i["acceptable_evidence_sets"][0])) for i in issues])
truth = tuple(TruthIssue(f"t{n}", i["type"], frozenset(i["affected_ids"]), i["expected_amount_minor"], i["currency"], tuple(frozenset(s) for s in i["acceptable_evidence_sets"])) for n, i in enumerate(issues))
validate_truth(truth, ep); print("validate_truth: accepted")
f = {"type": issues[0]["type"], "affected_ids": issues[0]["affected_ids"], "claimed_amount_minor": issues[0]["expected_amount_minor"], "currency": "KZT", "evidence_ids": issues[0]["acceptable_evidence_sets"][0], "explanation": ""}
try: parse_submission({"findings": {"episode_id": "ep-x", "findings": [f]}}, "ep-x", teaching.LIMITS); print("the exactly-correct finding parses")
except MalformedSubmission as e: print("the exactly-correct finding is MALFORMED:", e.detail)
EOF
```

</details>

```
issues derived by the repo's own PC-11 convention: [(['I5', 'P1'], 600, 13)]
validate_truth: accepted
the exactly-correct finding is MALFORMED: findings[0].evidence_ids: must be a list of 0..10 ids
```

Why it matters. PC-11 asks for "the row_id of every ledger row carrying that payment_id" plus two documents. [S1] caps evidence at 10. A receipt with a bank row, eight or more allocation rows and two documents is past the cap, with or without an unapplied row. For such an issue the only correct finding is malformed, any 10-id subset is a false positive plus a miss, and abstaining is a miss. If it is the only issue in the episode the ceiling is -1 for every policy; with other issues the ceiling is below 1. Either way a reviewer would read the loss as a policy failure. `validate_truth` checks that evidence ids exist, and does not check: the size of an evidence set against `limits.max_evidence_ids`, the number of affected ids against 20, the amount against 2^53 - 1, or the type and currency against the finding token rules (`"Payment-Allocation"` and `"USDT"` were both accepted as declared values that no valid finding can carry). At 200 to 2,000 rows with batch receipts this stops being latent.

### AF-2 (row 11, high). A real public id of another kind voids a correct finding

```bash
uv run python - <<'EOF'
from genesis_audit import paths
from genesis_audit.env import AuditEnv, DirectorySource
env = AuditEnv(DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT))
for extra in ([], ["I7"], ["P9"], ["E4"], ["2026-10-14|USD|KZT"]):
    env.reset(config={"episode": "teaching_b"})
    f = {"type": "payment_allocation", "affected_ids": ["I7", "P9"], "claimed_amount_minor": 100000, "currency": "KZT",
         "evidence_ids": ["D31", "D44", "L11", "L19", "L26", *extra], "explanation": ""}
    reward = env.step({"action": "submit", "args": {"findings": {"episode_id": "ep-4c1f09", "findings": [f]}}})[1]
    print(extra, reward, env.evaluator_report()["findings"][0]["reasons"])
EOF
```

```
[] 1.0 ['matched']
['I7'] -1.0 ['evidence_id_not_in_public_records']
['P9'] -1.0 ['evidence_id_not_in_public_records']
['E4'] -1.0 ['evidence_id_not_in_public_records']
['2026-10-14|USD|KZT'] 1.0 ['matched']
```

Why it matters. PC-9 says evidence is valid "when every cited id exists in the public records" and that "extra real ids are allowed". I7 is in `invoices.jsonl`, P9 in `payments.jsonl`, E4 in both tables. The code's universe is narrower: `row_id`, `doc_id` and the FX key. A policy that follows the published sentence and cites the invoice id next to the invoice document loses 2.0 of reward on a perfect audit, and it cannot tell why, because the terminal observation is the same as for any other outcome. The evaluator's own reason string is false for these ids. The FX key is accepted although OQ-9 lists that as undecided. Either side can be the one to change: narrow the sentence in PC-9 to the three evidence id kinds and rename the reason, or widen the universe.

### AF-3 (row 30, medium). The issue id gives the answer away

```bash
uv run python - <<'EOF'
import hashlib, itertools, json
from genesis_audit import paths
from genesis_audit.env import AuditEnv, DirectorySource
env = AuditEnv(DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT))
def submit(findings):
    return env.step({"action": "submit", "args": {"findings": {"episode_id": "ep-4c1f09", "findings": findings}}})[1]
def listing(table):
    return env.step({"action": "list_records", "args": {"table": table}})[0]["records"]
obs, _ = env.reset(config={"episode": "teaching_b"})
first = submit([])
leaked = env.evaluator_report()["unmatched_issue_ids"][0]      # the only thing taken from the report
env.reset(config={"episode": "teaching_b"})                    # second attempt: tools only from here on
inv, pay, led = listing("invoices"), listing("payments"), listing("ledger")
answer = None
for i, p, cur in itertools.product(inv, pay, obs["manifest"]["currencies"]):
    for amount in range(1, max(x["amount_minor"] for x in pay) + 1):
        scored = {"type": obs["manifest"]["issue_types"][0], "affected_ids": sorted([i["invoice_id"], p["payment_id"]]),
                  "expected_amount_minor": amount, "currency": cur}
        text = json.dumps(scored, sort_keys=True, separators=(",", ":"))
        if "truth-" + hashlib.sha256(text.encode()).hexdigest()[:12] == leaked:
            answer = (i, p, amount, cur); break
    if answer: break
i, p, amount, cur = answer
evidence = [i["doc_id"], p["doc_id"], *[r["row_id"] for r in led if r["payment_id"] == p["payment_id"]]]
second = submit([{"type": "payment_allocation", "affected_ids": [i["invoice_id"], p["payment_id"]],
                  "claimed_amount_minor": amount, "currency": cur, "evidence_ids": evidence, "explanation": ""}])
print("first attempt", first, "| id from the report", leaked, "| recovered", (i["invoice_id"], p["payment_id"], amount, cur), "| second attempt", second)
EOF
```

```
first attempt -1.0 | id from the report truth-29d7352524bd | recovered ('I7', 'P9', 100000, 'KZT') | second attempt 0.994
```

Why it matters. `teaching._issue_id` is `"truth-" + sha256(canonical scored fields)[:12]` with no secret. The id is therefore a commitment to (type, affected ids, amount, currency), and the candidate space is tiny: public ids, declared currencies, amounts up to the largest payment. The id shows up in `evaluator_report()` (`matched_issue_id`, `unmatched_issue_ids`), which `play` prints after the episode, and in `EpisodeError` text. Any place that keeps issue ids (a result sheet, a training log, a bug report) then holds the answer key for every later run of that episode. Scope: the report is evaluator-side by design and is shown only after the end, so this is not a leak inside one episode.

### AF-4 (row 35, medium). Truth with an unreachable affected id, or with indistinguishable issues, is accepted

```bash
uv run python - <<'EOF'
import json
from genesis_audit import paths
from genesis_audit.store import load_public
from genesis_audit.truth import parse_truth, validate_truth
from genesis_audit.matching import match
from genesis_audit.schemas import Finding
pub = load_public(paths.PUBLIC_ROOT / "teaching_b")
doc = json.loads((paths.PRIVATE_ROOT / "teaching_b" / "truth.json").read_text())
doc["issues"][0]["affected_ids"] = ["I7", "P404"]
doc["issues"].append({**doc["issues"][0], "issue_id": "truth-000000000000"})
truth = parse_truth(doc); validate_truth(truth, pub)
print("loader accepted: affected id P404 (no tool returns it) and two issues with identical scored fields")
f = Finding("payment_allocation", ("I7", "P404"), 100000, "KZT", ("D31", "D44", "L11", "L19", "L26"), "")
for fs in ([f], [f, f]):
    r = match(fs, truth, tolerance=pub.manifest["amount_tolerance_minor"], universe=pub.evidence_universe())
    print(len(fs), "identical finding(s) -> tp/fp/fn", r.tp, r.fp, r.fn)
EOF
```

```
loader accepted: affected id P404 (no tool returns it) and two issues with identical scored fields
1 identical finding(s) -> tp/fp/fn 1 0 1
2 identical finding(s) -> tp/fp/fn 2 0 0
```

Why it matters. Two separate holes in `validate_truth`. First, affected ids are not checked against the public records, so an issue can require an id that only a guess can supply; on a temp copy of `teaching_b` with that truth, the audit-correct finding scored -1.0 and the finding naming the unfetchable id scored 1.0. Second, two issues with the same scored fields are accepted, and then the same finding sent twice is two true positives, which contradicts "repeated findings are false positives" and rewards the exact behaviour row 1 punishes. Neither shipped truth file has these defects.

### AF-5 (row 18, low). The `play` CLI dies on deeply nested JSON

```bash
uv run python -c "print('raw ' + '[' * 200000)" | uv run python -m genesis_audit play
```

```
    obj, end = self.scan_once(s, idx)
               ^^^^^^^^^^^^^^^^^^^^^^
RecursionError: maximum recursion depth exceeded while decoding a JSON array from a unicode string
```

Exit status 1. Why it matters. `cli._play_action` calls `json.loads` and the loop catches only `OSError` and `ValueError`. `canon.loads_strict` already converts `RecursionError` to `ValueError` and refuses duplicate keys and NaN, and it is not used here (row 17 is the same root cause: a file with duplicate keys was scored 1.0). This is the only place where policy-written JSON text is parsed today. A bridge that copies this parsing would let one line of input kill the evaluator.

### AF-6 (row 41, low). `money.convert_minor` rounds twice and raises the wrong error

```bash
uv run python - <<'EOF'
from decimal import InvalidOperation
from genesis_audit.money import convert_minor
print(convert_minor(3, 0, "0.166666666666666666666666666666", 0, "half_up"), "<- exact product 0.499999999999999999999999999998 rounds half-up to 0")
print(convert_minor(1, 0, "0.499999999999999999999999999999", 0, "half_up"), "<- exact product is below one half and rounds to 0")
try:
    convert_minor(10**28, 2, "500", 2, "half_up")
except InvalidOperation as exc:
    print("decimal.InvalidOperation", exc)
EOF
```

```
1 <- exact product 0.499999999999999999999999999998 rounds half-up to 0
1 <- exact product is below one half and rounds to 0
decimal.InvalidOperation [<class 'decimal.InvalidOperation'>]
```

Why it matters. The module says the conversion "is exact up to the single declared rounding step". The multiplication runs in the default decimal context, which rounds to 28 significant digits before `quantize` applies the declared mode. A rate may be 32 characters long, so the product can need more than 28 digits. `quantize` also raises `decimal.InvalidOperation`, not `ValueError`, once the result has more than 28 digits. No policy can reach this function today. It matters when FX truth and the calculator are built on it: a truth amount that is off by one minor unit under a zero tolerance turns a correct finding into a false positive plus a miss.

### AF-7 (row 25, low). `TypeError` where the harness expects `LifecycleError` or `EpisodeError`

```bash
uv run python - <<'EOF'
import json
from genesis_audit import paths
from genesis_audit.env import AuditEnv, DirectorySource
from genesis_audit.store import load_public
from genesis_audit.truth import parse_truth, validate_truth
try:
    AuditEnv(DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT)).reset(config={"episode": "teaching_b", 1: 2})
except Exception as exc:
    print("reset:", type(exc).__name__, exc)
pub = load_public(paths.PUBLIC_ROOT / "teaching_b")
doc = json.loads((paths.PRIVATE_ROOT / "teaching_b" / "truth.json").read_text())
doc["issues"][0]["currency"] = ["KZT"]
try:
    validate_truth(parse_truth(doc), pub)
except Exception as exc:
    print("truth:", type(exc).__name__, exc)
EOF
```

```
reset: TypeError '<' not supported between instances of 'int' and 'str'
truth: TypeError unhashable type: 'list'
```

Why it matters. A harness that catches the two documented error types will crash on these instead of reporting a bad config or a bad truth file. Both are one-line fixes (`sorted(map(repr, config))`; a type check on `type` and `currency` in `parse_truth`).

## 4. Spec gaps and contradictions

### 4.1 Where the spec and the code disagree

1. **PC-9 against the evidence universe (row 11).** "Exists in the public records" is wider than what the code accepts. Decide which is right, then make the sentence and the reason string say the same thing.
2. **OQ-9 is listed as open, and the code has already answered it (row 11).** FX keys are valid evidence ids today; policy clauses are not citable at all.
3. **PC-11 against the evidence cap (row 36).** Both rules are in the spec and they cannot both hold for a receipt carried by more than 8 ledger rows. Options: evidence is the rows that touch the affected invoice and payment together plus the unapplied row; or the generator bounds rows per payment and the loader enforces it; or the cap is treated as an open design consideration.
4. **Section 2 calls the error list closed and names 9 codes; `errors.py` registers 15 (row 21).** `action_too_large` and five `calc_*` codes are documented nowhere and raised nowhere.
5. **PC-6 against PC-7 (row 3).** Caps are applied to the list as sent, before the set is formed. PC-7 reads as if repeats were free.
6. **"Repeated findings are false positives" against a truth file with two indistinguishable issues (row 35).** The loader should refuse such truth or the sentence needs a condition.
7. **"A malformed final submission is -1" against PC-1 (row 15).** A submit attempt with a broken envelope is an invalid inspection, and on the last step that is worth 0.998 on clean books where a broken payload is worth -1.0.

### 4.2 Behaviour the spec does not state

- **Reset.** What `seed` does (today: nothing, any integer accepted). Which config keys exist (`episode`, `max_steps`). That `max_steps` may exceed the manifest limit and then disagrees with the manifest the policy sees. What a failed reset raises, with what text, and that the previous episode stays live (rows 24, 26). That `reset()` without a config raises.
- **Observation shape.** The `status: "episode_over"` key on terminal, truncating and post-end observations is not in section 2. The content of `info` (`env_version` at reset, empty on steps) is not stated.
- **Arguments.** An explicit `null` for `cursor` or `limit` is treated as absent. Cursor offset 0 is refused, leading zeros are accepted (`ledger:005`), and a cursor is a plain offset that any policy can write without having been given it. The last is fine if it is said.
- **Policy JSON as text.** Duplicate keys, NaN and Infinity, nesting depth, total size, and what "1,000 characters" counts (code points today, so 4,000 UTF-8 bytes pass, and a lone surrogate passes) (rows 17, 21).
- **`type` token.** The code requires a leading letter and allows doubled and trailing underscores (`a__b_` is well-formed, `_x` and `9x` are malformed). The spec says only "lower_snake_case token, 1-40 characters".
- **Evidence rule.** `observed` is collected and unused (row 8). If OQ-1 is answered "must be retrieved", note that one `list_records` call marks up to 50 rows as observed, so on a small episode the rule is nearly empty unless "retrieved" is defined more narrowly.
- **Amounts.** The tolerance is looked up under the issue's currency. Truth may hold a zero or negative expected amount (both loaded and matched in my runs), although PC-11 says "positive". `half_up` on a negative amount rounds away from zero in `money.py` (`convert_minor(-1, 0, "0.5", 0, "half_up")` returned -1 in this session); the spec does not define it.
- **PC-10 ties.** Equal scored fields are ordered by submission position (row 39).
- **PC-11.** Recorded or policy-ideal open balance (row 37). The order of two receipts with the same timestamp: the code sorts by `payment_id` as a string (read from the code, not run). A receipt that arrives before its invoice is issued.
- **Truth loader.** The list in section 1 covers evidence ids only. Missing: affected ids exist in public records, set sizes fit the caps, amounts fit the integer bound, types and currencies fit the finding token rules, no two issues share scored fields (rows 35, 36).
- **`manifest.issue_types`.** Global vocabulary or the types present in this episode? If it ever varies per episode it is a label. Today the twins differ at reset in `episode_id` and `counts.ledger_rows` only (row 32).
- **Reward incentives.** OQ-10 records the 0.8 for a truncated run on clean books. Not recorded: the same 0.8 goes to a policy that never emits a valid action (row 16); hedged amounts beat a single guess (row 4); one malformed finding costs more than any number of wrong ones (row 14).
- **Where the private half lives (row 33).** "Different roots" is satisfied by two sibling directories in one repo. Say whether teaching truth is meant to be public.

### 4.3 Rules that read as official and are the repo's choice, or cannot be traced

I have not seen [S1], so these are questions about tagging, not claims about what [S1] says.

- Section 1, "Record columns follow [S1] exactly": the inner keys of `line_items` (`description, quantity, unit_price_minor, amount_minor`) are enforced by the loader and listed nowhere in the spec. The structure of `policy.json` (`fx`, `cutoff`, `allocation`, `finding_conventions`) is not specified at all.
- Section 1: PC-12 names five manifest additions. The other manifest fields (`schema_version`, `base_currency`, `period_start`, `period_end`, `timezone`, `rounding`, `counts.ledger_rows`, `counts.documents`) carry no tag. The key order is enforced by the loader (`tuple(manifest) == _MANIFEST_KEYS`) and is not mentioned.
- Section 1: the load-rejection list has no tag.
- Section 2: "Errors are bounded: a code and a fixed message from a closed list" has no tag.
- Section 4: "A well-formed finding with an unknown type, an undeclared currency or a made-up id is not malformed" stands as a flat rule, and OQ-4 says the same point is undecided. It belongs under PC-6.
- PC-14 is tagged as a proposed convention and as [S1] in the same sentence.
- The open questions run OQ-1 to OQ-6 and OQ-8 to OQ-11. OQ-7 is missing.
- `docs/GRADING_CRITERIA.md` appeared during this review. I did not review it. It names a wall-time limit and a calculator among the tools; SPEC.md has neither.

## 5. Hypotheses for features that do not exist yet

None of this was run. Each line is a statement that must be true once the feature exists, written so that a test can fail.

### 5.1 Calculator

- **C1. Nothing is executed.** `__import__('os').system('id')`, `().__class__.__mro__`, `a.b`, `f(1)`, `x`, `lambda: 1`, `"1"*9`, `[1][0]`, `1 if 1 else 2`, `(x := 1)` each return `calc_syntax`. A test patches `builtins.eval`, `exec`, `compile` and `__import__` to raise and still gets `calc_syntax`. A static check finds no `eval`, `exec` or `compile` in the module.
- **C2. Bounds are checked before work is done.** Length before parsing (`calc_too_long`), nesting before recursion (`calc_too_deep`; 100,000 opening parentheses and 100,000 unary minus signs must not raise `RecursionError`), magnitude before arithmetic (`calc_overflow`). `9**9**9`, `10**10**10`, `1e999999999 + 1`, `1e-999999999`, a literal of 10^6 digits and `1/3` each return within a fixed time and memory bound. If exponentiation is not needed for the four families, it is not in the grammar.
- **C3. Arithmetic is declared.** Decimal only: `0.1 + 0.2` equals `0.3`. The precision, the rounding mode and the output format are written in the spec. `1/0` and `0/0` return `calc_div_zero`. `NaN`, `Infinity`, `sNaN`, `1_000`, `١٢٣`, fullwidth digits, a leading `+`, embedded newlines and NUL are each either refused or defined.
- **C4. The context is local.** The calculator does not change `decimal.getcontext()`, and its result does not depend on it. Every decimal signal is mapped to a code and never escapes as an exception (AF-6 shows the current helper lets `InvalidOperation` out and rounds twice).
- **C5. It follows the action contract.** A calculator step costs one step and returns reward 0. Errors are a code and a fixed message, and never echo the expression. The five `calc_*` codes are added to the list in section 2. The result is a bounded string.
- **C6. It is not a channel.** The same expression gives the same result on every episode and at every step. It reads no record and no truth. A calculator result is not an evidence id and adds nothing to `observed`.

### 5.2 Bridge and sandbox

- **B1. The boundary is enforced by the operating system.** A probe policy tries to open `episodes/private`, list its parent directories, read `/proc`, inherited file descriptors, environment variables and the working directory, and import `genesis_audit.truth` and `genesis_audit.paths`. Every attempt fails under confinement. The same probe succeeds with confinement off, which proves the probe works.
- **B2. Input is parsed strictly and bounded.** One JSON value per message, parsed with `canon.loads_strict`: duplicate keys, NaN, Infinity and deep nesting are invalid actions that cost a step and do not raise (AF-5, row 17). A byte limit returns `action_too_large`. Invalid UTF-8, lone surrogates, NUL bytes, a line with no terminator and a half-written message are each handled within a bounded read.
- **B3. Only the 5-tuple goes back.** For every exception class the evaluator can raise (`LifecycleError`, `EpisodeError` with its absolute paths as in row 26, and whatever `_submit` lets propagate from scoring), the bytes sent to the policy contain a fixed message and nothing else. Test: force each class and scan the wire.
- **B4. The policy has no control verbs.** It cannot call `reset` or `evaluator_report`, cannot choose the episode name or `max_steps`, and cannot obtain a second submission by reconnecting. A policy that exits, hangs or closes the pipe ends the episode in a defined way within a wall-time limit, and the evaluator never blocks on a read.
- **B5. Evaluator-side names do not cross.** The episode name (`teaching_b_clean`), directory paths, mount names, host names and container labels are absent from everything the policy process can read.
- **B6. The policy cannot write to the scorer.** Evaluator files are outside the policy's writable area. Results are written by the evaluator after the policy has exited.
- **B7. Resource limits hold.** Memory, CPU, process count, output volume and network are capped. A fork bomb, a 10 GB write and a sleeping policy each end in the defined termination.
- **B8. The submit branch is unambiguous.** Whatever is decided for row 15 is enforced at the bridge, including for a message that is not JSON at all.

### 5.3 Logging

- **L1. Two logs.** The policy-visible trajectory (actions, observations, rewards) and the evaluator log (validation errors, internal errors, verdict reasons, issue ids) are separate files with separate access. A canary scan of the policy-visible log finds no issue id, canary, injection id, private path, seed or evaluator-side episode name.
- **L2. Reproducible bytes.** The same episode and the same actions give the same canonical log and digest. No timestamp, pid or absolute path is inside the hashed part.
- **L3. What was sent is what is logged, safely.** An oversized action is stored as a length and a hash. An explanation with control characters or a lone surrogate is either refused upstream or logged without loss (row 21). One record per line; a newline in a string cannot forge a record.
- **L4. Issue ids in any log are opaque.** They are random, or keyed with an evaluator secret (AF-3). Otherwise the evaluator log must never reach the side that trains.
- **L5. After-end actions are logged and inert.** Actions after submit and after truncation appear in the log, are counted, and leave the score digest unchanged.
- **L6. Failed resets are logged and leave no live episode** (row 26).

### 5.4 Seeds and perturbation

- **S1. The seed has a stated meaning.** Either an unsupported seed is refused, or (episode, seed) fixes the public view: the same seed gives byte-identical observations, and different seeds give different id strings and row order.
- **S2. Perturbation is an isomorphism.** After mapping ids back, the public records, the truth and the score of any submission are identical for every seed. A correct finding is a true positive under 100 seeds. Affected ids and evidence sets are remapped together. FX keys are natural keys and cannot be renamed; the spec says how they are treated.
- **S3. Nothing public inverts to something private.** `episode_id`, row ids, document ids and cursors do not reveal the seed, the evaluator-side name or the label. Ids come from a keyed function with an evaluator secret, not from a hash of a public or guessable string (AF-3, row 31). The seed is in no observation, `info`, error, log line or file name.
- **S4. No public field carries the label.** Across the shipped set, no field of the reset observation (counts, id ranges, the largest row id) predicts clean against faulty, or the family, better than chance. Test: a one-feature classifier per field. Today `counts.ledger_rows` separates the twins (row 32).
- **S5. Memorised ids do not transfer.** The lookup policy of row 8, built on one seed, scores no better than abstention on another.
- **S6. Position carries nothing.** The score is the same under any permutation of the ledger. The injected row is not adjacent to its sibling by construction; today L26 directly follows L11.
- **S7. Cursors stay stable inside an episode under perturbation**, and the spec says whether a cursor from one episode is meaningful in another (today `ledger:5` works everywhere).
- **S8. The generator's randomness is local and versioned.** Calls to `random.seed()` in the evaluator or the policy process do not change any episode.

## 6. First 5 tests to implement

In priority order. The first four fail on the reviewed state. The fifth fails under the reading that a broken submit attempt is a malformed final submission, and needs that decision first.

1. **`tests/test_teaching_fixture.py::test_every_truth_issue_is_matchable_by_a_well_formed_finding`**
   For each shipped episode: build the mirror finding from each truth issue (its type, affected ids, amount, currency and first evidence set), assert that `parse_submission` accepts it and that `match` returns `tp == len(truth)`. Then assert that `validate_truth` raises `EpisodeError` for: an evidence set larger than `limits.max_evidence_ids`; more than 20 affected ids; an affected id that is no public invoice, payment, row, document or FX id; an amount beyond 2^53 - 1; two issues with the same scored fields; a declared type or currency that fails the finding token rules. Add the nine-invoice receipt of AF-1 and assert that the builder refuses it or that its evidence set fits the cap.

2. **`tests/test_reward_integrity.py::test_extra_public_id_of_another_kind_follows_the_published_rule`**
   For `x` in `"I7"`, `"P9"`, `"E4"`: `run(env, [finding(evidence_ids=EVIDENCE + [x])])` equals the value PC-9 gives. With PC-9 as written that is 1.0, and the test fails today (-1.0). If the code is kept, the test asserts -1.0, asserts that the verdict reason does not claim the id is absent from the public records, and a second assertion pins the FX key case to whatever OQ-9 becomes.

3. **`tests/test_teaching_fixture.py::test_issue_ids_are_not_a_function_of_the_scored_fields`**
   For every issue in every shipped truth file: `"truth-" + sha256(canon.dumps({type, affected_ids, expected_amount_minor, currency}))[:12] != issue_id`. If ids become keyed, also assert that rebuilding the fixture with a different evaluator secret changes every issue id and no public file.

4. **`tests/test_teaching_fixture.py::test_play_reads_policy_json_strictly`**
   Through `run_play`: `raw` followed by 200,000 `[` prints `Could not read that` and the session goes on to `quit` with status 1 and no exception. A findings file with a duplicated `episode_id` or a duplicated `claimed_amount_minor` is refused and not scored. `raw` with `NaN` is refused before it reaches the environment.

5. **`tests/test_reward_integrity.py::test_broken_submit_on_the_last_step_is_not_scored_above_a_malformed_one`**
   On `teaching_b_clean` with `max_steps=1`: the reward for `{"action": "submit"}` is not greater than the reward for `{"action": "submit", "args": None}`. Today the values are 0.998 and -1.0. The same test at the default budget after 99 invalid actions: 0.8 and -1.0.

Next after these, all small: `tests/test_money.py::test_conversion_is_exact_beyond_28_significant_digits` (fails today, AF-6); the two `TypeError` cases of AF-7 (fail today); `tests/test_env_lifecycle.py::test_no_action_is_accepted_after_truncation` (passes today, row 23); `tests/test_env_fuzz.py::test_step_never_raises_and_errors_come_from_the_closed_list` with the canary scan (passes today, rows 19 and 28); `tests/test_teaching_fixture.py::test_twins_differ_at_reset_only_in_episode_id` (fails today, row 32).
