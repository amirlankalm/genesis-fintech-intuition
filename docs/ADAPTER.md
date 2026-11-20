# Jury adapter reference

`judge_adapter.py` at the repository root is the single entry point the official check definitions
(«Единый способ подключения») call. It is a thin translation layer over this repository's environment. It
does not contain a second generator, loader, or scorer. Adapter version `genesis-judge-adapter/1.0.0`,
environment `genesis-audit-env/0.2.0` (`judge_adapter.ADAPTER_VERSION`, `judge_adapter.ENV_VERSION`).

## 1. Where it is and how to run it

| | Host (repo root) | Container |
|---|---|---|
| Working directory | the repository root | `/app` (`WORKDIR`) |
| Import | `uv run python -c "import judge_adapter"` | `python -c "import judge_adapter"` (any cwd: `PYTHONPATH=/app:/app/src`) |
| Baselines through the adapter | `make judge` | part of the image `CMD` |
| Adapter conformance tests | `uv run pytest tests/test_judge_adapter.py tests/test_judge_schemas.py` | part of the image `CMD` |
| Everything, one command | `make docker-check` (`docker build -t genesis-audit-env . && docker run --rm --network none --cpus 2 --memory 4g genesis-audit-env`) | |

`judge_adapter.py` puts the repository's `src/` on `sys.path` itself, so it imports the right package
whether or not the package is installed. Only Python 3.11+ and the standard library are needed at run time.
In the container the evaluator runs as root, and everything under `/app` except `/app/policies` is readable by
root only.

`make judge` runs `tools/judge_run.py`. That script exports the shipped train and dev episodes to flat
directories under `out/judge/episodes/`. It then plays five policies through `make_env()` in closed mode and
scores each run with `score_episode`. It writes `out/judge/summary.json` and `out/judge/trajectories.jsonl`.
`uv run python tools/judge_run.py --help` lists the options: `--episode-dir` (repeatable), `--splits`,
`--mode`, `--policies`, `--summary`, `--trajectories` and `--export-root`.

## 2. The three functions

```python
import judge_adapter

judge_adapter.generate_episode(seed: int, config: dict, output_dir: str) -> None
env = judge_adapter.make_env()
env.reset(seed, config)  -> (observation: dict, info: dict)
env.step(action)         -> (observation: dict, reward: float, terminated: bool, truncated: bool, info: dict)
judge_adapter.score_episode(episode_dir: str, findings: dict, inspection_steps: int) -> dict
```

Positional and keyword calls both work, with exactly these parameter names. `reward` is always a Python
`float` and the two flags are always Python `bool`. Every value the functions take or return is JSON data.
A jury-side usage error (a bad seed, an unknown mode, a missing directory, a refused generator config)
raises `judge_adapter.AdapterError`, a `ValueError`. A policy never sees these errors.

### generate_episode(seed, config, output_dir)

This wraps the team generator: `genesis_audit.shipped.parse_config` followed by `shipped.generate`.

- `seed` must be a non-negative integer.
- `config` is the generator config (section 3).
- It writes the 8 files of section 4 flat into `output_dir` and creates the directory if it is missing. It
  overwrites those 8 files and leaves any other file alone. A refused request writes nothing.
- The same (seed, config, adapter version, `GENESIS_AUDIT_SECRET_FILE`) gives byte-identical files.
- Ids, the episode_id and the issue_ids are keyed by the evaluator secret. Without
  `GENESIS_AUDIT_SECRET_FILE` (a file of at least 16 bytes) that is the public dev key, so anyone with the
  repository can regenerate the episode. Set it for hidden seeds.

### make_env().reset(seed, config)

`config = {"mode": "closed" | "train", "episode_dir": str, "team_config": {...}}`

| mode | episode_dir | behaviour |
|---|---|---|
| `closed` | required | Loads exactly that directory. It never generates and never renames. `seed` is accepted and ignored, whatever its value. `team_config` is ignored and only logged. info `{}`. |
| `train` | given | Loads that directory, as in closed mode. info `{"env_version", "mode": "train"}`. |
| `train` | absent | Generates in memory from (`seed`, `team_config`). `team_config` is the generator config of section 3, and the seed must be a non-negative integer. This is the same episode `generate_episode(seed, team_config, dir)` writes. |

- A missing `mode` means `closed`. Any other mode value is refused.
- Unknown config keys are ignored and logged as a warning.
- A repeated reset starts the episode again from scratch, with no state carried over.
- A refused reset leaves no live episode.

### step(action)

`action = {"name": <action>, "args": {...}}` (schema: `docs/schemas/action.schema.json`).

The adapter swaps the key `name` with the core's key `action` and passes everything else through
unchanged. An official `{"name", "args"}` object therefore becomes the core's `{"action", "args"}`. Any
other shape stays exactly as broken as it was:

- `{"action": ..., "args": ...}` without `name` is an invalid action. It costs one step and is never a
  submit.
- An object whose `name` is `"submit"` is a submit attempt, however broken. A broken one ends the episode
  as an invalid submission (`return` -1).

### score_episode(episode_dir, findings, inspection_steps)

- `findings` is the findings.json object `{"episode_id"?: str, "findings": [...]}`, the same object passed
  as `args.findings` of submit. A bare list is not a findings.json object, so it is an invalid structure.
- `inspection_steps` must be a non-negative integer.
- The episode is loaded the same way reset loads it, and scored by the same code and with the same
  evidence universe and tolerance as the environment's own end-of-episode scoring
  (`genesis_audit.scoring.score_submission`). The tests check that the two give equal results.
- The result is exact. It is computed in fractions and converted to `float` only at the end.

## 3. Generator config (generate_episode `config`, train-mode `team_config`)

Both take one schema with one parser (`shipped.parse_config`). The machine-readable form is
`docs/schemas/generator_config.schema.json`.

```json
{"generator": {<company keys>}, "inject": {<error keys>}}
```

- Both sections are optional, `null` means `{}`, and `{}` is a clean default company.
- An unknown key at any level is refused with a message that names it.

`generator`:

| key | values | default |
|---|---|---|
| base_currency | KZT, USD, EUR, GBP, JPY, KWD (exponents 2, 2, 2, 2, 0, 3) | KZT |
| foreign_currencies | list of 1 to 5 codes from the same list, none equal to base | ["USD"] |
| timezone | Asia/Almaty (+05:00), Asia/Tokyo (+09:00), Asia/Dubai (+04:00), Asia/Kolkata (+05:30), America/Bogota (-05:00), Africa/Lagos (+01:00), UTC | Asia/Almaty |
| period | "YYYY-MM" or "YYYY-Qn", years 2000..2100 | "2026-10" |
| invoices | 12..110 | 40 |
| ledger_rows | 200..2000 (a target; the result lands within about 15 rows of it, and up to about 30 rows inside the range near 200 and 2,000) | 400 |
| head_days / tail_days | 3..12 days of records before / after the period | 6 / 7 |

Asia/Almaty is refused when the period start minus head_days falls before 2024-03-01, because the zone was
UTC+06:00 before that date.

`inject`:

- Every key is optional.
- Counts are non-negative integers; a bool is refused.
- Each family and each sub-kind can be switched on alone.
- The request may contain at most 12 issues in total, counting 2 per interaction.

| key | truth type | what is injected |
|---|---|---|
| duplicate_invoice | duplicate_invoice | one obligation recorded as a second invoice record |
| payment_allocation | payment_allocation | a receipt under-applied; missing or partial is drawn from the seed |
| payment_allocation_missing | payment_allocation | a receipt that names an open invoice with no allocation row at all |
| payment_allocation_partial | payment_allocation | a receipt applied for more than 0 and less than the policy requires |
| fx_mismatch | fx_mismatch | a foreign receipt translated at a rate the policy does not select; date or rate is drawn |
| fx_mismatch_date | fx_mismatch | translated at the fx.csv rate of another date |
| fx_mismatch_rate | fx_mismatch | translated at a rate on no fx.csv row |
| cutoff | cutoff | an invoice's revenue row on the other side of a period boundary from issued_at |
| interactions | two issues each | a list of scenarios; each entry is a name, or an object `{"name": ..., <parameters>}` |

The two documented interaction scenarios:

- **Interaction 1, `cutoff_and_allocation`.** An invoice's revenue row is on the wrong side of a boundary,
  and its receipt is also under-applied. This gives two issues: a `cutoff` on the invoice, and a
  `payment_allocation` on the invoice and the receipt.
  - Parameters: `boundary` start|end, `allocation` missing|partial, `receipt_currency` same|foreign.
  - The case's own example is `{"name": "cutoff_and_allocation", "allocation": "partial", "receipt_currency": "foreign"}`.
- **Interaction 2, `duplicate_then_cutoff`.** A duplicate invoice record whose revenue row is also on the
  wrong side of a boundary. This gives two issues: a `duplicate_invoice` on both records, and a `cutoff` on
  the copy.
  - Parameters: `boundary` start|end, `copy_offset` same|other.

`fx_then_allocation` is an extra third scenario. Its parameters are `fx_error` date|rate and `allocation`
missing|partial.

A parameter left out is drawn from the seed, with one exception: `fx_then_allocation` without `allocation`
is always partial. Amounts, currencies, ids and dates always come from the seed and the company.

The generator adds no decoys knob, because every company already holds the look-alikes: split payments,
refunds, legitimately repeated amounts, and FX and period-boundary look-alikes.

A request the company cannot hold is refused with a message saying why. Example: "no settled invoice near a
period boundary is left ...; another seed or company, or tail_days 10 to 12 for the end boundary, leaves
more". Near the 2,000-row ceiling, injected rows can also push the company outside the size envelope.

Recipes for the official closed episodes D01-D20 (the `config` passed to `generate_episode`; company settings
such as currencies, zone, period and size go under `generator` and may be anything in the table above). These
are the requests `tests/test_generator_scenarios.py` (`SCENARIOS`) builds for three seeds and three companies
each.

| check | config | truth |
|---|---|---|
| D01-D05 | `{"inject": {}}` (every company already holds split payments, refunds, repeated amounts and FX and period look-alikes) | none |
| D06-D08 | `{"inject": {"duplicate_invoice": 1}}` | 1 `duplicate_invoice` |
| D09, D11 | `{"inject": {"payment_allocation_missing": 1}}` | 1 `payment_allocation` |
| D10 | `{"inject": {"payment_allocation_partial": 1}}` | 1 `payment_allocation` |
| D12 | `{"inject": {"fx_mismatch_date": 1}}` | 1 `fx_mismatch` |
| D13 | `{"inject": {"fx_mismatch_rate": 1}}` | 1 `fx_mismatch` |
| D14-D15 | `{"inject": {"cutoff": 1}}` | 1 `cutoff` |
| D16 | `{"inject": {"interactions": [{"name": "cutoff_and_allocation", "allocation": "partial", "receipt_currency": "foreign"}]}}` | `cutoff` + `payment_allocation` |
| D17 | `{"inject": {"interactions": [{"name": "cutoff_and_allocation", "boundary": "start", "allocation": "missing", "receipt_currency": "same"}]}}` | `cutoff` + `payment_allocation` |
| D18 | `{"generator": {"tail_days": 12}, "inject": {"interactions": [{"name": "cutoff_and_allocation", "boundary": "end", "allocation": "partial"}]}}` | `cutoff` + `payment_allocation` |
| D19 | `{"inject": {"interactions": [{"name": "duplicate_then_cutoff", "boundary": "end", "copy_offset": "other"}]}}` | `duplicate_invoice` + `cutoff` |
| D20 | `{"inject": {"interactions": [{"name": "duplicate_then_cutoff", "boundary": "start", "copy_offset": "same"}]}}` | `duplicate_invoice` + `cutoff` |

## 4. The episode directory

The directory is flat and its name is free. Reset and score_episode read these 8 files. Any other file is
ignored and its name is logged.

| file | content |
|---|---|
| manifest.json | schema_version, episode_id, base_currency, period_start/end, timezone, counts, currencies (exponent), rounding, amount_tolerance_minor (tau per currency), issue_types, limits |
| policy.json | the published policy: account names, date, rate and rounding rules, cutoff and allocation rules, finding conventions |
| ledger.csv | row_id, timestamp, account, debit_minor, credit_minor, currency, entity_id, invoice_id, payment_id |
| invoices.jsonl | doc_id, invoice_id, entity_id, issued_at, due_at, currency, total_minor, line_items[] |
| payments.jsonl | doc_id, payment_id, timestamp, currency, amount_minor, invoice_refs[] |
| fx.csv | date, source_currency, target_currency, rate (decimal string, target units per one source unit) |
| truth.json | closed: `{"issues": [{issue_id, type, affected_ids, expected_amount_minor, currency, acceptable_evidence_sets}]}` |
| provenance.json | closed, optional for loading: generator settings, and per injection the error, the expected effect and the before/after changes |

What the loader tolerates and enforces:

- Tolerated: any key order, whitespace, a BOM, CRLF line ends, any CSV column order or quoting, a trailing
  empty line, and any row order. The row order of a file is the order in which list_records pages it.
- Ids: any non-empty string of at most 256 code points without control characters, compared exactly.
  Uniqueness holds within each id space only. Equal strings in different spaces are fine.
- Closed and jury-loaded episodes load non-strictly. Formats are enforced. Consistency checks become
  evaluator-log warnings: the published policy version, the size envelope, tau = 0, and truth against our
  rules. This lets a hand-built fixture (5 records, tau = 1, hand-written truth) load and score.

Tables and their ids (these are the canonical table names):

| table | `get_record(table, id)` takes | `list_records` | evidence id |
|---|---|---|---|
| ledger | row_id | rows | row_id |
| invoices | invoice_id | invoice documents | doc_id (`get_document`) |
| payments | payment_id | payment documents | doc_id (`get_document`) |
| fx | `date\|source_currency\|target_currency`, e.g. `2026-09-23\|KZT\|USD` | rate rows | the same key |

`get_document(doc_id)` returns the invoice or payment document with that doc_id.

Every field that carries an id must be renamed together when ids are swapped:

| id space | defined in | referenced from |
|---|---|---|
| row_id | ledger.row_id | truth.acceptable_evidence_sets; provenance changes (`id`, `record.row_id`) |
| doc_id | invoices.doc_id, payments.doc_id | truth.acceptable_evidence_sets |
| invoice_id | invoices.invoice_id | ledger.invoice_id, payments.invoice_refs[], truth.affected_ids; provenance (`error.invoice_id`, `expected.affected_ids`, change records) |
| payment_id | payments.payment_id | ledger.payment_id, truth.affected_ids; provenance (`error.payment_id`, `expected.affected_ids`, change records) |
| entity_id | invoices.entity_id | ledger.entity_id; provenance change records |
| episode_id | manifest.episode_id | findings.episode_id (optional) |
| issue_id | truth.issue_id | nothing public |

FX keys are not ids. They are the natural key `date|source_currency|target_currency` of an fx.csv row, so
they must not be renamed. Truth evidence sets cite them as written. provenance.json is never read for
scoring, so a copy that leaves it stale still scores the same.

## 5. Error types

The canonical rules are published in `policy.json` (`finding_conventions`) and implemented in
`genesis_audit/families.py`. Tau is `manifest.amount_tolerance_minor[currency]`, which is 0 in every episode
we generate. A truth currency the manifest does not list also gets tau 0.

| case error type | our `type` | canonical `affected_ids` (a set) | `claimed_amount_minor` | currency | minimal evidence set | tau | inject key |
|---|---|---|---|---|---|---|---|
| дубли счетов | `duplicate_invoice` | invoice_id of every record in the group | invoice total × (records − 1) | invoice currency | doc_id of every invoice in the group | 0 | duplicate_invoice |
| пропущенное или частичное распределение платежа | `payment_allocation` | {invoice_id, payment_id} | required allocation − recorded allocation | invoice currency | invoice doc_id, payment doc_id, row_id of every accounts_receivable row carrying both ids (none for a missing allocation); for a receipt in another currency than the invoice, also the row_id of the receipt's fx_clearing debit (what it brings, as recorded) | 0 | payment_allocation, payment_allocation_missing, payment_allocation_partial |
| неверная дата или курс конвертации | `fx_mismatch` | {payment_id} | abs(recorded − required translation) | invoice currency | payment doc_id, the fx key the policy selects, row_id of the receipt's fx_clearing debit | 0 | fx_mismatch, fx_mismatch_date, fx_mismatch_rate |
| ошибка отнесения к отчётному периоду | `cutoff` | {invoice_id} | invoice total | invoice currency | invoice doc_id, row_id of its revenue row | 0 | cutoff |

When one record breaks two rules (the interactions), the result is two issues, one per rule (policy
`overlap`). Allocation is measured against the translated amount that was recorded, so a wrong translation
is only an `fx_mismatch`.

## 6. Results and observations (with real examples)

Schemas: `docs/schemas/observation.schema.json`, `action.schema.json`, `findings.schema.json`,
`truth.schema.json`. `tests/test_judge_schemas.py` checks every action, observation, submitted findings
document and truth file of real runs against them.

The first observation is returned by reset. The examples below are a closed-mode run on the shipped episode
`train_02` (exported flat as `tools/judge_run.py` does); the task and policy are shortened.

```json
{"task": "You are auditing one synthetic company for one reporting period. ... Each step is one JSON action {\"name\": name, \"args\": {...}} ...",
 "manifest": {"schema_version": "genesis-fintech-draft-2026-11-12/case-1", "episode_id": "ep-d47cc25766",
   "base_currency": "KZT", "period_start": "2026-10-01T00:00:00+05:00", "period_end": "2026-10-31T23:59:59+05:00",
   "timezone": "Asia/Almaty", "counts": {"ledger_rows": 209, "documents": 37, "fx_rates": 49},
   "currencies": {"KZT": {"exponent": 2}, "USD": {"exponent": 2}},
   "rounding": {"permitted": ["half_up"], "default": "half_up"}, "amount_tolerance_minor": {"KZT": 0, "USD": 0},
   "issue_types": ["duplicate_invoice", "payment_allocation", "fx_mismatch", "cutoff"],
   "limits": {"max_steps": 100, "page_limit": 50, "max_findings": 30, "max_evidence_ids": 10, "max_explanation_chars": 1000}},
 "policy": {"policy_version": "case-draft-2", "...": "..."},
 "remaining_steps": 100}
```

Every later observation has the form `{"result": value | null, "error": null | {"code", "message"}, "remaining_steps": int}`:

```json
{"name": "list_records", "args": {"table": "ledger", "cursor": null, "limit": 2}}
{"result": {"records": [{"row_id": "L49UYQC", "timestamp": "2026-09-24T18:41:00+05:00", "account": "accounts_receivable", "debit_minor": 38000000, "credit_minor": 0, "currency": "KZT", "entity_id": "ENVFHQ6", "invoice_id": "IAZ24ET", "payment_id": null}, {"row_id": "LKR5Z6X", "...": "..."}], "next_cursor": "ledger:2"}, "error": null, "remaining_steps": 99}

{"name": "get_record", "args": {"table": "ledger", "id": "L49UYQC"}}
{"result": {"row_id": "L49UYQC", "timestamp": "2026-09-24T18:41:00+05:00", "account": "accounts_receivable", "debit_minor": 38000000, "credit_minor": 0, "currency": "KZT", "entity_id": "ENVFHQ6", "invoice_id": "IAZ24ET", "payment_id": null}, "error": null, "remaining_steps": 98}

{"name": "get_document", "args": {"doc_id": "D8VTCHG"}}
{"result": {"doc_id": "D8VTCHG", "invoice_id": "IAZ24ET", "entity_id": "ENVFHQ6", "issued_at": "2026-09-26T08:00:00+05:00", "due_at": "2026-10-26T08:00:00+05:00", "currency": "KZT", "total_minor": 38000000, "line_items": [{"description": "Consulting hour", "quantity": 5, "unit_price_minor": 7600000, "amount_minor": 38000000}]}, "error": null, "remaining_steps": 97}

{"name": "get_record", "args": {"table": "fx", "id": "2026-09-23|KZT|USD"}}
{"result": {"date": "2026-09-23", "source_currency": "KZT", "target_currency": "USD", "rate": "0.0019920"}, "error": null, "remaining_steps": 96}

{"name": "calculator", "args": {"expression": "0.1+0.2"}}
{"result": "0.3", "error": null, "remaining_steps": 95}

{"name": "get_record", "args": {"table": "ledger", "id": "U"}}
{"result": null, "error": {"code": "unknown_id", "message": "no record with that id"}, "remaining_steps": 94}

{"name": "submit", "args": {"findings": {"episode_id": "ep-d47cc25766", "findings": [{"type": "payment_allocation", "affected_ids": ["IAZ24ET", "P4QABRF"], "claimed_amount_minor": 11000000, "currency": "KZT", "evidence_ids": ["D8VTCHG", "DBKSNM8"], "explanation": "..."}, {"type": "payment_allocation", "affected_ids": ["IGKSBRF", "PNSX7H7"], "claimed_amount_minor": 29200, "currency": "USD", "evidence_ids": ["DJVSPF7", "DZXN99G", "LHDZEPP"], "explanation": "..."}]}}}
{"result": {"accepted": true}, "error": null, "remaining_steps": 93}

{"name": "list_records", "args": {"table": "ledger", "cursor": null}}
{"result": null, "error": {"code": "episode_over", "message": "the episode has ended; no further actions are accepted"}, "remaining_steps": 93}
```

`list_records`:

- `cursor` is `null` for the first page.
- `limit` is optional and runs from 1 to 50 (default 50).
- `next_cursor` is `null` on the last page.
- Cursors are stable within a loaded episode, and the same cursor returns the same page.

`calculator` returns an exact decimal string, such as `"0.3"` or `"0.333333333333333333"`.

`submit`:

- It returns `{"accepted": true}` for any valid structure, right or wrong, and says nothing about
  correctness.
- An invalid structure returns `{"result": null, "error": {"code": "invalid_submission", ...}}`. Both end
  the episode with `terminated=true`.

Public error codes are the only errors a policy can receive. Messages are fixed strings: they never echo
input and never contain paths, seeds or truth.

| code | message |
|---|---|
| invalid_action | action must be an object with exactly the keys 'name' and 'args' |
| unknown_action | action name is not one of the allowed actions |
| bad_arguments | arguments do not match the action's schema |
| unknown_table | table is not one of: ledger, invoices, payments, fx |
| unknown_id | no record with that id |
| bad_cursor | cursor is not valid for this table |
| bad_limit | limit must be an integer between 1 and the page limit |
| action_too_large | action exceeds the maximum encoded size |
| calc_syntax | expression is not valid decimal arithmetic |
| calc_too_long | expression is longer than the allowed length |
| calc_too_deep | expression is nested more deeply than allowed |
| calc_div_zero | division by zero |
| calc_overflow | value is outside the allowed range |
| invalid_submission | submit did not carry a valid findings.json structure; the episode has ended |
| episode_over | the episode has ended; no further actions are accepted |
| internal_error | the environment could not process this action |

Before the end, every error costs one step and only `invalid_submission` ends the episode. `episode_over` answers
any step after the end and changes nothing. The size bound behind `action_too_large` is 262,144 bytes of UTF-8 JSON;
a submit that large is an `invalid_submission` instead.

`score_episode` results:

```json
{"tp": 2, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0, "return": 0.982}
{"tp": 2, "fp": 2, "fn": 0, "precision": 0.5, "recall": 1.0, "f1": 0.6666666666666666, "return": 0.31533333333333335}
{"tp": null, "fp": null, "fn": null, "precision": null, "recall": null, "f1": null, "return": -1.0}
```

These are, on the same episode, the oracle's two findings, the same two findings twice, and an invalid structure (`claimed_amount_minor: true` in the first finding), each with `inspection_steps=9`. For an invalid structure, the reason goes to the evaluator log as `WARNING judge_adapter: invalid submission (return -1) on ep-...: findings[0].claimed_amount_minor: must be a JSON integer, not a bool, string or fraction`.

Metrics:

- P = TP/(TP+FP), with 0 when TP+FP = 0. R = TP/(TP+FN), with 0 when TP+FN = 0.
- F1 = 2TP/(2TP+FP+FN), with 1 when both truth and findings are empty.
- `return` = clip(2·F1 − 1 − 0.002·inspection_steps, −1, 1).

## 7. Oracle recipe (jury side)

`judge_adapter.oracle_findings(episode_dir)` returns the findings.json object for the episode in
`episode_dir`. Pass it as `{"name": "submit", "args": {"findings": <it>}}` and to `score_episode`.

To build it yourself from truth.json, for each issue write one finding:

| finding field | value from truth.json |
|---|---|
| type | type |
| affected_ids | affected_ids |
| claimed_amount_minor | expected_amount_minor |
| currency | currency |
| evidence_ids | any one of acceptable_evidence_sets (we take the smallest) |
| explanation | any string of at most 1000 characters |

The document is `{"episode_id": manifest.episode_id, "findings": [...]}`. `episode_id` may be omitted. On a
renamed copy, read that copy's truth.json, which already holds the new ids. `baselines/oracle.py` does
exactly this, and the oracle must never be given to a policy.

## 8. Closed vs train

| | closed | train |
|---|---|---|
| reward on every step, terminal included | `0.0` | `0.0`, and the terminal step returns the true return |
| info | `{}` everywhere, reset included | reset `{"env_version", "mode": "train"}`, steps `{}` |
| episode source | episode_dir only | episode_dir, or generated from (seed, team_config) |

In closed mode a perfect, a wrong, an empty and a malformed submit all look the same to the policy, except
that a malformed one carries `error.code = invalid_submission`. That is the bounded structural error the
official text allows. The true score stays with the jury, in `score_episode` and
`JudgeEnv.evaluator_report()`.

Evaluator log: the Python logger `judge_adapter`. Configure logging (for example
`logging.basicConfig(level=logging.INFO)`) to keep it. It records the following:

- every reset as JSON: adapter_version, env_version, seed, config, episode_id;
- every episode that ends on a submit or on the time limit: the cause and the inspection steps (an episode
  truncated by its 100th inspection is not logged here; its cause is in `evaluator_report()`);
- every invalid submission, with its reason;
- the number of loader warnings. The warnings themselves go to the logger `genesis_audit.loader`.

`JudgeEnv.evaluator_report()` is jury-only and available after the episode ends. It returns the core
report together with `"judge": {adapter_version, env_version, seed, config, episode_id}`. The core report
holds the termination cause, steps_used, inspection_steps, the score, the counts, the per-finding verdicts
with reasons, the unmatched issue ids and the trajectory digest.

## 9. Budgets

- **100 steps.** Every step call counts, including errors and the submit. A submit on step 100 is accepted.
  An inspection on step 100 ends the episode with `truncated=true` and empty findings.
- **inspection_steps.** This counts every step call before the submit, including errors, and excludes the
  submit itself. After 100 inspections it is 100. Pass this number to `score_episode`.
- **60 s per episode.** The clock is `time.monotonic` and the window opens at the top of `reset`, before the
  episode is loaded or generated. Policy time is included. The first step after the window has closed is not
  executed, even a submit. It returns `{"result": null, "error": null, ...}` with `truncated=true`, and the
  findings are empty. Count `{"findings": []}` as the result. The check happens when `step` is called, so a
  policy that hangs must be stopped by the jury's harness.

## 10. Matcher conventions

Each convention below gives its rule and where it lives in the code.

**Ids** are compared as exact strings, with no case folding, trimming, prefix stripping or similarity. Code:
`genesis_audit/matching.py` `edge_reasons`.

**affected_ids** is a set: order and repeats do not matter. A TP needs exact set equality with the issue's
canonical set (section 5), so a superset or a subset is FP + FN. Code: `schemas._id_list`,
`matching.edge_reasons`.

**evidence_ids** is a set, but the cap of 10 is checked on the list as sent, so repeats count toward it. A
TP needs one acceptable set fully included, and extra ids are allowed if they exist and are accessible
(rule 3, M03). Every cited id must be one a tool returns a record or document for in this episode: a ledger
row_id, a document doc_id, an invoice_id or payment_id (`get_record` takes them) or an fx key. Any other id
makes the finding unmatched (FP); that includes an invented id, an entity_id and an issue_id. The
environment, `score_episode` and truth validation use this one universe. Code: `matching.evidence_problem`,
`PublicEpisode.accessible_ids`.

**type, currency and amount.**

- The type must equal one of `manifest.issue_types` exactly. An unknown string is unmatched, not an error.
- The currency must match exactly; `kzt` and `KZT ` are FP.
- The amount must be a JSON integer, not a bool, string or float. It matches when
  abs(claimed − expected) ≤ tau, where tau is the manifest's value per currency (0 here).
- The explanation is never used. Code: `matching.edge_reasons`.

**Structure versus mismatch.** Only these make the whole submit invalid (return −1):

- a wrong JSON type;
- a missing required key;
- more than 30 findings;
- more than 10 evidence ids as sent;
- an explanation longer than 1000 code points;
- an `episode_id` that is present but differs from the episode's.

Everything else is scored, and a well-formed wrong finding is a FP. Extra keys are ignored. Code:
`genesis_audit/schemas.py` `parse_findings_document`.

**Matching.** The verifier takes a maximum-cardinality bipartite matching. Ties are broken the official
way: issue_ids are sorted by code point, and the verifier picks the lexicographically smallest sorted
sequence of (issue_id, finding index) pairs. Repeats of a finding stay separate FPs. Code:
`matching.match`, `matching.choose_pairs`. The chosen pairs appear in the evaluator report.

## 11. Baselines through the adapter

| baseline policy | module | decision code |
|---|---|---|
| random exploration, fixed seed | `baselines/random_explorer.py` (seed 7) | port of `policies/random_inspector.py` |
| simple reconciliation | `baselines/simple_reconciliation.py` | `policies/reconciliation_naive.py` |
| mass flagging | `baselines/flag_all.py` | `policies/flag_all.py` |
| oracle (jury side) | `baselines/oracle.py` | `judge_adapter.oracle_findings` |
| extra: rule-following solver | `baselines/reconciliation.py` | `policies/reconciliation.py` |

Each baseline exposes `run(env, first_observation, ...)` and plays only through `env.step({"name", "args"})`.
`baselines/_session.py` runs the unchanged decision code of `policies/*.py` over the adapter in place of
the sandboxed JSON-lines bridge.

`out/judge/trajectories.jsonl` has one JSON object per line with these fields:

- `run_id`, `policy`, `split`, `mode`, `episode_id`, `step`, and `policy_seed` for the random explorer;
- `action`: `null` for the reset line (step 0), otherwise the `{"name", "args"}` that was sent;
- `observation`: exactly what the policy saw;
- `reward`: as the policy saw it (0.0 throughout in closed mode);
- `terminated` and `truncated`.

`out/judge/summary.json` holds every run (tp, fp, fn, precision, recall, f1, return, inspection_steps,
wall_time_s, termination_cause) and the per-policy means. It also cross-checks every run: score_episode
must agree with the environment's own report on the counts and the return, and the jury-style
inspection_steps count must agree with the environment's. The run lists any run where they disagree.

## 12. Versions

- Adapter `genesis-judge-adapter/1.0.0`. Environment `genesis-audit-env/0.2.0`.
- Case schema `genesis-fintech-draft-2026-11-12/case-1`, policy `case-draft-2` (case-draft-1 plus the allocation
  evidence of a cross-currency receipt and the wider evidence universe; case-draft-1 is no longer published:
  strict loading refuses it, the jury path only logs a warning).
- Python 3.11. No run-time dependencies; `uv.lock` pins the dev tools.
- The image is `python:3.11-slim` with pytest 9.2.0 and pytest-cov 7.1.0.
