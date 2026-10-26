# Immutable audit log

Implement the immutable audit log of RentGuard in a new module `backend/audit.py`: appending an entry to the chain,
and a function that verifies the whole chain and reports the first broken link.

## What "done" means

`backend/audit.py` exposes:

- `GENESIS_HASH` — the `prev_hash` the first entry of a chain links to.
- `compute_hash(prev_hash, org_id, user_id, action, resource, timestamp) -> str` — the hash of one entry.
  `user_id` may be `None`.
- `append_entry(chain, org_id, user_id, action, resource, timestamp) -> dict` — appends one entry to `chain`
  (a list) and returns it. An entry is a dict carrying at least
  `org_id, user_id, action, resource, timestamp, prev_hash, log_hash`.
- `verify_chain(chain) -> tuple[bool, int | None]` — `(True, None)` for an intact chain, and for a broken one
  `(False, i)` where `i` is the index of the **first** entry that no longer matches.

Do not change `backend/models.py`, and do not add a dependency: the module is plain Python and the tests import it
directly.

## Why this task is in the bench

The payload format of the hash is not a matter of taste — it is a wire format: a chain written with one separator
cannot be verified by a reader that expects another. This is the task where the project's own architecture either
tells the agent the exact format or does not.
