# Webhook deliveries that fail

Webhook deliveries to a manager's system sometimes fail. Add exponential-backoff retries with a cap, in a new module
`backend/webhooks.py`.

## What "done" means

`backend/webhooks.py` exposes:

- `MAX_ATTEMPTS: int` and `CAP_SECONDS: int`.
- `delays(n) -> list[int]` — the first `n` retry delays in seconds: base-2 exponential starting at 1, never above
  `CAP_SECONDS`.
- `jittered(delay, rand) -> float` — the delay with jitter applied. `rand` is a callable returning a float in
  `[0, 1)`. The result is never negative and never larger than `delay`.
- `deliver(send) -> int` — calls `send()` until it succeeds, at most `MAX_ATTEMPTS` times, and returns how many
  calls it made. `send()` returns an HTTP status code as an `int`. 2xx is success. A 4xx is the caller's own fault
  and is not retried. Anything else is retried. `deliver` must not actually sleep in the tests: take the sleep
  function as a keyword argument `sleep` defaulting to `time.sleep`.

Plain Python; no dependency, no network.

## Why this task is in the bench

This task is here to be unremarkable. Any competent agent writes exponential backoff from general knowledge, and
the project's documents add almost nothing. If the two arms come out the same here — or the arm with the
specification comes out slower, because it read a specification that did not help — that is the result, and it is
published next to the others.
