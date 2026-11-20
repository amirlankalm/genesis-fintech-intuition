# Prompt B - one episode you can solve on paper

A teaching-only synthetic company. Every name, id and amount is invented. This page holds the public
records only. The answer key is private and is used only when you submit.

## Declared policies

- **Currencies and exponents:** KZT = 2, USD = 2. Base currency KZT; 1.00 KZT is 100 minor units.
- **Timezone:** Asia/Almaty. Every timestamp carries its offset.
- **Period:** 2026-10-01T00:00:00+05:00 to 2026-10-31T23:59:59+05:00.
- **FX date:** `payment_date`. A foreign-currency amount is translated to the base currency at the fx.csv rate dated on the payment's local calendar date. A rate is target units per one source unit.
- **Cutoff:** `invoice_issued_at`. Revenue belongs to the period that contains the invoice issued_at, read in the company timezone.
- **Rounding:** `half_up`.
- **Allocation:** `referenced_invoice_up_to_open_balance`. A bank receipt is allocated to each invoice in its invoice_refs, in order, up to that invoice's open balance when the receipt arrives. Only an excess over the open balance stays in unapplied_receipts as customer credit. Receipts are taken in order of their payment timestamp. An invoice's open balance is its total minus what this policy required earlier receipts to allocate to it.
- **Amount tolerance:** 0 minor units, so amounts must be exact.
- **Issue types that may occur:** payment_allocation. The books may also be clean.

## Public records

### ledger.csv

| row_id | timestamp | account | debit_minor | credit_minor | currency | entity_id | invoice_id | payment_id |
|---|---|---|---|---|---|---|---|---|
| L21 | 2026-10-05T10:00:00+05:00 | accounts_receivable | 250000 | 0 | KZT | E4 | I7 |  |
| L08 | 2026-10-05T10:00:00+05:00 | revenue | 0 | 250000 | KZT | E4 | I7 |  |
| L15 | 2026-10-07T11:30:00+05:00 | accounts_receivable | 250000 | 0 | KZT | E8 | I3 |  |
| L03 | 2026-10-07T11:30:00+05:00 | revenue | 0 | 250000 | KZT | E8 | I3 |  |
| L19 | 2026-10-14T09:15:00+05:00 | bank | 260000 | 0 | KZT | E4 |  | P9 |
| L11 | 2026-10-14T09:15:00+05:00 | accounts_receivable | 0 | 150000 | KZT | E4 | I7 | P9 |
| L13 | 2026-10-14T09:15:00+05:00 | unapplied_receipts | 0 | 110000 | KZT | E4 |  | P9 |
| L05 | 2026-10-16T14:00:00+05:00 | bank | 150000 | 0 | KZT | E8 |  | P2 |
| L17 | 2026-10-16T14:00:00+05:00 | accounts_receivable | 0 | 150000 | KZT | E8 | I3 | P2 |
| L09 | 2026-10-23T16:45:00+05:00 | bank | 120000 | 0 | KZT | E8 |  | P5 |
| L23 | 2026-10-23T16:45:00+05:00 | accounts_receivable | 0 | 100000 | KZT | E8 | I3 | P5 |
| L06 | 2026-10-23T16:45:00+05:00 | unapplied_receipts | 0 | 20000 | KZT | E8 |  | P5 |

### invoices.jsonl

```json
{"doc_id": "D31", "invoice_id": "I7", "entity_id": "E4", "issued_at": "2026-10-05T10:00:00+05:00", "due_at": "2026-10-20T18:00:00+05:00", "currency": "KZT", "total_minor": 250000, "line_items": [{"description": "Robotics workshop session", "quantity": 5, "unit_price_minor": 50000, "amount_minor": 250000}]}
{"doc_id": "D12", "invoice_id": "I3", "entity_id": "E8", "issued_at": "2026-10-07T11:30:00+05:00", "due_at": "2026-10-28T18:00:00+05:00", "currency": "KZT", "total_minor": 250000, "line_items": [{"description": "Data-literacy course seat", "quantity": 2, "unit_price_minor": 125000, "amount_minor": 250000}]}
```

### payments.jsonl

```json
{"doc_id": "D44", "payment_id": "P9", "timestamp": "2026-10-14T09:15:00+05:00", "currency": "KZT", "amount_minor": 260000, "invoice_refs": ["I7"]}
{"doc_id": "D27", "payment_id": "P2", "timestamp": "2026-10-16T14:00:00+05:00", "currency": "KZT", "amount_minor": 150000, "invoice_refs": ["I3"]}
{"doc_id": "D36", "payment_id": "P5", "timestamp": "2026-10-23T16:45:00+05:00", "currency": "KZT", "amount_minor": 120000, "invoice_refs": ["I3"]}
```

### fx.csv

| date | source_currency | target_currency | rate |
|---|---|---|---|
| 2026-10-14 | USD | KZT | 512.40 |
| 2026-10-16 | USD | KZT | 513.85 |
| 2026-10-23 | USD | KZT | 515.10 |

## What a finding must contain

For `payment_allocation`: A proven receipt was allocated to its referenced invoice for less than the policy requires.

- `affected_ids`: The invoice_id and the payment_id, in any order.
- `claimed_amount_minor`: Required allocation minus recorded allocation for that invoice and payment, as a positive integer in minor units of the invoice currency.
- `evidence_ids`: The invoice doc_id, the payment doc_id and the row_id of every accounts_receivable row that carries both that invoice_id and that payment_id. Further record ids may be added.

A finding counts only if the type, the affected ids, the amount, the currency and the complete evidence
are all right. A correct amount with missing evidence is a false claim, not a near miss.

## Solve it

On paper: decide which findings, if any, the records support, and write them in this shape.
Submit an empty `findings` list if you believe the books are clean.

```json
{
  "episode_id": "ep-4c1f09",
  "findings": [
    {
      "type": "<one of manifest.issue_types>",
      "affected_ids": [
        "<id>",
        "<id>"
      ],
      "claimed_amount_minor": 0,
      "currency": "KZT",
      "evidence_ids": [
        "<doc_id or row_id>"
      ],
      "explanation": "<short supporting text>"
    }
  ]
}
```

Through the tools, requesting records yourself and being checked only when you submit:

```
uv run python -m genesis_audit play --episode teaching_b
```

If you believe a decisive fact is missing from the public records, say which one. A fixture that
cannot be decided from its public records is broken and gets repaired; a guess is not rewarded.
