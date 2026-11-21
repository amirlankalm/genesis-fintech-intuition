# Environment spec (public)

What a policy and a reviewer may rely on. Status: engine, four error families, a seeded generator, shipped episodes and the jury adapter. The case was published on 19 November 2026 and the official check definitions on 20 November 2026 (a copy is `docs/reference/fintech-checks-2026-11-20.md`). On 20 November the environment was fully reconciled with both. This text describes the code as it is after that reconciliation.

Four kinds of statement appear here and they are kept apart:

- **[S1]** is taken from the official Genesis Hackathon case specification.
- **[K]** comes from the official check definitions of 20 November 2026. A check id (C19, T05, M10, ...) is given where one applies.
- **PC-n** is a *convention* of this repo where the case is silent. Anything without an [S1] or [K] tag is our team's choice. [K] leaves some rules to the team: the family rules, the canonical `affected_ids`, the evidence sets and the tolerance. Where it does, the PC is that published rule.
- **OQ-n** is an open design question. Section 11 says which ones [K] answered and how.

## 1. Episode files

One episode is one synthetic company and one reporting period [S1]. The two halves live under different roots.

| Half | Location | Files |
|---|---|---|
| Public | `episodes/public/<name>/` | `manifest.json`, `policy.json`, `ledger.csv`, `invoices.jsonl`, `payments.jsonl`, `fx.csv` |
| Private | `episodes/private/<name>/` | `truth.json`, `provenance.json` |

Record columns follow [S1]:

- `ledger.csv`: `row_id, timestamp, account, debit_minor, credit_minor, currency, entity_id, invoice_id, payment_id`
- `invoices.jsonl`: `doc_id, invoice_id, entity_id, issued_at, due_at, currency, total_minor, line_items`
- `payments.jsonl`: `doc_id, payment_id, timestamp, currency, amount_minor, invoice_refs`
- `fx.csv`: `date, source_currency, target_currency, rate`

Money is integer minor units; timestamps are ISO-8601 with an offset; rates are decimal strings [S1].

- **PC-12** The manifest holds what [S1] lists (`schema_version`, `episode_id`, `base_currency`, `period_start`, `period_end`, `timezone`, row and document counts, permitted rounding) and adds `currencies` (exponent per currency), `amount_tolerance_minor` (per currency), `issue_types`, `limits` and `counts.fx_rates`. `counts.documents` is invoices plus payments. Our files write the keys in a fixed order: `schema_version, episode_id, base_currency, period_start, period_end, timezone, counts, currencies, rounding, amount_tolerance_minor, issue_types, limits`. The loader accepts any key order and rebuilds this one (PC-38).
- **PC-22** A line item has `description, quantity, unit_price_minor, amount_minor`. `policy.json` has `policy_version`, `fx`, `cutoff`, `allocation` and `finding_conventions`; a case policy adds `accounts`, `time`, `posting`, `duplicates` and `overlap` (section 6).
- **PC-15** In CSV an empty field is an explicit null. In JSON it is `null`.
- **PC-23** An episode is rejected at load if: a header or key list differs (as a set; order does not matter), an id is not well formed or repeats within its id space (PC-37), a reference names a missing record, the public half holds any file but its six, the private half any file but `truth.json`, `provenance.json` and an optional `ANSWER_KEY.md`, a limit in the manifest exceeds the draft's, a ledger row has both or neither side non-zero, debits and credits differ in any currency, an invoice total differs from its lines, a currency is undeclared, or the manifest counts are wrong. Balance is the one accounting identity every episode satisfies. A case episode must also satisfy the posting structure of PC-29. Balanced, well-structured books can still be wrong: that is what truth is for. All of this is the *strict* load. It is used by `DirectorySource`, by `check` and for every shipped and generated episode. A jury directory loads non-strictly (PC-38).
- **PC-24** Truth is derived, never trusted. At load the published rules are applied to the public records, and a truth file that differs from the result in any issue, amount or evidence set is refused: an answer key that the records do not support describes some other books. A truth file is also rejected if a correct audit could not be written as a well-formed finding that matches it, or if an issue's amount is within the tolerance (a claim of nothing would match it). That means any of these:
  - an evidence set cites an id no tool returns a record or document for (PC-9), or is larger than the evidence cap;
  - an affected id is not in the public records, or there are more than 20;
  - the type is not in `manifest.issue_types`;
  - the currency is undeclared;
  - the amount is beyond 2^53 - 1;
  - two issues share type, affected ids and currency;
  - there are more issues than one submission may hold.

  The truth file itself is parsed in any key order. Each issue must have `issue_id` (a string, unique), `type` and `currency` (strings), `affected_ids` (a non-empty list of strings), `expected_amount_minor` (an integer, not a bool) and `acceptable_evidence_sets` (a non-empty list of non-empty lists of strings). Unknown keys are refused when strict and ignored with a warning otherwise.
- **PC-37 Ids.** An id is any non-empty string of at most 256 Unicode code points. It may not contain control characters (U+0000-001F, U+007F-009F) or lone surrogates. `store.is_valid_id` is the one gate: the loader, `get_record` and `get_document` all use it. Ids are unique within each id space, never across spaces. The spaces are: ledger `row_id`; `doc_id` across invoices and payments together; `invoice_id`; `payment_id`; FX key (`date|source|target`). `entity_id` has no uniqueness rule. The same string may appear in different spaces, and it names a different record in each. Ids are compared as exact strings everywhere. In a finding or a truth file an id is just a string: a finding that cites an id of another shape is scored, not malformed (PC-6). A cursor is not an id. It has its own bound of 64 characters.
- **PC-38 The jury loading path.** `episodes.load_episode_dir(path, *, strict)` loads one flat directory (any name). The directory holds the six public files, `truth.json`, and `provenance.json` if present. Any other file is ignored, and its name goes to the evaluator log.
  - Parsing does not depend on key order anywhere (manifest, JSONL lines, `line_items`, policy, truth), and the CSV columns may come in any order. Records are rebuilt in canonical key order, so observations stay deterministic. A policy equal to a published one, in any key order, is shown in the published order. Files are read as UTF-8 with an optional BOM. CRLF line ends and trailing empty lines are tolerated. A blank line inside the data is still refused.
  - Rows page in the order the files hold them. No sort order is required.
  - `strict=True` is the PC-23 load.
  - `strict=False` is the jury path: the adapter loads every `episode_dir` this way. Formats stay enforced in both modes. That covers the manifest (keys, types, limits no larger than the draft's, a tolerance for every currency, rounding), id shape and per-space uniqueness, timestamps with an offset, integer amounts, the `line_items` shape, `invoice_refs` as a list of ids, and FX dates and rates.
  - With `strict=False`, consistency becomes warnings on logger `genesis_audit.loader` (`LoadedEpisode.warnings`) instead of refusals. That covers:
    - undeclared currencies, a ledger row with both or neither side non-zero, empty accounts, unresolved references, balance, positive amounts, line arithmetic and totals, repeated or unknown `invoice_refs`, receipts for one invoice at one instant, FX currencies and `manifest.counts`;
    - the policy-version contract (PC-29 and section 6.0);
    - truth against the records (PC-24);
    - truth against the rules (the size envelope, the step budget, tolerance 0, the four family rules).

    A jury fixture (5 records, τ = 1, a hand-written truth, an unpublished policy) therefore loads and is scored against its own truth. A truth currency the manifest does not declare gets τ = 0 (`LoadedEpisode.tolerance()`).

Episode names such as `teaching_b` or `dev_04` are evaluator-side. The environment never gives a policy a name or a path; section 8 says what a policy can read from process metadata regardless. `manifest.timezone` is a label: no code resolves it. The offsets written in the timestamps are what count.

**The shipped truth is public on purpose.** Both halves of the teaching, fixture, train and dev episodes are in this repository: they are worked examples and public practice data. Held-out episodes must not be: set `GENESIS_AUDIT_PRIVATE_ROOT` and `GENESIS_AUDIT_PUBLIC_ROOT` to directories outside any agent-readable path, and `GENESIS_AUDIT_SECRET_FILE` to the evaluator's key.

### Private file formats (evaluator only)

`truth.json` is `{"issues": [...]}`; each issue has exactly `issue_id, type, affected_ids, expected_amount_minor, currency, acceptable_evidence_sets` [S1]. `acceptable_evidence_sets` is a list of alternative id lists. Issue ids are keyed with the evaluator's secret and say nothing about the answer.

`provenance.json` records how the episode was made. Case episodes: `builder`, `variant`, `canary`, `injections`, `status`, `families`, `split`, and for generated episodes `generator` (`seed`, `config`, `inject`). `inject` is written in one fixed spelling: zero counts are dropped, and an interaction without parameters is written as its bare name. So an inject written before sub-kinds and parameters existed (PC-35) keeps its spelling and its episode. `status` is `clean` with no injection, `interaction` when at least one interaction scenario was injected, otherwise `faulty`; `families` is the sorted list of families injected. Each injection has `injection_id`, `family`, `error` (what the clerk did), `expected` (the issue it should cause: `type`, `affected_ids`, `amount_minor`, `currency`), `causal_note` and `changes`. A change is one of:

- `{"op": "update", "table", "id", "field", "before", "after"}`
- `{"op": "insert", "table", "record"}`
- `{"op": "delete", "table", "record"}`

`table` is `ledger` (`id` is the `row_id`) or `invoices` (`id` is the `invoice_id`). Undoing every change, last injection first and last change first, gives the clean books: the public records of the same company with no error. Inserts and deletes carry no position: the ledger order is time, then `row_id`. The four teaching episodes keep their older format: `mutation`, `target`, and changes written as `{"op": "update", "table", "row_id", "field", "before", "after"}` or `{"op": "insert", "table", "after_row_id", "row"}`.

## 2. Observation and actions

`reset(seed, config) -> (observation, info)` and `step(action) -> (observation, reward, terminated, truncated, info)` [S1].

The initial observation holds `task`, `manifest`, `policy` and `steps_remaining` [S1]. The policy object is given in full, since it is small. In `train` mode the reset `info` holds `env_version` and `mode`. Every other `info` is `{}`: every step in both modes, and the reset in `eval` mode (PC-16). These are the core shapes. The jury adapter renames a few keys and wraps results in the official shapes (section 2a).

**PC-1** An action is a JSON object with exactly the keys `action` and `args`.

| Action | Args | Returns |
|---|---|---|
| `list_records` | `table`, optional `cursor`, optional `limit` | `records`, `next_cursor` |
| `get_record` | `table`, `id` | `record` |
| `get_document` | `doc_id` | `record` |
| `calculator` | `expression` | `result` |
| `submit` | `findings` | ends the episode |

Tables: `ledger`, `invoices`, `payments`, `fx`. Every observation carries `steps_remaining`. The observation that ends an episode also carries `status: "episode_over"`. There is no shell, SQL, filesystem or network tool [S1].

- **PC-4** A page is in file order. `limit` is an integer from 1 to 50, default 50; anything else is an error, not a silent clamp. `null` for `cursor` or `limit` means absent. A cursor is `<table>:<offset>`: a plain offset, not a secret, valid only for its own table, stable for the life of the episode, and accepted only as the environment writes it (no leading zeros, no offset 0).
- **PC-5** `get_record` ids: `row_id` for the ledger, `invoice_id` for invoices, `payment_id` for payments, `date|source|target` for FX rates. `get_document` takes a `doc_id`. An id that is not well formed (PC-37), or that names no record, is `unknown_id`. Either way it costs a step.
- **PC-25** Errors are bounded: a code and a fixed message from a closed list. They never echo the input, a path or a record. The codes: `invalid_action`, `unknown_action`, `bad_arguments`, `unknown_table`, `unknown_id`, `bad_cursor`, `bad_limit`, `action_too_large`, `calc_syntax`, `calc_too_long`, `calc_too_deep`, `calc_div_zero`, `calc_overflow`, `episode_over`, `internal_error`.
- **PC-26** One action is at most 262,144 bytes as UTF-8 JSON, the newline excluded. Over that it is `action_too_large`, costs a step and is not stored. The one exception is an oversized action whose top-level `action` is `"submit"`: it is a malformed submission (terminal, -1), in process and over the bridge alike. The bridge finds that member wherever it sits in the line by scanning the line as a stream (`bridge.SubmitScanner`), with the same rule as PC-19. Policy-written JSON is parsed strictly: duplicate keys, `NaN`, `Infinity` and nesting deeper than 16 levels are invalid. One episode may send at most 32 MiB in total; more ends it (`protocol_abuse`). Each line is one action: an empty line, or the JSON value `null`, is an invalid action. A last line without its newline is still read, unless it is over the size bound.

### Calculator

**PC-21** A parser, never an evaluator. Grammar: decimal numbers (`12` or `12.50`), `+ - * /`, unary `+` and `-`, parentheses, spaces. Nothing else: no names, calls, exponents, separators or other digits.

- Bounds, checked before any work: 256 characters, nesting depth 32, literals of 40 characters, magnitude below 10^40.
- Arithmetic: decimal, 50 significant digits, half-even. Output: plain decimal notation, at most 18 fractional digits, trailing zeros removed.
- It reads no record and no truth, and its result is the same in every episode. A result is not evidence.

## 2a. The jury adapter

The official checks call `judge_adapter.py` at the repository root [K, «Единый способ подключения»]. It provides `generate_episode(seed, config, output_dir)`, `make_env()` (with `reset` and `step`) and `score_episode(episode_dir, findings, inspection_steps)`. It is a thin translation over this environment, with no second generator, loader or scorer. The full reference is `docs/ADAPTER.md`, and the machine-readable schemas are in `docs/schemas/`. In short:

- **Modes.** `reset` takes `config = {"mode", "episode_dir", "team_config"}`. Mode `closed` (the adapter default) loads exactly `episode_dir` through the jury path (PC-38) and runs the core in `eval` mode. It ignores the seed and never generates or renames. Mode `train` loads `episode_dir` if one is given. Otherwise it generates in memory from `(seed, team_config)`, which is the same episode `generate_episode` writes. `team_config` has the generator config shape of PC-35.
- **Envelope.** `step` takes `{"name", "args"}`. The adapter swaps `name` for the core's `action` and passes everything else through unchanged, so PC-19 applies as written.
- **Observations.** The first observation is `{task, manifest, policy, remaining_steps}`, and later ones are `{result, error, remaining_steps}`.
- **Errors.** The public error codes are those of PC-25 plus `invalid_submission`.
- **Rewards and info.** In closed mode the reward is `0.0` at every step and `info` is `{}` (PC-16).
- **Wall time.** A truncation by time gives `result: null, error: null, truncated: true`.
- **Scoring.** `score_episode` returns `{tp, fp, fn, precision, recall, f1, return}`. It uses the same code, evidence universe and tolerance as the environment's own end-of-episode scoring (`scoring.score_submission`, `PublicEpisode.accessible_ids()`, `LoadedEpisode.tolerance()`). An invalid structure gives `return` -1.0 and `null` for the other six, and the reason goes to the evaluator log only.
- **Baselines.** The four benchmark reference policies run through the adapter as `baselines/`, and `make judge` runs them.

## 3. Budget, modes and termination

At most 100 steps, including the submission [S1]. Inspection reward is 0 [S1].

- **PC-2** Every `step` call on a live episode costs one step, including an invalid action, an unknown id, a calculator call and a line the bridge rejected. `inspection_steps` is every step before the `submit`, errors included, and the submit is not one of them [K].
- **PC-3** Precedence at the limit: a `submit` on the last allowed step is accepted and gives `terminated=true` [K C16: 99 inspections and a submit as step 100 count 99 inspection steps]. If the last allowed step is an inspection, its result is still returned, and the same transition has `truncated=true` [K C17: 100 inspections end truncated with empty findings].
- **PC-14** A truncated episode is scored as an empty final submission, which is [S1]'s wording.
- **PC-13** After the end, any further action returns `episode_over` with reward 0 and changes nothing. Such actions are counted in the evaluator report and are not logged as transitions. There is no second submission.
- **PC-16** Two modes [S1]. In `train` (the core default) the terminal step returns the reward. `eval` is the closed mode [K]. There the reward is the number `0.0` at every step, the terminal step and any step after the end included [K C19]. `info` is `{}` throughout, the reset included. The true reward and every diagnostic stay with the evaluator; `reward_withheld` no longer exists. In both modes the core's terminal observation is the same for a perfect, a wrong and a malformed submission. Through the adapter, a perfect and a wrong submission both give `{"accepted": true}`. A malformed one gives the bounded structural error `invalid_submission`, which the official interface allows, and never a correctness signal (section 2a).
- **PC-17** Wall time: 60 seconds per episode by default [S1's proposed envelope]. The window opens at the top of `reset` [K]: before the episode is loaded, generated or perturbed, so the environment's own work counts. A caller that opened it earlier can pass `reset(..., started_at=t)`, a reading of the environment's own clock. A future, non-finite or non-numeric value is refused. The adapter passes the time it read at the top of its own `reset`, before it loads or generates. Policy time counts. An action that arrives after the deadline is not executed, even a `submit`: the episode is truncated with empty findings [K C18]. The limit must be finite and at most one day. It can be switched off only for in-process use; an episode over the bridge always has one. Wall time is the one input that is not a function of seed, config and actions: a replay re-applies a recorded truncation instead of re-timing it.
- **PC-18** The evaluator can force a truncation with cause `wall_time`, `policy_exit` (the policy process ended or closed the pipe) or `protocol_abuse` (it flooded the bridge). Actions the policy had already written before it exited are still served, in order.
- **PC-19** Which branch an input takes:

| Input | Branch |
|---|---|
| Any JSON object whose `action` is exactly `"submit"`, however broken the rest | Submission attempt. If the envelope or payload is wrong it is malformed: the episode ends at -1 [S1]. |
| Any other invalid action | Inspection error: bounded code, one step, the episode continues. |
| A line that fails strict parsing (duplicate key, `NaN`, a number too large to read, deep nesting) and whose text is an object with a top-level member `"action": "submit"` | Submission attempt, malformed: -1. The test is a single pass over the characters that reads only the string literals directly inside the outermost object, so it gives the same answer on every interpreter. |
| A line over the size bound that has a top-level member `"action": "submit"` | Submission attempt, malformed: -1 (PC-26). |
| Any other line that fails strict parsing, or any other line over the size bound | Inspection error. It cannot be recognised as a submission, so it is not one. |

- `max_steps` in the config can shorten the budget for a test. It cannot exceed the manifest's limit.
- **PC-36 Reading cost.** One `list_records` call returns one page of at most 50 records, so reading a table of n records costs `ceil(n / 50)` steps. An episode is refused at build and at load unless every record of all four tables can be read once and one step is left for the submit. At the draft's largest size (2,000 ledger rows, 200 documents) that is 40 + 4 + the rate table: the shipped generated episodes need between 8 and 52 steps (`docs/measurements/scale.json`). Reading everything is therefore always possible, and costs up to about 0.10 of reward at the largest size and 0.016 at the smallest. A policy that reads less pays less.
- A failed `reset` leaves no live episode.

## 4. Findings

`submit` takes `{"findings": {"episode_id": ..., "findings": [ ... ]}}`. Each finding has exactly these keys [S1]:

`type, affected_ids, claimed_amount_minor, currency, evidence_ids, explanation`

**PC-6** "Malformed" means the structure is wrong, and nothing else. Only a value of the wrong JSON type, a missing required key or an exceeded limit is malformed [K, matcher convention 8]:

| Field | Structural rule |
|---|---|
| document | a JSON object with the key `findings`; `episode_id` is optional, and if present must be a string equal to this episode's id; other keys are ignored |
| `findings` | a list of at most 30 [S1] |
| finding | a JSON object with the six keys; other keys are ignored |
| `type` | a string |
| `affected_ids` | a list of strings (any length) |
| `claimed_amount_minor` | a JSON integer: not a bool, a string or a fraction [K M09] |
| `currency` | a string |
| `evidence_ids` | a list of strings, at most 10 as sent, repeats included [S1; K M05] |
| `explanation` | a string of at most 1,000 Unicode code points, counted after JSON decoding [S1; K convention 7] |

A malformed final submission ends the episode at -1, and the validation error goes to the evaluator log only [S1; K T18-T20]. The parser is `schemas.parse_findings_document`.

- A well-typed finding is **not** malformed when it has an unknown type string, any currency string (`"kzt"`, `"KZT "`), ids of any shape, an empty or long `affected_ids` list, or an integer amount of any size. It is scored, and it is a false positive [K conventions 4, 5, 8; M06].
- One malformed finding makes the whole submission malformed.
- The core's submit *args* envelope is still exactly `{"findings": ...}`: it is part of the action protocol, like the arguments of every other action.
- **PC-7** `affected_ids` and `evidence_ids` are sets: order and repeats inside one list do not matter [K M01]. The evidence cap applies to the list as sent, before repeats are removed [K M05]. Nothing else is canonicalized. Types, currencies and ids are compared as exact strings, with no case folding, trimming or number-to-string conversion [K conventions 1, 5].

## 5. Matching

A finding may be paired with a truth issue only if all of these hold [S1]:

1. same `type`;
2. same `affected_ids` set;
3. same `currency`;
4. `|claimed_amount_minor - expected_amount_minor| <= tolerance`;
5. the evidence is valid and complete.

- **PC-8** The tolerance τ is absolute, inclusive, an integer and in minor units: `abs(claimed_amount_minor - expected_amount_minor) <= τ` [K «Допуск суммы»]. τ is published per currency in `manifest.amount_tolerance_minor`. Our episodes publish τ = 0 for every currency, so for all four types (`duplicate_invoice`, `payment_allocation`, `fx_mismatch`, `cutoff`); the strict load refuses anything else. A jury fixture may declare another τ (for example τ = 1, [K M08]). A truth currency the manifest does not declare gets τ = 0 (`LoadedEpisode.tolerance()`), the official default. Inside is a pass and outside is a fail; there is no amount bonus.
- **PC-9** Evidence ids are the ids a tool returns a record or document for: a ledger `row_id`, a document `doc_id`, an `invoice_id` or `payment_id` (`get_record` takes them) or an FX key. Evidence is valid when every cited id is one of those, and complete when the cited set contains at least one acceptable evidence set. Any other cited id makes the finding unmatched, so it is a false positive and not a structural error [K convention 3, M04]. That covers an invented id, an `entity_id` and an `issue_id`. Extra accessible ids are allowed, up to the cap of 10 [K convention 3, M03]. The environment, `score_episode` and truth validation all use this one set, `PublicEpisode.accessible_ids()`. The task text and every case policy's `finding_conventions` tell the policy this. In our episodes the acceptable sets name only row ids, document ids and FX keys, so the broader universe stops voiding a finding but cannot create a match. What this condition can and cannot do: it rejects a claim that does not name the required records, and ids no tool returns. It cannot tell an audit from a guess that happens to cite the right ids, and on an episode this small it separates little that the other four conditions do not.
- **PC-27** `evidence_rule` in the config. `accessible` (the default, [S1]'s and [K]'s wording) asks only that cited ids are in the universe of PC-9. `observed` also asks that each was returned by a tool in this episode. A fetched invoice or payment counts with both its `doc_id` and its `invoice_id` or `payment_id`. Note its limit: one `list_records` call returns up to 50 records, so on a small episode it adds little. The adapter always uses `accessible`.
- **PC-10** True positives are the size of a *maximum* one-to-one matching [K]. Repeated findings are separate vertices, so they are never merged [K M12]. Among the maximum matchings the verifier picks the official one [K «Неоднозначные совпадения»]. First, the truth `issue_id`s are sorted by Unicode code points. Then the matching whose sorted sequence of `(issue_id, finding index from 0)` pairs is lexicographically smallest is chosen (`matching.choose_pairs`: greedy over issues in order and indices ascending, with a check that a maximum matching still exists). So M10 gives F1→A and F0→B, and M11 gives A→F0 and B→F1. Among correct findings for one issue, the lowest index wins. Submission order can change only which of the equally fitting findings is reported, never TP, FP, FN or the reward. The evaluator report names the matched issue for each finding.
- Unmatched and repeated findings are false positives; unmatched issues are false negatives [S1]. The explanation text is never scored.

## 5a. Reward

The common reward is the draft's [S1], unchanged:

```
P  = TP / (TP + FP)        R = TP / (TP + FN)        undefined P or R is 0
F1 = 2*TP / (2*TP + FP + FN)                         truth and findings both empty: F1 = 1
reward = clip(2*F1 - 1 - 0.002 * inspection_steps, -1, 1)
```

- Every inspection step returns reward 0. The episode return is the terminal reward alone [S1].
- A malformed final submission is -1 directly [S1].
- There is no experimental reward variant in this repo. If one is added it must sit beside the common reward, never replace it.
- The official table T01-T20 and the examples M01-M12 [K] are pinned in `tests/test_official_matcher.py`, exactly (for example 47/150 and -871/1050) and as floats to 1e-9.
- Arithmetic is exact (rational numbers); the float appears only in the step tuple. The evaluator report also keeps TP, FP, FN, F1 and the value before clipping, because clipping makes different failures look the same.

Worked values at 30 inspections are in `docs/tutoring/C_reward.md`. They are calculated examples.

## 6. The four families

All four rules are given to the policy in `policy.json` (`policy_version: case-draft-2`) and are decided from the public records alone. **They are this repository's published conventions (PC-11, PC-28 to PC-34).** The case names the families. [K] leaves the rules to the team: it sets no universal formula for every accounting scheme, it has the team publish the canonical affected ids per type in the matcher, and it has the independent checks follow the documented postings and policy of each environment. That answers OQ-2, OQ-3 and OQ-17 to OQ-21 (section 11). The four teaching episodes keep their smaller policy (`teaching-1`), which declares `payment_allocation` only; everything below applies to episodes whose policy has an `accounts` block.

`manifest.issue_types` lists the families in scope for the episode. A case episode always lists all four, in this order: `duplicate_invoice`, `payment_allocation`, `fx_mismatch`, `cutoff`. It does not say which are present.

### 6.0 Time and posting structure

- **PC-28 Time.** Timestamps are compared as instants. The company's local time is the UTC offset written on `manifest.period_start`; no daylight-saving change happens inside an episode. An instant is *inside* the period when `period_start <= t <= period_end`, *before* it when earlier and *after* it when later. A local calendar date is the date of the instant at the company's offset, whatever offset the record itself was written with. Records are written at different offsets on purpose: the date printed in a timestamp is not always its local date.
- **PC-29 Posting structure.** `policy.accounts` names five accounts: `receivable`, `revenue`, `bank`, `unapplied`, `fx_clearing`.

| Event | Rows |
|---|---|
| Invoice record | One receivable debit and one revenue credit, each for the invoice total, in the invoice currency, both carrying the `invoice_id` and no `payment_id`, with the same timestamp. |
| Receipt | One bank debit for the document amount in the document currency, carrying the `payment_id`. Then credits in the *invoice currency*: at most one receivable row per referenced invoice (carrying both ids), and unapplied rows. Together they equal what the receipt brings. All of these rows carry the instant of the payment document. |
| Receipt in another currency than its invoices | Also one `fx_clearing` credit for the document amount in the receipt currency, and one `fx_clearing` debit for the translated amount in the invoice currency. What the receipt brings is that debit. |
| Refund of unapplied credit | Unapplied debits and bank credits of equal total, all carrying the `payment_id` of the receipt they return, at any later time. Never more than that receipt's unapplied credit. The generator writes at most one refund per receipt. |
| Anything else | Rows with neither an `invoice_id` nor a `payment_id`. They are other journal entries and take no part in any rule. |

A receipt with empty `invoice_refs` is in its own currency and has nothing to allocate. All invoices one receipt references are in one currency, and no invoice is referenced twice by one receipt (the loader refuses that). "The receipt's timestamp" always means the `timestamp` of its payment document. An `invoice_id` appears on ledger rows only in the two ways the table names: the invoice's own two rows, and receivable credits of receipts.

Ledger rows are in time order, ties broken by `row_id`; documents are in a keyed order that means nothing. A whole-minute clock is used throughout, so no generated instant falls in the second between `period_end` (23:59:59) and midnight; one that did would be after the period.

An episode whose books break this structure is **refused at build and at load**; it is not an issue. So are: no single published rate for a receipt that needs one; a currency pair quoted in both directions; a translation with the base currency on neither side; a recorded allocation above the required one; two receipts for one invoice at the same instant; a receipt that references invoices of more than one customer; a refund that is in another currency than its receipt, not later than it, or of a translated receipt; and records that cannot all be read within the step budget (one call per page of each table, at least one call per table, plus the submit).

**The contract of an episode is fixed by its policy version, not by its files.** There are two published versions, `teaching-1` and `case-draft-2`. `case-draft-2` replaced `case-draft-1` on 20 November 2026. It made two changes. The allocation evidence of a receipt in another currency also cites the receipt's `fx_clearing` debit (6.2). Each convention's further evidence may now be any id a tool returns a record or document for (PC-9). `case-draft-1` is no longer loaded. At load, `policy.json` must name one of them and be that policy's text, word for word; the manifest must carry that version's schema version and its families (one for teaching, all four for a case episode), the draft's budget and caps exactly (100 steps, pages of 50, 30 findings, 10 evidence ids, 1,000 characters), half-up rounding and a tolerance of 0. A root whose files say otherwise (a rewritten rule, a dropped block, a borrowed version name, a raised tolerance, pages of 2,000 rows) is a different game and does not load. An episode for a family nobody has published a rule for cannot be loaded at all. These checks run on the clean books and again after every injected error. They exist so that the four rules below are the only ways the books can be wrong, and each is decidable. Balanced, well-structured books can still be wrong: that is what the rules are for. On the jury path (PC-38) these contract checks, and the structure checks of this section, are evaluator-log warnings instead of refusals.

### 6.1 `duplicate_invoice` (PC-30)

- **Rule:** two or more invoice records describe one obligation recorded more than once when their `entity_id`, `currency`, `issued_at` instant, `due_at` instant and `line_items` are all identical. Records that differ in any of these are separate obligations, however similar. Instants are compared, not strings: a copy may be written at another offset. `line_items` are compared as the list written: same items, same order, same integers.
- **`affected_ids`:** the `invoice_id` of every record in the group. One issue per group.
- **`claimed_amount_minor`:** the invoice total times (records in the group minus one): the amount recorded in excess. Positive, in the invoice currency.
- **`evidence_ids`:** the `doc_id` of every invoice record in the group.

### 6.2 `payment_allocation` (PC-11)

- **Meaning:** a proven receipt was allocated to its referenced invoice for less than the allocation policy requires. A receipt is proven by its `payments.jsonl` document.
- **Allocation policy:** a receipt is allocated to each invoice in its `invoice_refs`, in order, up to that invoice's open balance when the receipt arrives. Only an excess over the open balance stays in `unapplied_receipts`. With several references, what one invoice does not absorb goes to the next.
- **What a receipt brings:** its document amount when receipt and invoice currency are equal; otherwise the translated amount *as recorded* (the `fx_clearing` debit). See 6.5.
- **Order and open balance:** receipts are taken in order of their payment timestamp. An invoice's open balance is its total minus what this policy *required* earlier receipts to allocate to it, whatever was recorded. An invoice has its full open balance from its record alone: when it was posted plays no part, so a receipt that arrives before the posting is allocated like any other. Two receipts for one invoice at the same instant have no defined order: such an episode is refused, because breaking the tie by id would make truth depend on how ids are spelled.
- **Recorded allocation:** the receivable credits that carry both that `invoice_id` and that `payment_id`. There may be none: then the allocation is missing altogether.
- **`affected_ids`:** the `invoice_id` and the `payment_id`. One issue per invoice and payment pair.
- **`claimed_amount_minor`:** required allocation minus recorded allocation, positive, in minor units of the invoice currency.
- **`evidence_ids`:** the invoice `doc_id`, the payment `doc_id` and the `row_id` of every receivable row carrying both ids (none when the allocation is missing). When the receipt is in another currency than the invoice, the set also holds the `row_id` of the receipt's `fx_clearing` debit. That row is the recorded translation, which is what the receipt brings, so the amount follows from the cited records alone [K, Block 2 condition 4]. A same-currency set has no `fx_clearing` row.

### 6.3 `fx_mismatch` (PC-31)

- **Rule:** a receipt in another currency than its invoices is translated into the invoice currency at the `fx.csv` rate dated on the receipt's **local calendar date** (PC-28). One of the two currencies is always the base currency. `fx.csv` quotes each pair in one direction only, and exactly one row exists for that date and pair.
- **Arithmetic:** a rate is target units per one source unit. Multiply when the receipt currency is the row's `source_currency`; divide when it is the row's `target_currency`. Work in major units and round once, half up, to the minor units of the invoice currency:
  `translated_minor = round_half_up(amount_minor / 10^receipt_exponent  (* or /)  rate * 10^invoice_exponent)`. The computation is exact (rational); no intermediate rounding. Exact ties are rare in generated data, so half-up and half-even seldom differ there; `tests/test_families.py` pins the tie cases.
- **Issue:** the recorded translation (the receipt's `fx_clearing` debit) differs from the required one.
- **`affected_ids`:** the `payment_id`.
- **`claimed_amount_minor`:** the absolute difference, positive, in minor units of the invoice currency. Direction is not encoded.
- **`evidence_ids`:** the payment `doc_id`, the id of the fx row the policy selects (`date|source_currency|target_currency`) and the `row_id` of the receipt's `fx_clearing` debit.

### 6.4 `cutoff` (PC-32)

- **Rule:** revenue belongs to the period that contains the invoice's `issued_at`. The invoice's revenue row must be on the same side of the period as `issued_at`: before, inside or after (PC-28). A posting made earlier or later than `issued_at` on the same side is not an error.
- **`affected_ids`:** the `invoice_id`.
- **`claimed_amount_minor`:** the invoice total, positive, in the invoice currency.
- **`evidence_ids`:** the invoice `doc_id` and the `row_id` of its revenue row.

The guide's cutoff example recognises a service at completion time, a fact the schema does not carry; the final case keeps that schema and leaves the period boundary to `policy.json` (OQ-8, answered). This rule uses `issued_at`, which the schema does carry.

### 6.5 Overlap and interaction (PC-33)

Each rule is applied to the records independently. One record may be part of issues of different families. Within a family one discrepancy is one issue: no two issues share type, affected ids and currency.

- **A wrong translation is not also an allocation shortfall.** Allocation is measured against the translated amount that was *recorded*. If a receipt is translated at the wrong rate and the recorded amount is then allocated as the policy requires, there is one issue, `fx_mismatch`. Only when the recorded amount is *also* under-applied is there a second, `payment_allocation`, for the part of the recorded amount that was not applied.
- **A duplicate record on the wrong side of the period is two issues.** The record should not exist (`duplicate_invoice`, both ids) and its revenue row is on the wrong side (`cutoff`, that record's id). They are two rules broken and two amounts, even though they share a document.
- **A misdated invoice whose receipt is under-applied is two issues**, sharing the invoice document as evidence.

Three interaction scenarios are generated. Two of them are the documented ones that [K] Block 2 counts (D16-D18 and D19-D20). The case asks for at least two and gives an example; it does not fix which ones.

| Scenario | What the clerk did | Issues | Parameters |
|---|---|---|---|
| **Interaction 1, `cutoff_and_allocation`** | posted an invoice's revenue row on the wrong side of a period boundary, and under-applied its receipt | `cutoff` {invoice} and `payment_allocation` {invoice, payment}, sharing the invoice document | `boundary` start\|end, `allocation` missing\|partial, `receipt_currency` same\|foreign |
| **Interaction 2, `duplicate_then_cutoff`** | keyed an invoice a second time and posted the copy on the wrong side of a boundary | `duplicate_invoice` {both records} and `cutoff` {the copy} | `boundary` start\|end, `copy_offset` same\|other (the copy's `issued_at` written at the original's offset or another) |
| extra, `fx_then_allocation` | translated a receipt at a rate the policy does not select, then under-applied the recorded amount | `fx_mismatch` {payment} and `payment_allocation` {invoice, payment} | `fx_error` date\|rate, `allocation` missing\|partial |

The case's own example, a part payment in another currency at a period boundary, is Interaction 1 with `{"allocation": "partial", "receipt_currency": "foreign"}`. A parameter that is not given is drawn from the seed. The one exception is `fx_then_allocation` without `allocation`, which is always partial, as its bare name always was. Amounts, currencies, ids and dates always come from the seed and the company. `world.INTERACTION_1`, `world.INTERACTION_2` and `world.SCENARIO_PARAMETERS` hold these names and values.

### 6.6 Valid look-alikes

Every generated company contains each of these whether or not it has errors, so no error is the only record with its surface feature (PC-34). The generator places them on purpose, whatever the seed. `tests/test_generator.py` counts fifteen kinds in all twenty shipped companies and in fresh companies made with another key:

| Looks like | But is valid because |
|---|---|
| Missing allocation: a receipt names an invoice and has no receivable row | The customer paid twice; the invoice was already settled, so the whole second receipt is unapplied credit. Sometimes refunded. |
| Partial allocation: less than the receipt amount on the invoice | An overpayment (only the open balance is applied), or one receipt for two invoices. |
| An invoice with an open balance | Part payments and unpaid invoices: no receipt proves more. |
| An invoice written at an offset unlike its customer's others | About one invoice in ten is written at another branch's offset, and so is often the second of a valid same-instant pair. A copy written at another offset is not the only such record. |
| Duplicate invoice: same customer, same lines, same total | A weekly plan: the records differ in `issued_at` and `due_at`. Identical invoices to two *different* customers at one instant. Valid siblings: a second invoice of *one* customer at one instant, made from a record chosen at random, exactly as a copy is, that then differs in one of the two things the rule names beyond customer, currency and instant: half have one line replaced, half have other payment terms. Any record may get a sibling, also one that already has one, so three records of one customer at one instant are ordinary. How many siblings a company has is drawn (between an eighth and a third of its invoices), and a sibling is drawn as a copy is in everything the rule does not name: half are posted together with the first record and half whenever, four in ten are written at another offset, and none has a receipt. Only comparing the lines and the due date tells a copy from a sibling. What remains is a statistical hint, not a mark: copies add second records, so a company with unusually many is somewhat more likely to hold copies. |
| FX mismatch: translated amount is not `amount * rate` | The pair is quoted the other way (divide): every company has a translation that multiplies and one that divides, on the same pair. The local date differs from the date printed on the receipt. The product needed rounding. |
| Cutoff: the dates printed on invoice and posting are in different months | Written at another offset, both instants are on the same side. Clean postings also trail `issued_at` by up to six days or precede it by up to three, and an injected error stays inside that range: only the boundary tells them apart. |
| An unapplied balance | Receipts that name no invoice; overpayments not yet refunded. |

### 6.7 The hand-built fixture

One small invented company (`fixture_*`, 45 to 47 ledger rows), written by hand, one variant per family and per interaction. Base KZT (exponent 2), USD (2), JPY (0), company offset +05:00, period October 2026. The numbers below were worked by hand and are pinned in `tests/test_case_fixture.py`; the full reasoning is in `episodes/private/fixture_clean/ANSWER_KEY.md`.

| Variant | What the clerk did | Issue | Amount |
|---|---|---|---|
| `fixture_clean` | nothing wrong | none | |
| `fixture_duplicate` | keyed weekly invoice `I26` a second time as `I33` | `duplicate_invoice` {I26, I33} | 80,000 KZT minor |
| `fixture_allocation` | left receipt `P22` (80,000) wholly unapplied | `payment_allocation` {I26, P22} | 80,000 |
| `fixture_fx` | translated USD 100.00 (`P31`, written 20 Oct 21:30 UTC, local date 21 Oct) at the 20 Oct rate 490 instead of 500 | `fx_mismatch` {P31} | 5,000,000 - 4,900,000 = 100,000 KZT minor |
| | translated 200,000.00 KZT (`P40`) into JPY at 3.36 instead of 3.40: 59,524 instead of 58,824 | `fx_mismatch` {P40} | 700 JPY |
| `fixture_cutoff` | posted `I11` (issued 31 Oct 22:00) on 1 Nov 09:00 | `cutoff` {I11} | 120,000 |
| `fixture_x_fx_allocation` | the 490 rate again, and then applied only 4,000,000 of the 4,900,000 recorded | `fx_mismatch` {P31} and `payment_allocation` {I08, P31}; the allocation evidence includes P31's `fx_clearing` debit (6.2) | 100,000 and 900,000 |
| `fixture_x_duplicate_cutoff` | keyed `I11` again as `I35` and posted the copy on 1 Nov 08:30 | `duplicate_invoice` {I11, I35} and `cutoff` {I35} | 120,000 and 120,000 |

The clean variant already holds the look-alikes: three weekly invoices with identical lines; a split payment; an overpayment with a refund; an invoice written as 1 November at +09:00 that is 31 October 23:15 local; an invoice issued and posted after the period; a JPY invoice settled in KZT at a rate that needs rounding (200,000.00 / 3.40 = 58,823.53, half up 58,824).

## 7. Seeds, the generator and perturbation

**PC-35 The generator.** `shipped.generate(seed, config, inject)` builds one company and one reporting period.

- `config`: `base_currency`, `foreign_currencies` (at least one), `timezone` (a zone without daylight-saving time), `period` (`YYYY-MM` or `YYYY-Qn`), `invoices` (12 to 110), `ledger_rows` (200 to 2,000, a target), `head_days` and `tail_days` (3 to 12: the records start before the period and run past it, so that both boundaries can be tested). `Asia/Almaty` is refused when the period start minus `head_days` is before 2024-03-01, because the zone was UTC+06:00 before that date (`world.ALMATY_SINCE`).
- `inject`: every key is optional and every count is a non-negative integer (a bool is refused).
  - One count for each family: `duplicate_invoice`, `payment_allocation` (missing or partial, drawn), `fx_mismatch` (wrong date or wrong rate, drawn) and `cutoff` (the boundary is drawn).
  - Counts for sub-kinds. The truth type of a sub-kind is its family's.
    - `payment_allocation_missing`: a receipt that names an open invoice has no allocation row at all.
    - `payment_allocation_partial`: more than 0 and less than required is applied, in one receivable row.
    - `fx_mismatch_date`: the receipt is translated at the `fx.csv` rate of another date of the pair.
    - `fx_mismatch_rate`: the receipt is translated at a mistyped rate. No `fx.csv` row of the pair has that rate, and no row gives that translated amount.
  - `interactions`: a list of scenario names, or of `{"name", <parameters>}` objects (6.5).

  Each family and each sub-kind can be switched on alone. Sub-kinds are drawn after the families, and zero counts and parameterless objects keep the old spelling, so an inject written before them regenerates unchanged. `world.validate_inject` checks every key, count and interaction entry. It also checks the issue total (one per count, two per interaction) against the envelope of 0 to 12, before anything is generated.
- One parser, `shipped.parse_config`, reads `{"generator": {...}, "inject": {...}}`. Both sections are optional, and `null` is the same as `{}`. It serves the adapter's `generate_episode` config and the train-mode `team_config`. Unknown keys at any level are refused with the reason. `shipped.generate_files` returns the eight files flat. The schema is `docs/schemas/generator_config.schema.json`, and a test keeps it equal to the parser.
- An allocation sub-kind prefers a receipt whose required amount follows from the two documents alone: the same currency as the invoice, the invoice first in `invoice_refs`, and no earlier receipt for that invoice. Its acceptable evidence set is then enough by itself. A request the company cannot hold is refused with a message that says why, for example no receipt in another currency left to mistranslate, no invoice near the requested boundary, or errors that would push the company past 2,000 rows or 200 documents.
- The latent company depends on seed and config only. Errors are chosen afterwards from a separate stream, so a clean company and the same company with errors are *twins*: same records and same ids, except what the errors touch.
- Order of construction: latent history; clean books posted as the policy requires; structure checked; the clean books must raise no issue; each error applied as what an erring clerk would have posted; the difference recorded with before and after values; truth computed from the final public records by the rules of section 6, which never see the errors; what each error should have caused compared with what the rules found; structure checked again. Any disagreement refuses the episode.
- The generator enforces the draft's size envelope [S1]: 200 to 2,000 ledger rows, 20 to 200 documents, 0 to 12 issues. `ledger_rows` is a target for the padding: other journal entries are added until the count is within about fifteen rows of it, never exactly on it, so that a round count says nothing. A company whose invoices and receipts alone need more rows than the target simply has more.
- Each company keeps its own margin from the edges of the envelope, drawn from its seed (up to 28 rows and 14 documents). Errors add or remove a few records; with one fixed margin, a count beyond it would mean "errors were added". A company at the very edge whose errors do not fit is refused, with the reason. A weak signal remains at the very top of the envelope and is not removed: errors add records, so among companies generated for the largest settings, those within a document or two of 200 are somewhat more often faulty (the independent grader measured 17 faulty to 10 clean above 198 documents, against a base rate of 0.38).
- What is recorded regenerates what was built: `provenance.generator` (seed, full settings, `inject` in one fixed spelling) fed back to the generator with the same key gives the same files.
- Errors are placed where only the rule finds them: a misdated posting keeps a lag clean postings also have and may cross either boundary; some copies are written at another offset; some under-applied receipts are followed by a second receipt for the same invoice, so the order and open-balance rule decides; some wrong rates are the rate of the date printed on the receipt.
- All draws come from HMAC-SHA256 with the evaluator's secret. Ids are keyed labels with one template for every record of a kind. Ledger rows are in time order; documents are in keyed order. Nothing is drawn from Python's `random` module or a clock.
- Currencies are real codes at invented, round reference values. Rates are a small random walk, not market data. Nothing is taken from a real company.

**Shipped episodes and splits (`episodes/splits.json`).** Seven fixtures, ten train, ten dev. Among the twenty generated: five clean and five interaction episodes, mirroring the mix [S1] proposes for evaluation. Train seeds lie in 101 to 110 and dev seeds in 201 to 210; no seed is in both. The twenty episodes are eighteen companies: a twin pair shares one seed and is always in one split (`train_01`/`train_02`, `dev_03`/`dev_04`). Dev companies have base currencies and company offsets no train company has (JPY, GBP and KWD as base, KWD with three decimals; companies at +05:30, +04:00 and +09:00). Individual records in train are written at many offsets, those included. Seeds, settings and what was injected are in the private half only. Held-out episodes are generated the same way with a private secret and other seeds: `python -m genesis_audit generate`.

**PC-20 The seed in `reset(seed, config)`.**

- Without `perturb` in the config, the seed is recorded and changes nothing: the episode is the one named.
- With `perturb: {"rename_ids": bool, "shuffle_rows": bool}` and an integer seed, the episode is a harmless variant: every row, document, invoice, payment and entity id is renamed consistently, and the rows of every table are reordered. Amounts, timestamps, accounts, links and the policy do not change. FX keys are natural keys and are not renamed.
- The variant is driven by HMAC-SHA256 with the evaluator's secret. The new ids, the new `episode_id` and the re-keyed issue ids reveal nothing about the seed without that secret. Its output is pinned by a known-answer test.
- Perturbation defeats memorised ids. It does not defeat memorised amounts.
- The default secret is a public development key. With it, nothing is confidential, and cheaply so: a policy that has this repository can recognise a shipped episode from its `episode_id` alone, in a fraction of a second and with zero steps, and so knows whether it is clean and what its answers are. The shipped episodes are practice data with public answers. A score on them means something only for a policy that cannot see this repository; anything else needs a private key, private seeds and private roots. `generate` says so on stderr whenever it runs with the public key.

The same seed, config, version and actions give the same records, transitions and rewards [S1]. This is checked by regenerating every shipped file byte for byte and by the committed digests, on Python 3.11, 3.12 and 3.13 and on Linux.

## 8. Isolation

The evaluator holds the truth. A policy runs in another process and talks to it over one channel: JSON lines on a pipe, actions one way and the five-tuple the other. The policy has no control verbs: it cannot reset, choose an episode or read a report.

A separate process is structure, not secrecy: with the same user id it can read every file its parent can, and can kill it. The boundary is an operating-system backend:

| Backend | Enforced by | A hostile policy cannot |
|---|---|---|
| `seatbelt` (macOS) | sandbox profile | read the home, temporary or external volumes except its interpreter and its own code; read any path named as private, wherever it lies; write any file; use the network; fork; signal another process |
| `setuid` (POSIX, evaluator as root) | user ids and file modes | read or write anything that is root-only. The run is refused unless truth, records, source and tests are all root-only; signal the evaluator |
| `docker` | mounts | see anything but its own code: nothing else is mounted. No network; read-only root; capped pids, memory and CPU |
| `none` | nothing | nothing is protected |

What "private" covers: truth and provenance, the evaluator's key, and also the public records (they cost steps), the source and the tests. The only way to learn anything is through the bridge.

Two different containers appear in this repo and should not be confused. The `docker` backend starts one small container per policy, with only the policy code in it. `make docker-check` builds an image that holds the whole repo and runs the *evaluator* in it as root; there the policies run under `setuid`, and the private files are present but mode-protected.

- The policy's environment variables are scrubbed, and it starts in `/`.
- It runs in its own process group. When the episode ends the whole group is killed, so a child it started cannot linger or hold the pipes open.
- On the local backends its limits are lowered before it starts: CPU seconds and file size everywhere; address space where the platform enforces it (not macOS); process count under `setuid`.
- The evaluator never blocks on the policy. Reading, writing and stderr each have their own thread; the queue of incoming lines is bounded; only the first 2,000 bytes of stderr are kept, in memory.
- `auto` picks the strongest backend the machine has. If there is none, the run is refused: no boundary is used only when `none` is asked for by name. The self-check still runs in that case, and fails its boundary line.
- If the evaluator itself fails (for example a scoring bug), nothing is sent to the policy.

- A policy can read the command lines of other processes, and on macOS their initial environment. The CLI moves its own arguments off its command line, but it cannot clean a launcher's: whatever is typed after `uv run`, `make` or a shell stays visible there. Anything that must stay private (a held-out episode name, a seed) goes in a job file inside a private path: `run --job FILE`.
- Under `seatbelt` the policy can still read the rest of the system outside those areas, for example `/etc` and the list of installed applications.

Not protected: the initial environment of same-user processes under `seatbelt` (measured; the sandbox rules that block it also stop the interpreter); timing side channels; a policy that shares the evaluator's Python process (the `play` command and in-process calls are for trusted callers); loopback sockets under `setuid`, unless the container has no network; memory under `seatbelt`; a child that leaves the process group on purpose under `none` or `setuid` (under `seatbelt` it cannot fork, under `docker` the container is killed).

## 9. Logging and replay

- **Policy-visible trajectory:** one record per transition with `episode_id, step, action, observation, reward, terminated, truncated` [S1], plus `info` and `event`. `event` is `reset`, `step` or `forced_truncation`; it is set by the evaluator, so a policy action of JSON `null` cannot pass for a truncation. The log contains only what the policy saw and did, and no clock time.
- **Evaluator report (private):** seed, config, mode, termination cause, step counts, validation error, the score with its raw components, a verdict and reasons per finding, unmatched issue ids, internal errors, and the SHA-256 digest of the canonical trajectory.
- **Harness:** `python -m genesis_audit harness` runs, on whatever episodes are under the configured roots (shipped or held-out): the boundary probe (aimed at an episode that is there), a load of every episode (files, posting structure, the fixed contract, truth as the rules derive it), the independent checker, all eight policies, replay of every run, the leak scan, an id-and-order pair per episode and the truth-blind solver with a perturbed twin. `check` is the same on the shipped episodes plus byte-for-byte regeneration, the committed result sheet, digests and trajectories, and the stored measurements (everything in them that is not a clock or memory reading must equal a fresh measurement). `generate --job FILE` writes held-out episodes from a private job file, so seeds and settings never appear on a command line.
- **Replay:** re-running the recorded actions with the same seed and config must give the same digest and the same score, and both must equal the digest of the saved log itself. So a changed action, a forged score, and an edited observation or reward in the saved file are each detected. `python -m genesis_audit replay` does this for everything `baselines` saved.
- **Committed digests:** `docs/DIGESTS.json` lists, for every baseline run, the trajectory digest, the exact reward and the step count. The self-check recomputes them, so another machine can verify bit-for-bit agreement without trusting its own first run.

## 10. Consequences of the common reward worth knowing

These follow from [S1]'s formula and its rule that truncation is an empty submission. They are pinned by tests so that they are known. They are not "fixed" here.

- **Doing nothing is perfect on clean books.** A policy that exits, hangs or floods before its first action is truncated with zero inspection steps and scores 1.0 on a clean episode. One that burns all 100 steps and never submits scores 0.8. The official table has the same values [K T03, T15, T17].
- **Always-abstain is a strong lazy baseline.** It scores +1 on clean and -1 on faulty books. With a clean share p its mean is 2p - 1: -0.5 on the four teaching episodes (one clean), -0.6 on train (two of ten) and -0.4 on dev (three of ten). The shortcut baselines score below it; the policy-aware reconciliation scores above it.
- **Most of a rule earns part of the score.** The shipped naive baseline ignores the policy text and stays near the floor. A policy that implements most of each rule does not: the independent grader's own averaged -0.25 on fresh companies, with a best episode of 0.55. The gap between "near the floor" and "solved" is not empty.
- **Reading is taxed, so the ceiling for an honest reader falls with size.** A policy that reads every record and is right scores 1 - 0.002 x pages: 0.984 on the smallest generated company and 0.896 on the largest. Only a policy that knows where to look can do better.
- **No signal below a complete finding.** A finding earns nothing until type, ids, amount, currency and evidence are all right. The random inspector scores -1 on every generated episode, faulty or clean (it always claims something). The draft rules out partial credit in the common reward; an experimental reward would have to sit beside it.
- **Hedging beats a miss.** Two claims on one issue with different amounts score 1/3 when one is right; a single wrong guess scores -1.
- **Malformed is the worst case.** One malformed finding costs -1; thirty wrong but well-formed ones cost at most the same.

## 11. Key design questions and resolution

These design questions were addressed during development. The final case (19 November 2026) and the official check definitions [K] (20 November 2026) answer all but two. Each answer below gives the official rule and what the code does now.

### Answered

- **OQ-1** Does a superset of an acceptable evidence set count as complete? Must evidence have been retrieved in the episode, or is it enough that it is accessible? **Answered** [K convention 3, M03, M04]. A superset counts: extra existing, accessible evidence is allowed. Accessible is enough. A non-existent or inaccessible id makes the finding FP. The code follows this (PC-9). `evidence_rule: observed` remains an option outside the official path (PC-27).
- **OQ-2** What does `claimed_amount_minor` mean for each family, with what sign? Is the tolerance absolute or relative? **Answered** [K «Допуск суммы», convention 6]. The amount is a JSON integer in minor units, compared exactly by default (τ = 0). The team publishes any other τ in advance as a fixed non-negative integer, and the condition is `abs(claimed - expected) <= τ`, so the tolerance is absolute. What the amount means for each family is the team's published rule: here a positive amount, as section 6 defines it per family (PC-8).
- **OQ-3** What are the canonical `affected_ids` for each family: invoice and payment ids, ledger row ids, or both? **Answered** [K convention 2]. They form a set that must equal the issue's canonical set exactly, and the team publishes the canonical rule per type in its matcher code. Ours are in section 6 and in each policy's `finding_conventions`.
- **OQ-4** Is an unknown `type` or undeclared `currency` malformed (-1) or merely wrong (a false positive)? **Answered** [K conventions 4, 5, 8; M06]. It is a false positive. Only a wrong JSON type, a missing required key or an exceeded limit is structural (PC-6).
- **OQ-5** Do error steps and calculator calls count as `inspection_steps` in the cost term? **Answered** [K «Общие пограничные решения»]. Yes: every step before the submit counts, errors included, and the submit does not (PC-2).
- **OQ-7** In evaluation mode, what does the reward field of the terminal step hold? **Answered** [K C19]. The number 0, with no diagnostics in `info` or in the final answer (PC-16).
- **OQ-8** [S1]'s public schema has no service-completion time. Which cutoff policies are meant to be decidable from the listed fields? **Answered.** The final case keeps the schema and gives the period boundary to `policy.json` (§03). [K] D14-D15 asks only that the evidence and the period boundaries are accessible and that the timezone follows the manifest and policy. A rule on `issued_at` is therefore a legitimate published policy (PC-32).
- **OQ-9** Can FX rows and policy clauses be cited as evidence, and under what ids? **Answered** [K convention 3]. Any existing id that is accessible through the tools may be cited. FX rows can, under their key `date|source|target`. Policy clauses cannot, because no tool returns them (PC-9). [K] Block 4 also says that an FX key is a natural key, not a surrogate id, and is not renamed.
- **OQ-10** Are the consequences in section 10 intended, in particular a perfect score on clean books for a policy that never acts? **Answered** [K T03, T15]. T03 gives F1 = 1 for empty truth and empty findings. T15 shows that F1 = 1 at zero inspection steps gives a reward of 1. Together they pin exactly what section 10 describes.
- **OQ-11** Is `explanation` required, and are extra keys in a finding malformed? **Answered** [K convention 8, T20]. `explanation` is one of the six fields of a finding in §05, and a missing required field is structural. Here leaving it out is treated that way. The official structural list does not include extra keys, so here they are ignored (PC-6).
- **OQ-12** When does the wall clock start, and does environment compute count against the policy? **Answered** [K «Общие пограничные решения», C18]. The clock runs from the start of reset to the end of the episode, policy time included. Container build and fixture preparation are excluded. Here the window opens at the top of `reset`, before loading or generation (PC-17).
- **OQ-14** With a 10-id evidence cap, how should an issue be evidenced when its natural evidence is larger? **Answered** [K T19, M05, convention 3]. The cap of 10, counted as sent, is final. One complete acceptable set must fit, and extra ids are optional. Here every acceptable set fits, and an episode whose set would not fit is refused (OQ-22).
- **OQ-15** Is `manifest.issue_types` the global vocabulary or the types present in this episode? **Answered.** `issue_types` is not a field the case requires. [K convention 4] asks only for an exact match with one of the team's documented type values. Here a case episode always lists all four types, so the key reveals nothing.
- **OQ-16** For payment allocation: may one receipt reference invoices of different entities? Is an empty `invoice_refs` valid? When a later receipt over-allocates to make up an earlier shortfall, is the earlier shortfall still an issue? **Answered** [K Block 2, «Необходимая реализация жюри»]. The independent checks follow the documented postings and policy of each environment, and the case sets no universal formula. So these are ours to publish. A receipt for more than one customer is refused. An empty `invoice_refs` is valid and has nothing to allocate. A recorded allocation above the required one is refused, so a later receipt cannot make up an earlier shortfall, and the earlier shortfall stays an issue: open balances follow what the policy *required*, not what was recorded (6.0, 6.2).
- **OQ-17** Duplicate invoices: the invoice schema has no supplier or external invoice number. What makes two records "the same invoice"? Is a second *posting* of one invoice record also meant? **Answered** as OQ-16: the rule is the team's, and [K] D06-D08 asks only that legitimate repeated amounts do not automatically become duplicates. Here two records are one obligation when they have identical entity, currency, issue and due instants and line items (PC-30). A second posting of one record is a broken episode, not an issue.
- **OQ-18** FX: the ledger rows carry one currency each and there is no "translated amount" field. Where is a translation recorded, and which amounts are translated at which date? **Answered** [K D12-D13]. The policy for choosing the date, the rate and the direction of the pair decides, and no outside market data is added. Here only a receipt in another currency than its invoice is translated, shown through a clearing account, at the receipt's local date (PC-31).
- **OQ-19** Cutoff: is `period_end` inclusive? Which event fixes the period? **Answered** as OQ-8: the policy decides. Here the event is `issued_at`, compared as an instant, with both ends inclusive (PC-28, PC-32).
- **OQ-20** Interactions: when two rules are broken on overlapping records, is that one issue or two, and may a later error be defined relative to an earlier one? **Answered** [K Block 2]. The jury uses exactly the two scenarios the team implemented and documented, and changes their parameters. Here an interaction gives two issues, allocation is measured against the recorded translation (PC-33), and the two documented scenarios are those of 6.5.
- **OQ-21** Refunds have no document type in the case. **Answered** as OQ-16: the documented postings decide. Here a refund is two ledger rows that carry the `payment_id` of the receipt they return (PC-29).
- **OQ-22** With `evidence_ids` capped at 10, a duplicate group of more than ten records could not be evidenced. **Answered** with OQ-14: the cap is final. Such an episode is still refused.

### Still open

- **OQ-6** For `limit` above 50: clamp or error? The case says only that a page holds at most 50 rows, and [K] C05 pages with `limit=50`. Neither text decides between a clamp and an error. Here it is an error, `bad_limit` (PC-4), which is consistent with both.
- **OQ-13** Is a final line that is not valid JSON a malformed submission (-1) or an invalid action? [K] does not say. On the jury path the question does not arise, because `step` receives a Python object. On our JSON-lines bridge, PC-19 decides.

## 12. Limitations and Honest Scope

This section addresses the honest limitations of the environment (aligned with Criterion E5):

1. **Rule-Following Solver vs. Learned Models.**
   - A deterministic rule-following script (`baselines/solver.py`) scores $F_1 = 1.000$ and return $0.961$ across the 20 shipped train and dev episodes, and achieves $F_1 = 1.0$ across 138 self-check runs over all 31 shipped episodes (including perturbed twins).
   - This finite empirical evaluation on the 31 shipped episodes demonstrates that the shipped benchmark scenarios are solvable from public records under the published policy rules, rather than serving as a formal proof for all arbitrary cases or unconstrained accounting topologies.
   - However, this benchmarks structured record parsing and compliance logic, not generalized natural language understanding or ambiguous real-world accounting judgment.
   - No machine learning model or neural network was trained in this submission, and no training claims are made.

2. **Containment Boundary and What It Does Not Protect.**
   - In container execution (`make docker-check`), the evaluator runs as `root` and policies run under an unprivileged user (`setuid`). On macOS, policies run under `sandbox-exec` (Seatbelt).
   - What is protected: The policy process cannot read `truth.json`, `provenance.json`, private generator seeds, evaluator memory, or host filesystem paths outside `/app/policies`. Network access is disabled via `--network none`. Hostile probes attempting these operations are denied and verified in tests.
   - What is not protected: Process confinement relies on OS privilege separation and Seatbelt/Docker isolation. It does not patch host kernel vulnerabilities, prevent memory exhaustion if external cgroup limits are absent, or isolate against physical side-channels.

3. **Calculated vs. Measured Quantities.**
   - Exact structural quantities: Step budgets (100 steps maximum), reading costs (52 steps maximum required to exhaustively read the largest episode), and decimal minor unit representations are exact by construction.
   - Measured empirical quantities: Wall-clock execution durations (< 0.13 s for the slowest solver episode) and peak resident set size (evaluator ~43 MB, policy ~28 MB) recorded in `docs/measurements/scale.json` are empirical measurements on the test machine and will vary with host hardware.

4. **Memorisation vs. Generalization.**
   - A memoriser policy that stores and replays known answers achieves $F_1 = 0.000$ and return $-1.000$ on unseen twin episodes with renamed identifiers and shuffled rows (scoring identically to an abstaining policy at $-1.000$).
   - This proves the benchmark cannot be solved by memorising static identifiers.

5. **Generator and Accounting Model Boundaries.**
   - All simulated companies use a uniform double-entry bookkeeping model with standardized charts of accounts and accounts receivable flows.
   - The generator supports scales from 200 to 2,000 ledger rows across 6 fiat currencies. It does not model complex corporate consolidations, inventory valuation methods (FIFO/LIFO), or taxation jurisdictions.

6. **Accounting Identities vs. Audit Ground Truth.**
   - Double-entry balance ($\sum \text{Debits} = \sum \text{Credits}$) is validated by construction. Balanced books do not imply error-free records: clerk mistakes such as wrong cutoff dates, unapplied cash receipts, and exchange rate misstatements persist within mathematically balanced ledgers.

7. **Official Runtime Envelope.**
   - Conforms strictly to the official public check specification (20 Nov 2026): **60-second execution timeout** and **100-step budget** per episode in an isolated offline environment (`--network none`). Hardware resources (CPU / RAM) depend on the evaluating platform; the environment imposes no hardcoded resource requirements.
