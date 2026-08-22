# One Postgres instance, two schemas with opposite lifecycles

Both persistence layers live in one managed Postgres instance, separated by
schema, not by engine:

- `graph` — the LangGraph checkpointer's tables. Disposable outside the
  resumption window.
- `core` — **Topic Confidence**, **Evidence**, the Credit and Pool ledgers,
  `call_record`, `session`, `topic_visit`. Permanent.

## Why not two databases

ADR-0003 asked for opposite *lifecycles*, and that was read here as a demand for
opposite *engines*. It is not. Splitting the engines costs the one thing the
design cannot give up: **a Topic Visit's writes must be one transaction.**

SPEC-0005 requires a `call_record` and its `credit_ledger` debit to commit
together, and PRD-0002 requires the **Evidence** write and the **Topic
Confidence** update to be a single atomic act. Across two engines those become a
distributed transaction or a reconciliation job, and a reconciliation job is
precisely the shape PRD-0005 rejected when it chose pre-funding over
after-the-fact repair.

## Why not SQLite, or a Redis checkpointer

SQLite expresses the partial unique indexes the invariants rest on, and is a
defensible starting point — but the checkpointer and `core` would then be one
file with one lifecycle, which is the mistake ADR-0003 exists to prevent. Redis
for checkpoints splits the transaction for no gain, since checkpoint writes are
not the hot path.

## What the separation actually buys

- A graph schema migration may drop and recreate `graph` outside the resumption
  window and can never touch `core`. This is enforced by the migration tool
  owning only one schema, and by the application role holding no DDL on `core`.
- `core` is readable without instantiating a graph — the requirement in ADR-0003
  that made a framework KV namespace unacceptable.
- Idempotency stays where SPEC-0005 put it: in partial unique constraints on
  `call_id`, `refunded_visit_id`, `payment_ref` and `topic_visit_id`, which
  Postgres expresses directly.

## Consequence

One engine to operate, one backup, one point of failure. The lifecycle
guarantee becomes a property of tooling and permissions rather than of physical
separation, so it must be tested: a migration test asserts that applying every
graph migration to a database holding `core` rows leaves those rows byte-identical.
