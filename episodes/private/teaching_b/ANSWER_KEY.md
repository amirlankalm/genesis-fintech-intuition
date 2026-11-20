# Answer key - teaching episode `teaching_b` (private)

Instructor copy. Do not show before the learner submits. `truth.json` is the machine-readable form.

## Hand calculation

All amounts are KZT minor units (exponent 2).

**Invoice I7** - total 5 x 50,000 = 250,000.

- Receipt P9 (document D44): 260,000, references I7.
- Open balance when P9 arrives: 250,000. Required allocation: min(260,000, 250,000) = 250,000.
- Recorded allocation of P9 to I7: row L11 = 150,000.
- Shortfall: 250,000 - 150,000 = **100,000** (1,000.00 KZT).
- Row L13 parks 110,000 in `unapplied_receipts`. Only 10,000 of that is a genuine excess over the open balance. The other 100,000 belongs on the invoice, which still shows 100,000 open.

**Invoice I3** - total 2 x 125,000 = 250,000.

- Receipt P2 (D27): 150,000. Open balance 250,000, required 150,000, recorded L17 = 150,000. Correct.
- Receipt P5 (D36): 120,000. Open balance 100,000, required 100,000, recorded L23 = 100,000. Correct.
- The remaining 20,000 of P5 (row L06) exceeds the open balance, so it is legitimate customer credit. A valid split payment with an overpayment. No finding.

**Balance check:** debits 250,000 + 250,000 + 260,000 + 150,000 + 120,000 = 1,030,000; credits 250,000 + 250,000 + 150,000 + 110,000 + 150,000 + 100,000 + 20,000 = 1,030,000. The books balance with the error in them, as they should: balance is necessary, not sufficient.

## Expected submission

One finding:

| Field | Value |
|---|---|
| type | `payment_allocation` |
| affected_ids | `I7`, `P9` |
| claimed_amount_minor | `100000` |
| currency | `KZT` |
| evidence_ids | `D31`, `D44`, `L11` (the invoice document, the payment document, the allocation row). Adding `L19` or `L13` is allowed and not required. |

## Wrong answers this fixture is built to catch

| Answer | Why it fails |
|---|---|
| Amount 110000 for I7/P9 | "Receipt minus allocated", or the whole unapplied row. It ignores the open-balance rule: 10,000 of it is a real excess. |
| Also flag I3/P5 for 20,000 | Treats every unapplied row as an error. That 20,000 is a genuine excess. |
| Amount 1000 | Major units instead of minor units. |
| Amount 260000 | The whole receipt instead of the unallocated part. |
| Evidence without L11, or without one of the two documents | The allocation row and both documents are required: the evidence set is incomplete. |
| Evidence citing `I7` or `P9` | Those are business-object ids, not record ids. Cite the documents D31 and D44. |
| Flag I3 for the 150,000 + 100,000 split | A fully allocated split payment is valid. |

## Clean twin

`teaching_b_clean` is the same company without the mutation: L11 credits 250,000 and L13 holds the genuine 10,000 excess. Same rows, same ids, same counts; two amounts differ. Its truth is empty; the right submission is an empty findings list.
