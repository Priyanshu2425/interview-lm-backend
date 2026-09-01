# ISSUE-0039 — The schema breaks and is rebuilt

Status: resolved — built and proven on local; prod migration is a separate plan
Type: **HITL**
Source: SPEC-0007 (to be written); amends ADR-0004
Covers: the plan, the transcript, and Evidence keyed on the Topic within a Session

## What to build

The Session stops being a sequence of independently graded Topic Visits and becomes
a **plan** executed against a **transcript**, graded once at the end. That is a
different set of tables, and `create_all` cannot get there from here — it never
ALTERs. This slice is the break.

New:

- **`session_plan`** — one row per Session. `budget_questions`, `suggested_seconds`,
  `chosen_seconds`, `breadth` (`full | compressed`), `planner_provider`,
  `planner_fallback`, `planned_at`.
- **`plan_item`** — one row per planned question. `item_order`,
  `topic_ids ARRAY NOT NULL` (1–3), `focus`, `state` (`planned | asked | unreached`),
  `UNIQUE(session_id, item_order)`. `trg_plan_item_fixed` rejects UPDATE of
  `topic_ids`, `item_order` or `focus` — fixedness is a constraint, not a convention,
  mirroring `trg_session_immutable`.
- **`message`** — the transcript. `seq`, `role` (`interviewer | candidate`), `kind`
  (`question | answer | probe | hint`), `topic_ids`, `text`, `topic_visit_id`,
  `plan_item_id`, `UNIQUE(session_id, seq)`, append-only trigger copied from
  `APPEND_ONLY_EVIDENCE_TRIGGER`.

Changed:

- **`topic_visit`** keeps its name and its id. That id is the join key for
  `visit_provider_binding` (PK), `call_record`, `credit_ledger` refunds and MCP
  ticket TTLs; renaming it is a large diff with no product value. What changes is
  its meaning — it is the *question*, not the *Topic Visit*. Add `topic_ids ARRAY`
  and `plan_item_id`; keep singular `topic_id` as the owning Topic, because
  `open_topic_ids()` and the refund path need a scalar. Drop
  `uq_visit_session_topic` — a plan may spend two questions on one Topic. Keep
  `uq_visit_one_open_per_session`. Drop the `exchange` JSONB; `message` rows are the
  one writer now. `visit_state` loses `graded`, because grading is no longer a fact
  about a question.
- **`evidence`** — `topic_visit_id` becomes nullable and non-unique; the new key is
  `UNIQUE(session_id, topic_id)`. That constraint *is* ADR-0004, restated: one Beta
  observation per Topic per Session, exactly as before. Add `source_score`
  (nullable) and `truth_score`; `score` stays as the stated combination. Add
  `question_count` for reporting only — it is never a Beta count.

Also fix the asymmetry at `db/engine_async.py:82`, which runs `create_all` without
applying the triggers. Three of them are load-bearing now.

## Why HITL

`INTERVIEW_LM_DATABASE_URL` points at a live deployment. A clean break drops real
Candidate Evidence, and Evidence is append-only precisely because it is not
supposed to be destroyable. This slice does not merge until a human has confirmed in
writing that those rows are disposable.

`scripts/reset_core.py` must refuse to run unless
`INTERVIEWER_ALLOW_DESTRUCTIVE_RESET=1` **and** the DSN host is echoed back on the
command line. A destructive script that is easy to run by accident is the same
defect as no guard at all.

## Confirmation

**2026-09-01 — Priyanshu:** the shared `interview_lm_core` rows are disposable.

Scope of the work taken under that confirmation: the break is built and proven
against **local Postgres only** (`cortex-pg`, pgvector pg16 on :55432). The shared
Neon deployment is not migrated by this slice; it gets a written migration plan
instead, and a dump taken before that plan is executed.

`backend/.env` had `DATABASE_URL` pointing at Neon — the redirection
`.env.example` warns about. It now names the local database, and the Neon DSN
moved to `INTERVIEW_LM_DATABASE_URL`, so reaching production takes a deliberate
opt-in.

## Acceptance criteria

- [x] Written confirmation recorded here that the shared `interview_lm_core` rows are disposable
- [x] `scripts/reset_core.py` refuses without both the env var and the echoed host
- [x] `create_core` on a fresh database produces every new table and trigger
- [x] An UPDATE on `message` is refused; an UPDATE of `plan_item.topic_ids` is refused
- [x] `engine_async` applies the same triggers as `engine`
- [x] Two Evidence rows for one `(session_id, topic_id)` are refused
- [x] The suite passes on a clean database

## Blocked by

Nothing technically. Blocked on the human decision above.


## What landed, and the one deviation

Built additive. ISSUE-0039 as written also *removes* two things — `topic_visit.exchange`
and the `graded` value of `visit_state` — and both removals were deferred to the slice
that replaces their writers.

The reason is this ticket's own last acceptance criterion. `exchange` has 56 references
across 15 files and `graded` 10 across 8; nothing writes `message` until ISSUE-0042 and
nothing grades at the end until ISSUE-0044. Dropping them here would leave the suite red
for four slices, which is the opposite of "the suite passes on a clean database".
Postgres has no `ALTER TYPE … DROP VALUE` either, so `graded` could not have left an
existing enum cleanly in any case. Both columns carry a comment naming the slice that
retires them.

Everything else landed as specified:

- `session_plan`, `plan_item` and `message`, with `trg_plan_item_fixed` and an
  append-only `message` trigger copied from `APPEND_ONLY_EVIDENCE_TRIGGER`.
- `topic_visit` gained `topic_ids` and `plan_item_id`, and lost `uq_visit_session_topic`.
- `evidence.topic_visit_id` is nullable and non-unique; `uq_evidence_session_topic` is
  ADR-0004 now. `source_score`, `truth_score` and `question_count` added, the two
  sub-scores constrained to the unit interval.
- `_migrate_core_columns` and `_migrate_core_constraints` — `create_core` had no column
  migrator at all, which ISSUE-0048 also needs.
- `create_async_tables` applies the triggers. It applied none of them: a database built
  through the async path had every table and not one invariant, in the suite meant to
  prove they held. Fixed via `schema.statements`, because asyncpg prepares every
  statement and rejects a multi-command blob.
- `tests/test_interview_mode_schema.py`, 18 tests. `clean_db` truncates the three new
  tables.

`test_walking_skeleton.py::test_the_same_topic_cannot_be_opened_twice_in_one_session`
asserted the constraint this slice removed. It is now
`test_a_topic_may_be_asked_about_twice_in_one_session` and asserts the new rule.

Suite: 911 passed, 8 skipped.
