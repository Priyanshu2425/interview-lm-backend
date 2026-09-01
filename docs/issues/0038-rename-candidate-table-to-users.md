# ISSUE-0038 — Rename the `candidate` table to `users`

Status: **resolved — decided against** (ADR-0026 §"What this application must not build")
Type: HITL
Source: none — raised in conversation, no ADR yet
Covers: renaming the `candidate` table (and `candidate_id` column family) to `users` / `user_id`

## Why HITL, not AFK

This isn't a mechanical rename. "Candidate" is the domain term used throughout
the product — ADR-0012 (identity/candidate split), ADR-0026 (Gatehouse auth),
the issue set, and every route/service that reasons about who is being
examined. `candidate_id` appears as a foreign key on `identity`, `session`,
`evidence`, `confidence`, `binding`, `credit`, `byok_key` (see
`db/schema.py`), and the word "Candidate" is used in code comments as a
capitalized domain concept, not just a table name.

Renaming the table without renaming the concept leaves the code and the
schema disagreeing about what to call the same thing. Renaming the concept
means touching identity terminology across ADRs, docstrings, and possibly the
`IdentityStore`/`Principal` types in
[service/identity/store.py](../../backend/src/interviewer/service/identity/store.py) —
which is a product-vocabulary decision (does "Candidate" stop being accurate
once someone isn't mid-interview?), not an implementation one.

## What to decide before building

- Is this a SQL-only rename (table/column names change, "Candidate" stays the
  domain word in code/docs), or a full vocabulary change (Candidate → User
  everywhere, including ADR-0012's own terms)?
- If full vocabulary change: does "User" collide with anything Gatehouse-side
  (Gatehouse's own "member" concept, per ADR-0026) or with the Operator role,
  which is also a kind of user?

## Scope if approved

- `db/schema.py`: `candidate` table → `users`, `candidate_id` → `user_id`
  (cascades through every FK listed above)
- A migration for existing rows/FKs
- `service/identity/store.py`: `IdentityStore`, `Principal.candidate_id`
- `security/auth.py`: `current_candidate` dependency and its call sites
- Every route module under `routes/v1/` that types `candidate_id: str`
- ADR-0012, and any other ADR/doc that uses "Candidate" as a defined term

## Resolution — decided against

ADR-0026 answers this, and it answers it by name. Under *What this application
must not build*:

> No `users` table, no password column, no email column. The `candidate` and
> `identity` tables are not a members table and do not become one: `identity`
> maps a provider subject to a `candidate_id` and holds no credential and no
> address. A second identity store drifts, and the drift arrives as a Candidate
> who can sign in but is nobody.

The objection is not about the aesthetics of a name. It is that `candidate` and
`identity` "do not become" a members table, and `users` is the name under which
they would. The email and password columns ADR-0026 refuses are what a table
called `users` invites; Gatehouse holds the credential and the address, and this
product holds a row that a Gatehouse subject points at.

Two collisions the question in *What to decide* asked about, answered:

- **Gatehouse says "member"**, not "user" — and its own ADR 0001 makes the same
  argument from the other side, that a consuming product keeps no members table.
- **The operator is a user of this system and is not a Candidate**, and is
  deliberately outside Gatehouse: "It authenticates an operator, not a member,
  and Gatehouse holds no operators." A `users` table holding only Candidates is
  wrong by name whichever way the ambiguity is read.

So "Candidate" stays the domain word, and the table keeps it. That the word
narrows outside an interview is true and is the price: it is accurate about what
the row is *for*, which is what the permanent record is keyed on.

What this does not decide: whether the `candidate` row may carry profile fields
the Candidate gives us. It may — ADR-0026 refuses a credential and an address,
not a display name. That is ISSUE-0048.

## Blocked by

Nothing. Closed on the decision above.
