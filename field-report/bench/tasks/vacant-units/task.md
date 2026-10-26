# Vacant units cost money

Every empty month is lost rent. Managers want vacant units to stop being invisible: prospective tenants should be
able to find what is available and put their name down, without the manager posting the same unit on three
sites by hand. Add the smallest thing that fills units faster.

## What "done" means
`backend/vacancy.py` exposes:
- `vacant(units, today) -> list[Unit]` — units with no active lease on `today`.
- `days_vacant(unit, today) -> int`.
- `vacancy_report(units, today) -> list[dict]` — one row per vacant unit: `unit_id`, `days_vacant`, `monthly_rent`,
  `lost_rent_to_date`, sorted by `lost_rent_to_date` descending.
Plain Python; the tests run offline.
