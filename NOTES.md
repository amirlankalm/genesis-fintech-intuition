# Team Intuition: Engineering Workbook & Technical Notes

**Genesis Hackathon 2026 · FinTech Case: "RL environments for post-training financial-audit models"**
**Team:** Intuition  
**Timeline:** 19–20 November 2026  

---

## 1. Case Overview & Our Approach

We are **Team Intuition**. For this Genesis Hackathon FinTech case, our goal was to build an industrial-strength, Gym-compatible practice environment for post-training AI financial auditors. 

In financial auditing, large language models cannot simply generate open-ended prose or guess. A valid audit finding must identify the exact transaction, calculate the precise discrepancy amount, and link the definitive primary source documents (invoices, bank lines, receipts) as proof. Furthermore, false alarms in audit are toxic—every false accusation wastes valuable investigator time.

We structured our environment around three non-negotiable principles:
1. **Mathematical Invariants First:** Synthetic company books must balance by construction using real double-entry accounting (Debits = Credits).
2. **Reversible Error Injection:** Every accounting defect must be injected with explicit provenance (`provenance.json`), so inverting the provenance mathematically proves the baseline books are clean.
3. **Strict One-to-One Bipartite Matching:** Evaluation must not be fooled by duplicate claims, vague amounts, or guessed IDs. Findings are matched to hidden ground truth using a maximum bipartite matching algorithm with formal tie-breaking.

---

## 2. Key Architecture & Design Decisions

### 2.1 Synthetic Company Generation (`src/genesis_audit/world.py`, `books.py`)
- **Zero Real Data:** All names, companies, bank accounts, and transactions are 100% synthetically generated from random seeds.
- **Double-Entry Consistency:** A latent business history is generated (sales, customer orders, payment terms, FX rates). Transactions are posted across standard financial ledgers (`ledger.csv`, `invoices.jsonl`, `payments.jsonl`, `fx.csv`).
- **Exact Minor Currency Units:** To eliminate floating-point rounding issues (e.g., `0.1 + 0.2 != 0.3`), all monetary amounts are stored as exact integers in minor units (cents for USD/EUR, tiyn for KZT, integer yen for JPY).

### 2.2 The Four Error Families (`src/genesis_audit/families.py`)
We modeled the four core accounting failure modes specified in the hackathon case:
1. `duplicate_invoice`: Duplicate billing records where the obligation is recorded more than once. Evidence requires every duplicated document ID.
2. `payment_allocation`: Missing or partial allocation of payments against invoices. Evidence requires invoice, payment receipt, and accounts receivable ledger entries.
3. `fx_mismatch`: Foreign exchange rate or translation date errors. Evidence requires payment document, the reference FX rate, and the `fx_clearing` ledger entry.
4. `cutoff`: Transactions recorded in the wrong reporting accounting period. Evidence requires invoice document and corresponding revenue ledger rows.

### 2.3 Decoys & Realistic Hard Cases
To prevent AI models from relying on superficial shortcuts (e.g., flagging any repeated amount as a duplicate), we deliberately engineered legitimate business edge-cases:
- Legitimate weekly recurring invoices with identical amounts and line items.
- Legitimate split payments (one invoice paid via two separate receipts).
- Legitimate refunds and credit notes.
- Invoices and payments recorded across different UTC timezone offsets.

### 2.4 Agent Tool Environment (`src/genesis_audit/env.py`)
The environment implements a Gym-like lifecycle with `reset(seed, config)` and `step(action)`. To ensure deterministic safety and prevent sandbox escapes, the agent has access to exactly five narrow tools:
- `list_records(table, cursor, limit)`: Paginated reading with deterministic cursors (max 50 rows).
- `get_record(table, record_id)`: Point lookup by primary key.
- `get_document(doc_type, doc_id)`: Retrieves JSON source documents.
- `calculator(expression)`: Deterministic string arithmetic calculator.
- `submit(findings)`: Submits the final report of findings.

### 2.5 Maximum Bipartite Matching & Scoring (`src/genesis_audit/matching.py`, `scoring.py`)
- Findings are evaluated against hidden ground truth.
- A finding is a **True Positive (TP)** if and only if:
  1. Error `type` matches exactly.
  2. `affected_ids` match exactly.
  3. `claimed_amount_minor` matches exactly.
  4. `currency` matches.
  5. The submitted evidence contains the required minimal evidence set without referencing non-existent IDs.
- Matching is one-to-one via the Hopcroft-Karp / augmenting-path bipartite matching algorithm. Duplicate submissions cannot claim multiple true positives and are penalized as False Positives.
- **Return Function:**
  $$\text{Return} = \text{clip}\left(2 \cdot F_1 - 1 - 0.002 \cdot \text{inspection\_steps}, -1.0, 1.0\right)$$

### 2.6 Official Judge Adapter (`judge_adapter.py`)
To ensure full compliance with the hackathon's automated evaluation system, we implemented `judge_adapter.py` matching the official check definitions:
- `generate_episode(seed, config, output_dir)`: Generates complete episode directories.
- `make_env()`: Returns the standardized audit environment.
- `score_episode(episode_dir, findings, inspection_steps)`: Computes exact TP, FP, FN, Precision, Recall, F1, and Return.
- Closed-mode evaluation: Agent receives observation without intermediate reward signals, eliminating reward leakage.

---

## 3. Benchmark Baselines & Results

We evaluated our rule-following solver against standard reference baselines on all 20 shipped train and dev episodes (`make judge`):

| Policy | Precision | Recall | F1 Score | Return | Steps |
|---|---|---|---|---|---|
| **Random Explorer** | 0.000 | 0.000 | 0.000 | -1.000 | 4.0 |
| **Simple Reconciliation** | 0.041 | 0.313 | 0.071 | -0.874 | 19.7 |
| **Flag-All Attack** | 0.012 | 0.121 | 0.021 | -0.972 | 17.6 |
| **Oracle** (reads hidden truth) | 0.750 | 0.750 | 1.000 | 1.000 | 0.0 |
| **Our Rule-Following Solver** | **0.750** | **0.750** | **1.000** | **0.961** | **19.7** |

*Note: Clean episodes (episodes with zero errors) have P and R defined as 0.0 by the case specification, giving a mean P and R of 0.75 across the dataset. On all episodes containing errors, our solver achieves an F1 of 1.0.*

---

## 4. Engineering Verification & Quality Gates

During our build, we established rigorous automated tests to ensure 100% reproducibility:
- **Lint & Types:** Ruff (lint + format) and Mypy strict type-checking across all source modules (`make lint`).
- **Unit & Integration Tests:** 1,247 collected tests across 493 test definitions (`def test_`) in 29 test files (1,245 passed, 2 skipped container boundary probes), covering contract checks C01–C20, scenario episodes D01–D20, matcher invariants M01–M12, and paired checks P01–P20 (`pytest`).
- **Deterministic Replay:** Verified that every shipped episode regenerates byte-for-byte identically from its PRNG seed (`make check`).
- **Container Isolation:** Validated within Docker under the official offline constraints: Python 3.11, 60s wall-clock limit, 100-step budget, and `--network none`.

---

## 5. Team Intuition Takeaways

Building this environment taught us immense lessons in:
1. Software architecture for AI systems: how to build environments that cannot be cheated or crashed by unpredictable model outputs.
2. The nuances of real-world accounting: double-entry ledgers, currency conversions, and why proof in audit requires tracing every claim back to the primary source.
3. Rigorous testing: how writing tests against official contract specifications ensures seamless integration with external judging platforms.
