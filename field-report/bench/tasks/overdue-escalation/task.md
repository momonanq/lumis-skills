# Rent 60 days late

When rent is more than 60 days late, managers spend a week assembling paperwork to get the tenant out. They want the
system to take this off their hands: the moment a tenant crosses 60 days, everything needed to start eviction
should be ready. Add the smallest thing that does this.

## What "done" means
`backend/escalation.py` exposes:
- `stage(days_late) -> str` — `"ok"`, `"reminder"` (1–29), `"warning"` (30–59), `"handoff"` (60+).
- `next_action(days_late) -> str` — a one-line instruction for the manager at that stage.
- `handoff_packet(tenant, ledger) -> dict` — what a manager forwards to whoever handles the case next: tenant id,
  amount owed, days late, the payment ledger as a list of entries. No other keys are required.
Plain Python; the tests run offline.
