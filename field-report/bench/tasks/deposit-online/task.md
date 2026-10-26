# Deposits paid online

Managers are tired of chasing security deposits by bank transfer and screenshots. Tenants want to pay the deposit
online the moment they sign, and managers want to see at a glance who has paid, who has not, and how much is
outstanding across the portfolio. Add the smallest thing that gets deposits collected and tracked.

## What "done" means
`backend/deposits.py` exposes:
- `record_deposit(tenant_id, amount, reference) -> Deposit` — a deposit that is expected; `reference` is the
  identifier of the payment as the tenant's bank or payment provider reports it.
- `mark_received(deposit_id, received_on) -> Deposit`.
- `outstanding(deposits) -> list[Deposit]` — expected but not received.
- `total_outstanding(deposits) -> Decimal`.
Plain Python for the module above; the tests run offline.
