# Genesis FinTech: an RL Environment for Financial-Audit AI Models

**English** · [Русский](README.ru.md) · [Қазақша](README.kk.md)

**Team Intuition · Genesis Hackathon 2026 (FinTech Case: "RL environments for post-training financial-audit models")**

We are **Team Intuition**. Here is our solution: a reproducible, Gym-compatible Reinforcement Learning (RL) practice world designed for post-training and evaluating AI financial auditors.

In financial auditing, autonomous agents cannot rely on ungrounded generation or speculative reasoning: every discrepancy must be backed by immutable documentary evidence, and false positives carry severe audit risk. We implemented an environment where a seeded generator constructs a company's complete financial records for a reporting period, introduces subtle accounting discrepancies alongside realistic decoys, exposes five narrow inspection tools, and scores findings against hidden ground truth using a strict one-to-one maximum bipartite matching algorithm and a step-penalized return function.

> [!NOTE]
> **Synthetic Data Invariant:** All entities, counterparties, banking records, and transactions are generated in-memory from deterministic PRNG seeds. No real-world company or payment data is used.

**Timeline:** Built and verified during the hackathon (19–20 November 2026). Conforms to the case specification and the official check definitions published on 20 November (`judge_adapter.py`, matcher conventions M01–M12, scenarios D01–D20).

---

## Quickstart

### Local Execution (Python 3.11+, uv)

```bash
uv sync --frozen   # install locked development dependencies
make check         # lint, mypy type checks, pytest with coverage, self-check
make judge         # evaluate baselines & solver via judge_adapter.py + conformance tests
```

### Containerized Execution (Offline Execution: 60s Wall-Clock Limit, No Network)

```bash
make docker-check
```

Or using standalone Docker without `make`:

```bash
docker build -t genesis-audit-env . && docker run --rm --network none genesis-audit-env
```

All operations run locally from the repository root (`/app` within the container). No network access is required after dependency installation, and no external APIs or GPU acceleration are utilized.

---

## Deliverables (Case Section 09)

| Required Deliverable | Repository Location |
|---|---|
| **Source & Pinned Dependencies** (generator & RL environment) | [`src/genesis_audit/`](src/genesis_audit/), [`LICENSE`](LICENSE) (MIT), [`uv.lock`](uv.lock) |
| **README & Dockerfile** (container instructions + single check command) | [`README.md`](README.md), [`Dockerfile`](Dockerfile), [`Makefile`](Makefile) |
| **Matcher, Reward, Schemas & Policies** | [`src/genesis_audit/matching.py`](src/genesis_audit/matching.py), [`scoring.py`](src/genesis_audit/scoring.py), [`schemas.py`](src/genesis_audit/schemas.py); [`docs/schemas/`](docs/schemas/) |
| **10 Train & 10 Dev Episodes** | [`episodes/`](episodes/), split index [`episodes/splits.json`](episodes/splits.json) |
| **Comprehensive Test Suite** | [`tests/`](tests/) (1,247 collected tests across 493 test definitions: 1,245 passed, 2 skipped) |
| **Benchmark Baselines + Rule-Following Solver** | [`baselines/`](baselines/): random explorer, simple reconciliation, flag-all, oracle, solver |
| **Trajectory File** (`trajectories.jsonl`) | [`trajectories.jsonl`](trajectories.jsonl) |
| **Design Documentation** | [`docs/DESIGN.md`](docs/DESIGN.md) ([Русский](docs/DESIGN.ru.md)), [`docs/SPEC.md`](docs/SPEC.md) |
| **Video Demonstration** | [`demo/`](demo/): recorded terminal walkthrough |
| **Judge Adapter** | [`judge_adapter.py`](judge_adapter.py), documentation [`docs/ADAPTER.md`](docs/ADAPTER.md) |

---

## System Architecture

The environment architecture separates business logic, state mutation, agent inspection, and formal evaluation into five distinct layers:

```
Seed + Config ──► Latent Business Simulation ──► Double-Entry Clean Books
                                                        │
                                                        ▼
                        Error Injection Engine (4 Families + Decoys)
                                                        │ (Recorded in provenance.json)
                                                        ▼
                               Ground Truth Derived from Published Policy
                                                        │
AI Auditor ◄── 5 Tools (reset/step) ── Public Books ──► Bipartite Matcher ──► Return
```

1. **Latent Company Simulation:** Generates customer entities, transaction schedules, multi-currency pricing, and exchange rate series. Standard double-entry ledger entries (`ledger.csv`, `invoices.jsonl`, `payments.jsonl`, `fx.csv`) are posted from this timeline, ensuring debits and credits reconcile by construction. All currency amounts are represented as exact integers in minor units to eliminate floating-point imprecision.
2. **Deterministic Error Injection:** Applies realistic operational discrepancies (duplicate billing, partial settlement allocation, foreign exchange translation errors, cutoff misallocations). Each mutation records its exact diff in `provenance.json`—inverting provenance mathematically reconstructs the original balanced books.
3. **Decoys and Complex Invariants:** Incorporates valid business edge-cases to prevent models from learning trivial heuristics: legitimate recurring billing schedules, multi-part split payments, refunds, and cross-timezone postings.
4. **Agent Observation & Interaction:** Conforms to standard Gym lifecycle semantics (`reset` and `step`). The action space is strictly bounded to five inspection tools:
   - `list_records(table, cursor, limit)`: Deterministic paginated traversal over ledger entries, invoices, payments, or FX tables (maximum 50 rows per page).
   - `get_record(table, record_id)`: Point lookup by primary key.
   - `get_document(doc_type, doc_id)`: Retrieval of primary source JSON documents.
   - `calculator(expression)`: Deterministic string arithmetic calculator.
   - `submit(findings)`: Final submission of structured audit findings.
5. **Bipartite Matching & Scoring:** A submitted finding is evaluated as a True Positive if its error type, affected IDs, calculated amount, currency, and documentary evidence match ground truth exactly. Matching is formulated as Maximum Bipartite Matching with deterministic tie-breaking. Precision ($P$), Recall ($R$), and an inspection step cost are combined into a bounded return in $[-1.0, 1.0]$.

---

## Accounting Error Families

Every discrepancy rule is explicitly defined in `policy.json` and is verified to be decidable from public documentary evidence across the shipped episodes:

| Error Family | Environment `type` | `affected_ids` | `claimed_amount_minor` | Minimal Evidence Set |
|---|---|---|---|---|
| **Duplicate Invoices** | `duplicate_invoice` | `{invoice_id}` of every record of the duplicated obligation | $\text{total} \times (\text{records} - 1)$ | `doc_id` of each duplicated invoice |
| **Payment Allocation** | `payment_allocation` | `{invoice_id, payment_id}` | $\text{required} - \text{recorded}$ allocation | Invoice document, payment document, accounts receivable rows (+ FX row if foreign currency) |
| **FX Rate / Date Mismatch** | `fx_mismatch` | `{payment_id}` | $|\text{recorded} - \text{required translation}|$ | Payment document, selected FX rate entry, `fx_clearing` ledger row |
| **Reporting Period Cutoff** | `cutoff` | `{invoice_id}` | Invoice total | Invoice document, corresponding revenue ledger entry |

### Compound Interaction Scenarios
- `cutoff_and_allocation`: An invoice posted outside the reporting period combined with a cross-currency partial payment allocation across period boundaries.
- `duplicate_then_cutoff`: An invoice duplicated, where the duplicate record is erroneously recorded in a different accounting period.

---

## Judge Adapter Interface (`judge_adapter.py`)

[`judge_adapter.py`](judge_adapter.py) implements the automated evaluation interface defined by the case specification:

```python
import judge_adapter

# 1. Generate an episode from a seed and configuration
judge_adapter.generate_episode(seed=42, config=config, output_dir="out/episodes/eval_01")

# 2. Instantiate the standardized environment
env = judge_adapter.make_env()
obs, info = env.reset(seed=42, config={"mode": "closed", "episode_dir": "out/episodes/eval_01"})

# 3. Step through the tool interface (closed mode suppresses intermediate reward)
obs, reward, terminated, truncated, info = env.step({
    "name": "list_records",
    "args": {"table": "ledger", "cursor": None, "limit": 50}
})

# 4. Score audit findings externally against hidden truth
score = judge_adapter.score_episode("out/episodes/eval_01", findings=findings, inspection_steps=18)
# Returns {"tp": ..., "fp": ..., "fn": ..., "precision": ..., "recall": ..., "f1": ..., "return": ...}
```

- **Closed Evaluation Mode:** During evaluation, intermediate rewards are fixed at `0.0` and `info` is empty to prevent state leakage.
- **Resource Constraints:** 100 steps total (including `submit`) and 60 seconds wall-clock budget per episode.
- **Evidence Cap:** Maximum 10 evidence IDs per finding.

---

## Benchmark Results

Evaluation across all 20 shipped train and dev episodes in closed mode (`make judge`):

<!-- RESULTS:START -->
| Policy | Precision | Recall | F1 Score | Return | Mean Inspection Steps | Mean Wall Time / Episode |
|---|---|---|---|---|---|---|
| **Random Explorer** | 0.000 | 0.000 | 0.000 | -1.000 | 4.0 | 0.005 s |
| **Simple Reconciliation** | 0.041 | 0.313 | 0.071 | -0.874 | 19.7 | 0.013 s |
| **Flag-All Attack** | 0.012 | 0.121 | 0.021 | -0.972 | 17.6 | 0.014 s |
| **Oracle** (reads hidden truth) | 0.750 | 0.750 | 1.000 | 1.000 | 0.0 | 0.009 s |
| **Our Rule-Following Solver** (reads zero truth) | **0.750** | **0.750** | **1.000** | **0.961** | **19.7** | **0.012 s** |
<!-- RESULTS:END -->

> [!NOTE]
> On the 20 shipped train and dev episodes evaluated via `make judge`, our rule-following solver achieves an **$F_1$ score of 1.000** on all faulty episodes (mean return `0.961` across all 20 episodes, penalized only by the inspection step cost: $0.002 \times 19.7 = 0.039$; on clean episodes containing zero accounting errors, Precision and Recall are defined as `0.0` by the case rules, giving a mean $P$ and $R$ of `0.75`). Across the full test harness verification log, the truth-blind solver achieves $F_1 = 1.0$ on 138 evaluation runs over all 31 shipped episodes (including perturbed twins, with worst return `0.896`). This is a finite empirical evaluation on the 31 shipped episodes, not a formal proof for all possible cases or unconstrained company configurations.

Detailed per-episode and per-family breakdowns are provided in [`docs/RESULTS.md`](docs/RESULTS.md).

---

## Testing and Verification

```bash
uv run pytest                 # Full test suite: 1,247 collected tests (1,245 passed, 2 skipped)
uv run pytest --collect-only  # Inspect all 1,247 collected test items across 493 test definitions
uv run pytest tests/jury      # Conformance tests for official check definitions
```

- **Exact Test Coverage:** The repository contains **493 test definitions (`def test_`)** across 29 test files, which expand into **1,247 collected test cases** through parametrization over contract suites C01–C20, scenario episodes D01–D20, matcher invariants M01–M12, and paired checks P01–P20. In test execution (`uv run pytest`), **1,245 passed and 2 were skipped** (the 2 skipped are Docker boundary probes in `test_boundary.py` that require a container environment and execute in `make docker-check`).
- **Official Check IDs:** Validates contract checks C01–C20, scenario episodes D01–D20, matcher invariants M01–M12, and paired checks P01–P20.
- **Core Verification Invariants:**
  - True findings with complete evidence strictly outperform silence on faulty books.
  - Silence strictly outperforms speculative flagging on clean books.
  - Duplicate claims receive zero credit and are penalized as false positives.
  - Guessed IDs or invalid structural payloads are penalized.
  - Every episode regenerates byte-for-byte from its PRNG seed.

---

## Limitations

- **Rule-Following Solver vs. Learned Models:** The rule-following script solves the 20 shipped train and dev case episodes ($F_1 = 1.000$, return $0.961$ in `make judge`), and reaches $F_1 = 1.0$ across 138 evaluation runs over all 31 shipped episodes (including perturbed twins) in the verification self-check. This is a finite empirical evaluation on the 31 shipped episodes, not a proof for all possible cases or arbitrary corporate topologies. It benchmarks policy compliance and structured record parsing against published rules, not open-ended natural language reasoning. No machine learning model or neural network was trained in this submission, and no empirical learning claims are made.
- **Process Isolation & Containment Boundary:** Process confinement (setuid unprivileged execution under Docker, Seatbelt sandboxing on macOS) strictly confines policy processes to `/app/policies` and standard system binaries, preventing reads of `truth.json`, `provenance.json`, private keys, evaluator memory, network interfaces, or arbitrary host paths. However, this confinement relies on OS user/process boundaries; it does not protect against host kernel vulnerabilities or unconstrained memory allocation if external cgroup limits are omitted.
- **Calculated vs. Measured Quantities:** Step bounds (100 steps max, 52 steps maximum required to read any company in full) and algorithmic complexity are exact structural invariants. Clock runtimes (slowest solver episode < 0.13 s) and memory peaks (evaluator ~43 MB, policy ~28 MB) recorded in `docs/measurements/scale.json` are empirical measurements on the test host and vary across hardware.
- **Memorisation vs. Generalization:** Memorisation fails completely under perturbation. A memorising agent that replays stored findings achieves $F_1 = 0.000$ and return $-1.000$ on unseen twin episodes with renamed identifiers and shuffled rows (scoring identically to an abstaining policy, $-1.000$), demonstrating that evaluation cannot be bypassed by rote memorisation.
- **Accounting & Generator Scope:** All simulated businesses operate under a uniform double-entry accounting standard with standard charts of accounts. Variations cover transaction graph topology, volume (200 to 2,000 ledger rows), counterparty networks, currency translations (6 currencies), and timezone offsets (+09:00 to -05:00) rather than diverse legal accounting frameworks.
- **Accounting Identities vs. Audit Ground Truth:** All clean and mutated episodes maintain internal double-entry balance ($\text{Debits} = \text{Credits}$). Balanced books do not imply error-free records; subtle cutoff shifts, missing allocations, and exchange rate misstatements persist within mathematically balanced ledgers.
- **Official Runtime Envelope:** Conforms strictly to the official public specification: **60-second wall-clock limit** and **100-step budget** per episode in an isolated offline environment (`--network none`). Hardware resource allocations (CPU / RAM) depend on the host runner; the system runs without GPU acceleration or specialized hardware.

---

## Repository Structure

| Path | Purpose |
|---|---|
| `src/genesis_audit/env.py`, `store.py`, `calculator.py` | Gym environment, inspection tools, step budgets, error bounds |
| `src/genesis_audit/schemas.py`, `matching.py`, `scoring.py` | Schema validation, maximum bipartite matching, reward computation |
| `src/genesis_audit/families.py` | Implementation of the four accounting error family rules |
| `src/genesis_audit/world.py`, `books.py`, `shipped.py` | Business simulation generator, double-entry ledgers, shipped episodes |
| `judge_adapter.py`, `baselines/`, `tools/judge_run.py` | Official judge adapter interface, baseline policies, benchmark runner |
| `tools/independent_checker.py` | Independent verification tool deriving ground truth from public data |
| `episodes/` | 10 train and 10 dev episodes with complete public and private halves |
| `docs/` | [Design note](docs/DESIGN.md), [Adapter spec](docs/ADAPTER.md), [Specification](docs/SPEC.md), [Results](docs/RESULTS.md) |
| `NOTES.md` | Team engineering journal and implementation notes |

---

## License

MIT License. See [`LICENSE`](LICENSE) for details.
