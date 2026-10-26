"""The acceptance tests under `tasks/*/tests/` are not tests of this repository.

They are the hidden half of a bench task: they import modules that only exist inside a prepared run folder
(`backend/audit.py`, `backend/scoring.py`, `backend/webhooks.py`), which is where `scripts/agent_bench.py` copies
them and runs them. Collected here they would fail on import and turn the repository's own suite red for a reason
that has nothing to do with the repository.
"""
collect_ignore_glob = ["tasks/*/tests/*"]
