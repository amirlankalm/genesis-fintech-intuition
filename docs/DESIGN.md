# Design note

**English** · [Русский](DESIGN.ru.md)

Team Intuition, Genesis Hackathon 2026, FinTech case. A short account of how the environment is built and why. Exact rules are in [`SPEC.md`](SPEC.md); the jury interface is in [`ADAPTER.md`](ADAPTER.md).

## 1. What the environment is for

An agent that audits books must look at records, pick what to inspect next, and make claims it can back with evidence. The environment gives it that loop: a company's books for one period with real errors hidden in them, five narrow tools, a budget of 100 steps, and a score for its findings. The score depends only on structured fields and evidence, never on how persuasive the explanation is. The environment does not train anything; it supplies interactions, trajectories and a reward for whoever does.

## 2. The world: history first, errors second

```
seed + config
   │
   ▼
latent history      customers, currencies, period, timezone; invoices issued, receipts, refunds,
   │                rates for every day; who pays what and when
   ▼
clean books         ledger rows posted from the history by one bookkeeping model:
   │                every receipt allocated as the policy requires, every translation at the right rate
   ▼
clerk's errors      applied one at a time; each change recorded with before and after values
   │                (provenance.json); the books are validated after every step
   ▼
public records      manifest, ledger.csv, invoices.jsonl, payments.jsonl, fx.csv, policy.json
   │
   ▼
truth               what the published rules find in the final public records (truth.json)
```

Three properties follow from this order and each one has a test:

- **The books are consistent before the errors.** Undoing the provenance gives the clean books, in which the published rules find nothing.
- **Truth describes a real discrepancy.** It is computed from the records, not copied from the injection label, and the expected effect of each injection is cross-checked against what the rules find.
- **Every issue is decidable from public evidence.** Each truth entry carries the evidence sets that prove it; every id in them is reachable through the tools within the budget, and the amount can be recomputed from the set alone.

Randomness comes from one keyed stream (HMAC-SHA256 over the seed and a label per draw), so the same seed, config and version give byte-identical files on any machine and Python version, and ids cannot be inverted to the seed without the evaluator's key.

## 3. The four error types as published rules

The case names the error families and leaves their exact meaning open. We fixed each one as a rule the agent can read in `policy.json` and apply to the records:

| Type | The books are wrong when |
|---|---|
| `duplicate_invoice` | two or more invoice records are the same obligation: same customer, currency, issue and due instants, and lines |
| `payment_allocation` | a receipt referencing an open invoice is applied for less than "up to the open balance" requires (missing: nothing applied; partial: some) |
| `fx_mismatch` | a receipt in another currency was translated at a rate other than the fx.csv rate of its local calendar date (wrong date or wrong rate) |
| `cutoff` | an invoice's revenue row is on the other side of the reporting period than its `issued_at` |

**Interactions.** When one record breaks two rules, each rule gives its own issue, and an overlap rule says what is measured against what (an allocation is measured against the translation that was recorded, so a wrong rate is counted once, as `fx_mismatch`). Two scenarios are documented: `cutoff_and_allocation` (with a foreign partial receipt it is the case's example) and `duplicate_then_cutoff`.

**Decoys.** Difficulty comes from valid look-alikes, not from noise: split and double payments, overpayments with refunds, weekly invoices with identical lines, receipts written at another offset, rates quoted the other way round, postings a few days late or early inside the period. A copy and a valid sibling are drawn by the same process, so nothing but the published rule tells them apart; fourteen single-feature shortcuts are measured and each stays below F1 0.5.

## 4. The contract

- `reset(seed, config)` returns `(observation, info)`; the first observation holds the task, the manifest, the policy and the remaining budget.
- `step(action)` returns `(observation, reward, terminated, truncated, info)`, every value JSON.
- Actions: `list_records(table, cursor, limit)` with at most 50 rows per page and stable cursors; `get_record(table, id)`; `get_document(doc_id)`; `calculator(expression)`, a parser for decimal arithmetic that never executes code; `submit(findings)`.
- Every step costs one, errors included; a submit on step 100 is accepted; 100 inspections or 60 seconds end the episode truncated with empty findings.
- In closed (evaluation) mode the policy sees reward 0 at every step and an empty info; the score stays with the evaluator.

The official interface the jury calls (`generate_episode`, `make_env`, `score_episode`) is a thin translation layer, `judge_adapter.py`, over the same code.

## 5. Scoring

A finding is a true positive only if all of these hold: the right type, the same set of affected ids as the truth issue, an amount within the published tolerance (0), the same currency, and one complete acceptable evidence set among its evidence ids, with every cited id existing and accessible. There is no partial credit. Findings and issues are matched one-to-one by maximum matching, so the order of findings cannot change a score and a repeated finding is a false positive; ties between maximum matchings are broken by the rule in the official definitions. Then F1 = 2TP/(2TP+FP+FN) (both empty gives 1) and reward = clip(2·F1 − 1 − 0.002·inspection_steps, −1, 1). A submission is malformed, and scores −1, only for a wrong JSON type, a missing field, an exceeded limit or an `episode_id` that differs from the episode's; a wrong value is just an unmatched finding.

## 6. Isolation

The policy gets JSON observations over a pipe, never a path. In our own runs it runs in a separate process under an operating-system boundary (a sandbox profile on macOS, separate user ids in the container), and a hostile probe that tries to read truth, write, use the network or signal the evaluator must fail on every attempt the boundary is meant to stop for the self-check to pass (in the container, the network is closed by `--network none`). The limits of that boundary are listed in the spec.

## 7. How we checked it

- Every official check by its id (C01-C20, D01-D20, matcher tests 1-20 and M01-M12, P01-P20), plus a blind re-implementation of them in `tests/jury/` written from the published text alone.
- An independent checker that shares no code with the generator re-derives truth from public records for every shipped episode.
- Independent reviewers attacked the environment several times; each found real defects (shortcuts that gave away duplicates, a contract that could be weakened by editing a policy file, replay crashes), and each fix has a regression test. The log is in [`NOTES.md`](../NOTES.md); one failed trajectory is traced to its cause in [`review/H_failed_trajectory.md`](review/H_failed_trajectory.md).

## 8. Limits and Honest Scope

- **Rule-Following Solver vs. Learned Models:** A rule-following script solves the 20 shipped case episodes ($F_1 = 1.000$, return $0.961$ in `make judge`) and reaches $F_1 = 1.0$ across 138 verification runs on the 31 shipped episodes. This finite empirical evaluation bounds what the episodes measure: rigorous reading of rules and records, not open-ended audit judgment. It is an evaluation on finite shipped data, not a proof for all arbitrary cases. No machine learning model was trained, and no learning claim is made.
- **Process Isolation Boundary:** Confinement (setuid unprivileged execution under Docker, Seatbelt sandboxing on macOS) strictly prevents policies from reading `truth.json`, `provenance.json`, private seeds, evaluator memory, network interfaces, or unauthorized host paths. It relies on standard OS privilege separation and does not protect against host kernel vulnerabilities or unbounded memory allocation without external cgroups.
- **Calculated vs. Measured Numbers:** Step budgets (100 steps max, 52 steps maximum to read any company) and decimal minor unit representations are exact structural invariants. Clock runtimes (< 0.13 s slowest episode) and memory peaks (~43 MB evaluator, ~28 MB policy) in `docs/measurements/scale.json` are empirical measurements on the test machine.
- **Memorisation vs. Generalization:** A memoriser policy that replays saved answers achieves $F_1 = 0.000$ and return $-1.000$ on unseen twin episodes with renamed identifiers and shuffled rows (scoring identically to an abstaining policy, $-1.000$), proving the benchmark cannot be bypassed by table lookup.
- **Accounting Model & Generator Scope:** One bookkeeping model, receivables only, with standard double-entry charts of accounts. The family rules are our reading where the case left them open. The generator targets 200 to 2,000 ledger rows across 6 fiat currencies.
- **Accounting Identities vs. Truth:** Balanced books ($\text{Debits} = \text{Credits}$) do not imply absence of errors: cutoff, allocation, duplicate, and exchange rate misstatements persist within balanced ledgers.
- **Runtime Envelope:** Conforms strictly to the official public specification: 60-second execution timeout and 100-step budget per episode in an isolated offline environment (`--network none`). Hardware resources depend on the evaluating platform; the environment imposes no hardcoded CPU or RAM limits.
