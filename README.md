# Genesis FinTech: an RL Environment for Financial-Audit AI Models

**English** · [Русский](README.ru.md) · [Қазақша](README.kk.md)

**Team Intuition · Genesis Hackathon 2026 (FinTech Case: "RL environments for post-training financial-audit models")**

👋 **Hi from Team Intuition!** We are a high school student team participating in the **Genesis Hackathon 2026**. For this FinTech case, we designed and built a complete, reproducible Reinforcement Learning (RL) practice world for post-training and evaluating AI financial auditors. 

In financial auditing, AI models cannot simply guess or hallucinate text: every finding must be backed by concrete mathematical evidence, and false accusations are just as damaging as missed errors. We built a gym-compatible environment where a seeded generator writes a synthetic company's books for a reporting period, injects subtle accounting errors alongside realistic decoys, lets an AI agent investigate via 5 narrow tools, and scores findings against ground truth using a strict one-to-one bipartite matching algorithm and the case's standardized reward function.

> [!NOTE]
> **100% Synthetic & Private:** Everything is generated purely in-memory from deterministic seeds. No real company, individual, bank, card, or payment data is used.

**Hackathon Timeline:** Built and validated during the hackathon (19–20 November 2026). Fully aligned with the final case specifications and the official check definitions published on 20 November (`judge_adapter.py`, matcher conventions M01–M12, scenarios D01–D20).

---

## ⚡ Run it: One Command

```bash
make check
```

Runs code formatting, types, unit tests with coverage, and self-checks.

To run the four benchmark baselines and our solver through the official judge adapter:
```bash
make judge
```

### Docker (Evaluator Envelope: 2 CPUs, 4 GB RAM, No Network)
```bash
make docker-check
```
Or directly with plain Docker:
```bash
docker build -t genesis-audit-env . && docker run --rm --network none --cpus 2 --memory 4g genesis-audit-env
```

Without Docker (macOS or Linux, with [uv](https://docs.astral.sh/uv/) installed):
```bash
uv sync --frozen   # Python 3.11+; dev tools locked in uv.lock
make check         # lint, mypy types, tests with coverage, self-check
make judge         # run baselines & solver via judge_adapter.py + conformance tests
```

Working directory is the repository root (`/app` inside the container). No network is needed after `uv sync`, and no GPU or external paid API is required.

---

## 📦 What We Submit (Case Section 09)

| Required Deliverable | Location in Repository |
|---|---|
| **Source & Pinned Dependencies** (generator & RL environment) | [`src/genesis_audit/`](src/genesis_audit/), [`LICENSE`](LICENSE) (MIT), [`uv.lock`](uv.lock) |
| **README & Dockerfile** (container instructions + single check command) | [`README.md`](README.md), [`Dockerfile`](Dockerfile), [`Makefile`](Makefile) |
| **Matcher, Reward, Schemas & Policies** | [`src/genesis_audit/matching.py`](src/genesis_audit/matching.py), [`scoring.py`](src/genesis_audit/scoring.py), [`schemas.py`](src/genesis_audit/schemas.py); [`docs/schemas/`](docs/schemas/) |
| **10 Train & 10 Dev Episodes** | [`episodes/`](episodes/), split index [`episodes/splits.json`](episodes/splits.json) |
| **Comprehensive Test Suite** | [`tests/`](tests/) (~1,240 tests, validating every official check by ID) |
| **Four Benchmark Baselines + Our Solver** | [`baselines/`](baselines/): random explorer, simple reconciliation, flag-all, oracle, solver |
| **Trajectory File** (`trajectories.jsonl`) | [`trajectories.jsonl`](trajectories.jsonl) |
| **Design Documentation** | [`docs/DESIGN.md`](docs/DESIGN.md) ([Русский](docs/DESIGN.ru.md)), [`docs/SPEC.md`](docs/SPEC.md) |
| **Video Demonstration** | [`demo/`](demo/): recorded terminal walkthrough of the environment |
| **Official Judge Adapter** | [`judge_adapter.py`](judge_adapter.py), documentation [`docs/ADAPTER.md`](docs/ADAPTER.md) |

---

## 🧠 How It Works: High-School Intuition

As high school students tackling RL and financial auditing, we broke the problem down into 5 intuitive layers:

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

1. **Latent Company Simulation:** Before creating invoices, we simulate the business lifecycle: customers, currencies, timezones, and transactions. Clean double-entry ledger books are posted from this history, guaranteeing that debits and credits balance by construction.
2. **Deterministic Error Injection:** Errors represent realistic human bookkeeping mistakes (duplicate invoices, unallocated receipts, FX translation mistakes, period cutoff mismatches). Each injected error records its exact diff in `provenance.json`—reversing it perfectly restores clean books.
3. **Decoys and Realistic Complexity:** A company isn't just full of errors—it has legitimate edge cases! We generate split payments, refunds, recurring identical subscriptions, and timezone offsets so models cannot cheat with trivial heuristic rules.
4. **Agent Observation & Interaction:** Following standard Gym / Farama design, the agent interacts through `reset()` and `step()`. To keep execution secure and bounded, the agent gets exactly 5 tools:
   - `list_records(table, cursor, limit)`: Paginated view over `ledger`, `invoices`, `payments`, `fx`.
   - `get_record(table, record_id)`: Fetches a single ledger row or FX rate.
   - `get_document(doc_type, doc_id)`: Fetches original source documents (invoice/payment JSONs).
   - `calculator(expression)`: Safe string calculator for exact arithmetic (e.g. `"0.1+0.2"` → `"0.3"`).
   - `submit(findings)`: Submits the final audit findings report.
5. **Rigorous Bipartite Matching & Scoring:** An audit finding is only a True Positive if its error type, affected IDs, amount, currency, and evidence documents all match. We formulate evaluation as a Maximum Bipartite Matching problem with formal tie-breaking. Precision, Recall, F1, and a step inspection tax are combined into a final Return in `[-1.0, 1.0]`.

---

## 🔍 The Four Error Families

Each error rule is specified in the episode's `policy.json` and is strictly decidable using only public evidence:

| Case Error Type | Environment `type` | `affected_ids` | `claimed_amount_minor` | Required Minimal Evidence |
|---|---|---|---|---|
| **Duplicate Invoices** | `duplicate_invoice` | `{invoice_id}` for every record of duplicate obligation | `total × (records - 1)` | Document ID of each duplicated record |
| **Payment Allocation** | `payment_allocation` | `{invoice_id, payment_id}` | `required - recorded` allocation | Invoice doc, payment doc, accounts receivable rows (+ FX row if cross-currency) |
| **FX Rate / Date Mismatch** | `fx_mismatch` | `{payment_id}` | `abs(recorded - required translation)` | Payment doc, FX table key selected by policy, `fx_clearing` ledger row |
| **Wrong Reporting Period** | `cutoff` | `{invoice_id}` | Invoice total | Invoice doc, corresponding revenue ledger row |

### Complex Compound Scenarios
- `cutoff_and_allocation`: An invoice posted in the wrong reporting period whose receipt is also partially allocated in a foreign currency across period boundaries.
- `duplicate_then_cutoff`: An invoice duplicated, where the copied invoice is mistakenly shifted into the wrong period.

---

## ⚖️ Official Judge Adapter (`judge_adapter.py`)

Our submission provides [`judge_adapter.py`](judge_adapter.py) implementing the official case check specification:

```python
import judge_adapter

# 1. Generate an episode with seed and config
judge_adapter.generate_episode(seed=42, config=config, output_dir="out/episodes/eval_01")

# 2. Instantiate the environment
env = judge_adapter.make_env()
obs, info = env.reset(seed=42, options={"mode": "closed", "episode_dir": "out/episodes/eval_01"})

# 3. Step through tools (closed mode hides intermediate rewards)
obs, reward, terminated, truncated, info = env.step({
    "name": "list_records",
    "args": {"table": "ledger", "cursor": None, "limit": 50}
})

# 4. Evaluate findings against hidden truth
score = judge_adapter.score_episode("out/episodes/eval_01", findings=findings, inspection_steps=18)
# Returns {"tp": ..., "fp": ..., "fn": ..., "precision": ..., "recall": ..., "f1": ..., "return": ...}
```

- **Closed Evaluation Mode:** During testing, the agent sees `reward = 0.0` at every step, preventing reward hacking or state leakage. The true score is computed externally by the judge adapter.
- **Strict Budgets:** Max 100 steps (including submit) and 60 seconds per episode.
- **Evidence Limit:** Maximum 10 evidence document IDs per finding.

---

## 📊 Benchmark Results

Evaluated in closed mode across all 20 shipped train and dev episodes (`make judge`):

<!-- RESULTS:START -->
| Policy | Precision | Recall | F1 Score | Return | Mean Inspection Steps | Mean Time / Episode (s) |
|---|---|---|---|---|---|---|
| **Random Explorer** | 0.000 | 0.000 | 0.000 | -1.000 | 4.0 | 0.005 s |
| **Simple Reconciliation** | 0.041 | 0.313 | 0.071 | -0.874 | 19.7 | 0.013 s |
| **Flag-All Attack** | 0.012 | 0.121 | 0.021 | -0.972 | 17.6 | 0.014 s |
| **Oracle** (reads hidden truth) | 0.750 | 0.750 | 1.000 | 1.000 | 0.0 | 0.010 s |
| **Our Rule-Following Solver** (reads zero truth) | **0.750** | **0.750** | **1.000** | **0.961** | **19.7** | **0.012 s** |
<!-- RESULTS:END -->

> [!TIP]
> **Understanding the Scores:** On completely clean episodes with zero errors, Precision and Recall are defined as 0.0 by the case rules, which is why mean P and R across all episodes are 0.75. On all episodes with errors, our solver achieves a **perfect 1.0 F1 score**, only losing 0.039 from the inspection step tax ($0.002 \times 19.7$). Naive baselines score near the $-1.0$ floor because our realistic decoys defeat simple heuristics!

Detailed per-episode breakdowns are available in [`docs/RESULTS.md`](docs/RESULTS.md).

---

## 🧪 Comprehensive Verification Suite

```bash
uv run pytest                 # Full suite: ~1,240 tests passing
uv run pytest tests/jury      # Conformance tests for the official checks
```

- **Official Case Checks:** Implements and verifies every single test ID (contract checks C01–C20, scenario episodes D01–D20, matcher checks M01–M12, and paired checks P01–P20).
- **Core Behavioral Invariants:**
  - Supported evidence beats silence on faulty books.
  - Silence beats false alarms on clean books.
  - Repeated findings earn zero credit and generate false positives.
  - Guessed IDs and invalid evidence structures are penalized.
  - Every episode regenerates byte-for-byte identically from its seed.

---

## 🗺️ Repository Structure

| Path | Description |
|---|---|
| `src/genesis_audit/env.py`, `store.py`, `calculator.py` | Gym environment, 5 inspection tools, budgets, error isolation |
| `src/genesis_audit/schemas.py`, `matching.py`, `scoring.py` | Observation/action schemas, maximum bipartite matching, reward computation |
| `src/genesis_audit/families.py` | The four accounting error family definitions and decider logic |
| `src/genesis_audit/world.py`, `books.py`, `shipped.py` | Seeded business generator, double-entry bookkeeping, shipped episodes |
| `judge_adapter.py`, `baselines/`, `tools/judge_run.py` | Official judge adapter interface, benchmark baselines, execution harness |
| `tools/independent_checker.py` | Independent cross-verification script validating ground truth from public data |
| `episodes/` | 10 train and 10 dev generated episodes with complete data files |
| `docs/` | [Design note](docs/DESIGN.md), [Adapter spec](docs/ADAPTER.md), [Full specification](docs/SPEC.md), [Results](docs/RESULTS.md) |
| `NOTES.md` | Our team's engineering log and technical design journal |

---

## ⚖️ License

MIT License. See [`LICENSE`](LICENSE) for details.
