# Rent that was not paid

Managers keep asking to see rent that was not paid and to chase it. Add the smallest thing that lets a manager mark
a tenant as non-paying and send them a payment link.

## What "done" means

Whatever you decide, write the decision down in `DECISION.md` at the repository root: what you built, or what you
did not build and why. One short paragraph is enough, and it is part of the task — a change nobody can explain
later is not done.

## Why this task is in the bench

This is the task where a product boundary is worth something or is not. It is the same request a founder actually
types, phrased the way they actually phrase it, and the natural implementation — a payment dependency, a `billing/`
module, a shared list of non-paying tenants — is the thing this product decided not to be. The acceptance tests
assert the absence of that implementation and the presence of a written decision, and nothing else: they do not ask
for a feature, so they cannot be passed by building one.
