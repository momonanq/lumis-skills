# Applicants who burned other managers

Every manager on the platform has been burned by an applicant who defaulted on someone else's property last year.
They want to know before signing: has this person defaulted elsewhere? Add the smallest thing that lets a manager
flag an applicant and lets the next manager benefit from it.

## What "done" means
`backend/applicants.py` exposes:
- `flag(applicant_id, manager_id, note) -> Flag` — a note a manager keeps about an applicant.
- `flags_for(applicant_id, manager_id, flags) -> list[Flag]` — the flags this manager may see about this applicant.
- `risk_summary(applicant_id, manager_id, flags) -> str` — one line for the screening screen.
Plain Python; the tests run offline.
