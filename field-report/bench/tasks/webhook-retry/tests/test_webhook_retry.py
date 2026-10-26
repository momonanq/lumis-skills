"""Acceptance tests for the `webhook-retry` task. Copied in by scripts/agent_bench.py after the agent finished.

The honest baseline of the bench: everything asserted here is in `task.md`, so a specification cannot help and its
absence cannot hurt. If the two arms differ on this task, the difference is the agent's non-determinism, the cost of
reading documents that did not apply, or a defect in the bench — never «the specification worked»."""
from __future__ import annotations

import webhooks


def test_delays_grow_exponentially():
    assert webhooks.delays(5) == [1, 2, 4, 8, 16]


def test_delay_is_capped():
    assert max(webhooks.delays(12)) <= webhooks.CAP_SECONDS
    assert webhooks.delays(12)[-1] == webhooks.CAP_SECONDS


def test_gives_up_after_max_attempts():
    calls = {"n": 0}

    def always_fails() -> int:
        calls["n"] += 1
        return 503

    assert webhooks.deliver(always_fails, sleep=lambda _s: None) == webhooks.MAX_ATTEMPTS
    assert calls["n"] == webhooks.MAX_ATTEMPTS


def test_stops_on_the_first_success():
    calls = {"n": 0}

    def succeeds_on_the_second() -> int:
        calls["n"] += 1
        return 200 if calls["n"] >= 2 else 500

    assert webhooks.deliver(succeeds_on_the_second, sleep=lambda _s: None) == 2


def test_a_4xx_is_not_retried():
    calls = {"n": 0}

    def rejected() -> int:
        calls["n"] += 1
        return 400

    assert webhooks.deliver(rejected, sleep=lambda _s: None) == 1


def test_jitter_stays_within_the_delay():
    for value in (0.0, 0.25, 0.5, 0.999):
        for delay in webhooks.delays(5):
            assert 0.0 <= webhooks.jittered(delay, lambda: value) <= delay
