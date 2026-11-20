# H. One failed trajectory, inspected

**Input.** A public, synthetic trajectory and its evaluator report, both produced by this repo:

- `docs/review/H_inputs/trajectory.jsonl`: what the policy saw and did (5 records).
- `docs/review/H_inputs/evaluator_report.json`: the evaluator's diagnostics, hidden from the policy during the run.

Regenerate: `uv run python -m genesis_audit run --policy reconciliation_naive --episode teaching_b`.

The policy is `reconciliation_naive`, the simple reconciliation baseline, on the faulty teaching episode. Reward: -1.000.

## 1. Observations and hidden diagnostics, kept apart

**What the policy could see (the trajectory):**

| Step | Action | Observation |
|---|---|---|
| 0 | reset | task, manifest, policy, `steps_remaining: 100`. The policy object includes `allocation.note`: a receipt is allocated "up to that invoice's open balance"; "only an excess over the open balance stays in unapplied_receipts". |
| 1 | `list_records(invoices)` | 2 invoices. I7 (doc D31) total 250,000; I3 (doc D12) total 250,000. |
| 2 | `list_records(payments)` | 3 receipts. P9 (D44) 260,000 for I7; P2 (D27) 150,000 for I3; P5 (D36) 120,000 for I3. |
| 3 | `list_records(ledger)` | 12 rows. For P9: L19 bank 260,000; L11 receivable credit 150,000 to I7; L13 unapplied 110,000. For P5: L09 bank 120,000; L23 receivable credit 100,000 to I3; L06 unapplied 20,000. |
| 4 | `submit` with two findings | `status: episode_over`, reward -1.0 |

The two findings it submitted:

| # | affected_ids | claimed_amount_minor | evidence_ids |
|---|---|---|---|
| 0 | I7, P9 | 110,000 | D31, D44, L19, L11, L13 |
| 1 | I3, P5 | 20,000 | D12, D36, L09, L23, L06 |

**What only the evaluator knew (the report):** TP 0, FP 2, FN 1. Finding 0: `amount_outside_tolerance`. Finding 1: `no_issue_with_this_type_and_affected_ids`. One truth issue unmatched. Termination `submitted`, 3 inspection steps, the submission well-formed.

## 2. The earliest externally visible failure

**Step 4, finding 0: the amount 110,000. Class: policy mismatch.**

Going through the possible classes in order, with the records that rule each one in or out:

| Class | Verdict | Why |
|---|---|---|
| Missing fact | No | Every fact the answer needs was on screen by step 3: I7's total (step 1), P9's amount and reference (step 2), row L11 (step 3), and the allocation policy (step 0). |
| Wrong tool call | No | Three list calls returned every record. Steps 1 to 3 are the same calls a correct run makes. |
| Budget | No | 4 of 100 steps used. |
| Output schema | No | The report shows a valid submission. |
| Invalid evidence | No | Finding 0 cites D31, D44 and L11, the complete required set, plus two more record ids, which is allowed. |
| Matching | No | The finding names the right type, pair and currency. It is rejected on amount alone. |
| Arithmetic | No, in the narrow sense | 260,000 - 150,000 is 110,000. The subtraction is right. The wrong quantity was subtracted. |
| **Policy mismatch** | **Yes** | The published policy caps the allocation at the invoice's open balance: required = min(260,000, 250,000) = 250,000. The shortfall is 250,000 - 150,000 = **100,000**. The claim of 110,000 is the receipt minus the recorded allocation, which counts P9's genuine 10,000 overpayment as part of the error. |

Finding 1 is the same mistake a second time. For P5 the open balance of I3 is 250,000 - 150,000 = 100,000, so the policy requires 100,000, and L23 records 100,000. There is no shortfall. 120,000 - 100,000 = 20,000 is the legitimate excess that the policy says "stays in unapplied_receipts". The trajectory shows nothing earlier than step 4 going wrong: the same rule produced both findings.

**What I am not inferring.** The trajectory shows what was claimed, not why. That the claim equals "receipt minus recorded allocation" is an arithmetic observation about two numbers on screen. It also happens to be what the public source of the policy computes (`policies/reconciliation_naive.py`: `shortfall = payment["amount_minor"] - allocated`), which is a fact about the code, not a guess about reasoning.

## 3. Is the expected truth supported by the records?

Yes, so this is not a generator or verifier failure:

- By hand from steps 0 to 3: required 250,000, recorded 150,000, shortfall 100,000 for (I7, P9); nothing for I3.
- `tools/independent_checker.py`, which shares no code with the package and reads public files only, derives the same single issue (the self-check line "independent checker agrees with truth (teaching_b)").
- The evaluator's reason for finding 0 is the amount, with a tolerance of 0 declared in the manifest. 110,000 is outside it; 100,000 is the expected value.

Had the records not supported the truth, the right classification would have been a generator or verifier failure, and the fix would not have touched the policy.

## 4. One minimal patch

Compare the recorded allocation with what the policy **requires**, not with the receipt amount. The patched policy is `policies/reconciliation.py`; the naive one is kept as a shortcut probe. The change, in essence:

```diff
- allocated = sum(row["credit_minor"] for row in rows if row["account"] == receivable)
- shortfall = payment["amount_minor"] - allocated
+ required = min(remaining, open_balance[invoice_id])      # the open-balance rule
+ recorded = sum(row["credit_minor"] for row in rows)      # receivable rows of this invoice and payment
+ shortfall = required - recorded
+ open_balance[invoice_id] -= required                     # by what was required, whatever was recorded
+ remaining -= required
```

Receipts are taken in timestamp order, as the policy says. It reads nothing but observations.

## 5. One regression test

`tests/test_bridge.py::test_policy_aware_reconciliation_is_the_regression_test_for_the_failed_trajectory`:

- the naive and the patched policy make the **same three tool calls**, so the difference is not in the evidence gathered;
- naive: TP 0, FP 2, FN 1, reward -1.0;
- patched: TP 1, FP 0, FN 0, reward 0.994, claiming (I7, P9) 100,000;
- patched on the clean twin: no finding, 0.994, so the decoy no longer draws a false alarm.

Measured after the patch (`docs/RESULTS.md`): `reconciliation` scores 0.994 on all four teaching episodes. A second test builds an episode the policy had not been run on, where the first receipt of a split is under-allocated, and checks that it claims (I3, P2) 50,000 and nothing for the later receipt.

## 6. Uncertainty

- **One company.** All four episodes are variants of the same latent history, one family. The patch fixes this failure; it says nothing about duplicate, FX or cutoff errors, which do not exist here.
- **A memoriser also scores well on the two original episodes** (0.994 on 40 perturbed runs). The control that separates it from the patched policy is one variant with amounts it has not seen, where it scores -1.0. One control is thin evidence.
- **The patch encodes one reading of the allocation policy** (the open balance follows required allocations; ties in receipt time are refused). The independent checker's author read the same sentences the same way, which is two readers, not a proof.
- The diagnosis rests on two findings in one trajectory. It is the earliest visible failure in this run, not a claim about every way this policy can fail.
