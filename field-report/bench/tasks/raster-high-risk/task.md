# A scanned bank statement

A tenant uploaded a scanned bank statement — the PDF has no vector text layer, so `is_vector_pdf` is `False`.
Decide what RentGuard's scoring does with such a statement and implement that decision in a new module
`backend/scoring.py`.

## What "done" means

`backend/scoring.py` exposes:

- `score(*, is_vector_pdf, open_banking_connected, monthly_income, stability_index, rent) -> int` — the risk score
  from 0 (safe) to 100 (dangerous). `monthly_income` and `stability_index` arrive as `Decimal`, `rent` as an `int`.
- `category(score) -> str` — the label that goes into the report next to the number.

Plain Python; no dependency, no database, no call to `backend/models.py`.

## Why this task is in the bench

A number like "how much does a scan cost you" and a label like "which category is that" are decisions somebody has
already made for this product, or decisions the agent is about to invent. This task measures which of the two
happened.
