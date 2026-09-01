# ISSUE-0048 — A Candidate says who they are

Status: open
Type: AFK
Source: ADR-0026 (what may be stored); ISSUE-0038 (the table keeps its name)
Covers: the first-login step that is currently missing entirely

## What to build

A Candidate signs in through Gatehouse and is immediately examinable. The first
verified `(issuer, subject)` mints a `candidate` row and an `identity` row inside
`current_candidate` and nothing is ever asked. `candidate.display_name` exists,
has existed since the table did, and **is never written**: the only writer,
`ensure_candidate(candidate_id, name=None)`, is called without a name from
`service/graph/runner.py`.

So there is no moment at which this product learns anything about the person
using it, and no way for the surface to know it is looking at a new one.

## What may be stored, and what may not

ADR-0026 draws this line and it is not reopened here:

> No `users` table, no password column, no email column.

The credential and the address are Gatehouse's. The token carries `sub`, `sid`
and `iss` and no email claim, so mirroring one would mean a userinfo call and a
copy that goes stale the moment it is changed upstream. What ADR-0026 refuses is
a second identity store — not a Candidate telling us what they are preparing for.

## Columns

On `core.candidate`, all defaulted so an existing row reads as unanswered rather
than unknown:

- `onboarded_at timestamptz` — null means never completed. A timestamp rather
  than a boolean because the permanent record should say *when*, as the rest of
  `core` does. This is the flag the surface gates on.
- `target_role text NOT NULL DEFAULT ''`
- `experience_level text NOT NULL DEFAULT ''` — the form's own vocabulary. No
  enum until something reads it.
- `goal text NOT NULL DEFAULT ''` — free text.

`display_name` already exists and needs no migration.

Nothing reads the last three yet. They are collected because the form is the only
moment a person will answer, and the calibration that would consume them is later
work — which is worth stating rather than leaving to be discovered as dead
columns.

**`create_core` has no column migrator.** `_migrate_added_columns` in
`db/engine.py` is `content`-only; `create_core` is `create_all` plus two
triggers, and `create_all` alters nothing that exists. A `_CORE_ADDED_COLUMNS`
tuple and a `_migrate_core_columns` mirroring the content one have to land with
this, or the columns exist on a fresh database and nowhere else.

## Routes

Beside the existing `/candidates/me/…` family, and taking no id from the caller —
the rule `security/auth.py` states in its own docstring:

- `GET /v1/candidates/me` → `{candidate_id, display_name, onboarded}`
- `PATCH /v1/candidates/me` → writes the fields, stamps `onboarded_at` on first
  completion. Idempotent: a second PATCH updates the fields and leaves
  `onboarded_at` where it was.

## Also in this slice

`AsyncSessionStore.ensure_candidate` builds its upsert statement and returns
without executing it, and is a sync `def` on an async store. It is harmless only
because `IdentityStore.resolve` has already inserted the row — which means the
one place that would write a name is a no-op that nothing has noticed.

## Surface

`RequireSession` already gates on a Gatehouse session. A second gate: on first
authenticated load, read `/v1/candidates/me`; if `onboarded` is false, route to
the form, PATCH, continue. The surface deliberately never holds a `candidate_id`
(`shared/stores/session.ts` says so) — every endpoint here is `/me`, so it does
not start.

## Done when

- An unseen token reads `onboarded: false`; a PATCH flips it and sets the name.
- A second PATCH changes the fields and does not move `onboarded_at`.
- No route accepts a `candidate_id` in a body.
- `create_core` run twice against a populated database is a no-op the second time.

## Blocked by

Nothing. ISSUE-0038 settled where these columns live.
