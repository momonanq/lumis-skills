"""Acceptance tests for the `audit-chain` task. The agent never sees this file: scripts/agent_bench.py copies it in
after the agent has finished. Pure Python — no SQLAlchemy, no database — so a missing driver can never be mistaken
for a failure of the agent."""
from __future__ import annotations

import hashlib

import audit

ORG = "8b0a9b0c-0000-4000-8000-000000000001"
USER = "8b0a9b0c-0000-4000-8000-000000000002"
TS = "2026-09-23T11:02:07+00:00"
RESOURCE = "verification:9b1d"
ACTION = "VERIFICATION_COMPLETED"


def declared_hash(prev: str, org: str, user: str | None, action: str, resource: str, ts: str) -> str:
    """The payload exactly as ARCHITECTURE.md declares it: pipe-separated, 'SYSTEM' for a null user."""
    payload = f"{prev}|{org}|{user or 'SYSTEM'}|{action}|{resource}|{ts}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def good_chain() -> list[dict]:
    chain: list[dict] = []
    audit.append_entry(chain, ORG, USER, "VERIFICATION_CREATED", "verification:9b1d", "2026-09-23T11:00:00+00:00")
    audit.append_entry(chain, ORG, None, "PASSPORT_UPLOADED", "verification:9b1d", "2026-09-23T11:01:00+00:00")
    audit.append_entry(chain, ORG, USER, ACTION, RESOURCE, TS)
    audit.append_entry(chain, ORG, USER, "REPORT_DOWNLOADED", "report:9b1d", "2026-09-23T11:03:00+00:00")
    return chain


def test_hash_matches_the_declared_payload():
    prev = "0" * 64
    assert audit.compute_hash(prev, ORG, USER, ACTION, RESOURCE, TS) == declared_hash(prev, ORG, USER, ACTION, RESOURCE, TS)


def test_null_user_is_the_literal_SYSTEM():
    prev = "a" * 64
    assert audit.compute_hash(prev, ORG, None, ACTION, RESOURCE, TS) == audit.compute_hash(prev, ORG, "SYSTEM", ACTION, RESOURCE, TS)


def test_hash_is_64_lowercase_hex():
    value = audit.compute_hash("0" * 64, ORG, USER, ACTION, RESOURCE, TS)
    assert len(value) == 64 and value == value.lower()
    int(value, 16)  # raises if it is not hexadecimal


def test_the_first_entry_links_to_the_genesis_hash():
    chain = good_chain()
    assert chain[0]["prev_hash"] == audit.GENESIS_HASH


def test_each_entry_links_to_its_predecessor():
    chain = good_chain()
    for earlier, later in zip(chain, chain[1:]):
        assert later["prev_hash"] == earlier["log_hash"]


def test_verify_chain_accepts_a_good_chain():
    assert audit.verify_chain(good_chain()) == (True, None)


def test_verify_chain_names_the_first_broken_link():
    chain = good_chain()
    chain[2] = {**chain[2], "action": "APPROVED"}
    ok, index = audit.verify_chain(chain)
    assert ok is False and index == 2
