# Answer key: the hand-built case fixture

Worked by hand from the history written in `src/genesis_audit/shipped.py` (`FIXTURE_WORLD`), before any code computed it. `tests/test_case_fixture.py` pins every number below with literals; the independent checker re-derives them from the public files. Evaluator-side: this file is in the private half and no policy can read it.

**The company.** Books in KZT (two decimals), also USD (two) and JPY (none). Company offset +05:00. Period 1 to 31 October 2026, both ends inclusive.

## The clean books

| Invoice | Customer | Issued (as written) | Total | Settled by |
|---|---|---|---|---|
| I21 | E3 | 5 Oct 10:00 +05 | 300,000 KZT | P14, 300,000 |
| I08 | E5 | 9 Oct 15:00 +05 | 5,000,000 KZT | P31, USD 100.00 |
| I17, I26, I02 | E3 | 7, 14, 21 Oct 09:00 +05 | 80,000 KZT each | P05; P22; P09 50,000 + P18 30,000 |
| I11 | E7 | 31 Oct 22:00 +05 | 120,000 KZT | unpaid |
| I30 | E9 | 1 Nov 03:15 +09 | 200,000 KZT | P27, 230,000 (30,000 refunded) |
| I19 | E7 | 2 Nov 10:00 +05 | 90,000 KZT | unpaid |
| I24 | E6 | 15 Oct 12:00 +05 | 58,824 JPY | P40, 200,000.00 KZT |

Why nothing here is an issue:

- **I17, I26, I02** have the same customer, lines and total. Their `issued_at` and `due_at` differ, so by the duplicate rule they are three obligations.
- **I02** is settled by two receipts (50,000 then 30,000). Each is applied in full.
- **P27** pays 230,000 on an invoice of 200,000. The policy applies 200,000 and leaves 30,000 unapplied; the refund returns it.
- **I30** is written as 1 November 03:15 at +09:00. That instant is 31 October 23:15 at +05:00: inside the period. Its revenue row is at 31 October 23:40: same side.
- **I19** is issued and posted after the period: both after.
- **P31** is written as 20 October 21:30 at +00:00. Its local date is 21 October (02:30 at +05:00), so the policy rate is the one dated 21 October, 500.00 KZT per USD: 100.00 x 500.00 = 50,000.00 KZT = 5,000,000 minor units. That settles I08 exactly.
- **P40** is 200,000.00 KZT for a JPY invoice. The pair is quoted JPY to KZT at 3.40, and the receipt is in the target currency, so divide: 200,000.00 / 3.40 = 58,823.529... JPY. JPY has no minor unit; half up gives 58,824, the invoice total.

## The variants

| Variant | Error | Reasoning | Issue |
|---|---|---|---|
| `fixture_duplicate` | I26 keyed again as I33 (document D58) | I26 and I33 agree in customer, currency, both instants and lines. Two records, one obligation: 80,000 x (2 - 1). | `duplicate_invoice`, {I26, I33}, 80,000 KZT, evidence D07 + D58 |
| `fixture_allocation` | P22 (80,000 for I26) left wholly unapplied | I26 is open for 80,000 when P22 arrives, so 80,000 is required and 0 is recorded. No receivable row carries both ids. | `payment_allocation`, {I26, P22}, 80,000 KZT, evidence D07 + D25 |
| `fixture_fx` | P31 translated at the 20 October rate, 490.00 | Recorded 100.00 x 490 = 4,900,000; required 5,000,000. | `fx_mismatch`, {P31}, 100,000 KZT, evidence D03 + `2026-10-21\|USD\|KZT` + the clearing debit |
| | P40 translated at the 24 October rate, 3.36 | Recorded 200,000.00 / 3.36 = 59,523.81, half up 59,524; required 58,824. | `fx_mismatch`, {P40}, 700 JPY, evidence D19 + `2026-10-25\|JPY\|KZT` + the clearing debit |
| `fixture_cutoff` | I11 posted on 1 November 09:00 | Issued 31 October 22:00, inside; revenue row after. | `cutoff`, {I11}, 120,000 KZT, evidence D29 + the revenue row |
| `fixture_x_fx_allocation` | P31 at 490.00, and only 4,000,000 applied | The wrong rate: 100,000 as above. Then allocation is measured against the 4,900,000 *recorded*: required min(4,900,000, 5,000,000) = 4,900,000, recorded 4,000,000. | `fx_mismatch` {P31} 100,000 (evidence as in `fixture_fx`) and `payment_allocation` {I08, P31} 900,000 KZT, evidence D12 + D03 + the receivable row carrying I08 and P31 + P31's clearing debit (the receipt is in USD, the invoice in KZT, so what it brings, 4,900,000, is that row; policy `case-draft-2`) |
| `fixture_x_duplicate_cutoff` | I11 keyed again as I35, the copy posted 1 November 08:30 | I11 and I35 are one obligation: 120,000. I35 is issued inside (it copies I11's 31 October 22:00) and its revenue row is after. I11 itself is posted correctly. | `duplicate_invoice` {I11, I35} 120,000 and `cutoff` {I35} 120,000 |

In `fixture_fx` there is no allocation issue: the 4,900,000 recorded for P31 is applied in full (I08 keeps an open balance of 100,000), and of the 59,524 JPY recorded for P40, 58,824 is applied and 700 is unapplied credit. The wrong rate is counted once.
