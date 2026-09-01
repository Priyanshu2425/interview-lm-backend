# ISSUE-0048 — A Candidate says who they are

Status: resolved — backend landed; the surface gate is a frontend-repo slice
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


## What landed

The four columns are on `core.candidate` in `db/schema.py`, defaulted so every
row that predates the form reads as *unanswered*, and the comment above the
table says outright that `target_role`, `experience_level` and `goal` are read by
nothing yet — the thing the ticket asked to be stated rather than discovered.

`_CORE_ADDED_COLUMNS` gained the four entries. The ticket says `create_core` has
no column migrator; ISSUE-0039 had already added one by the time this ran, so the
existing tuple was extended rather than a second migrator written. It looks
before it ALTERs, so a second boot over a populated database changes neither the
catalogue nor a Candidate's answers, and there is a test that snapshots both.

`GET /v1/candidates/me` and `PATCH /v1/candidates/me` sit beside the rest of the
family in `routes/v1/candidate.py` and take no id from anybody. The reading is
the three fields the ticket named and no more: the answers are collected and not
served, because a value on the wire is a value something starts depending on.
`onboarded` is derived from `onboarded_at` rather than stored beside it.

`AsyncSessionStore.ensure_candidate` is `async` and executes. The one caller that
already awaited it — `service/graph/async_adapters.py`, which passed the returned
string to `_run_async` — becomes correct as a side effect.

## Deviations, and why

- **PATCH leaves omitted fields alone.** The ticket says a second PATCH "updates
  the fields"; written literally that lets a surface correcting a display name
  erase a goal it never asked about. `exclude_unset` keeps the verb honest.
- **A body carrying an unknown field is refused, not ignored.** `extra: "forbid"`
  on `OnboardingIn`. "No route accepts a `candidate_id` in a body" is stronger as
  a 422 than as a silent drop — a surface that sent one and got a 200 would go on
  believing the field meant something.
- **The stamp is `COALESCE(onboarded_at, now())` in the UPDATE**, not a read
  followed by a conditional write. Two PATCHes arriving together would both read
  null and both stamp, and the later one would move a date whose only job is to
  say when the person actually finished.
- **GET does not mint the row.** A real token has already been through
  `IdentityStore.resolve`, so a GET that inserted would exist for a case that
  cannot happen — and an absent row and an unanswered form are the same reading
  either way.

## Left for the surface

All of it, and it is a separate repository. `RequireSession` needs its second
gate: on first authenticated load read `/v1/candidates/me`, and if `onboarded` is
false route to the form, PATCH, continue. No `candidate_id` is involved anywhere,
so `shared/stores/session.ts` keeps its promise unchanged.

## Suite

`13` new tests in `tests/test_candidate_onboarding.py`; the two routes added to
`GUARDED` in `tests/test_api_authentication.py`.

Run on a checkout with no `data/` material, where 38 notebook tests fail and 169
skip for want of it, before this slice and identically after: **727 passed, 38
failed, 169 skipped** against a baseline of 712/38/169 — the same 38, and every
one of them a fixture reading `data/markdown/aiml`, which this repository does
not ship (ADR: there is no Corpus on disk). ISSUE-0039 recorded 911/8 on a
machine that had that material locally.
