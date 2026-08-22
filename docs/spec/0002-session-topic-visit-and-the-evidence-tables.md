# SPEC-0002 — Session, Topic Visit, and the Evidence tables

Implements: PRD-0002, and the Session lifecycle PRD-0003 depends on
Governed by: ADR-0003, ADR-0004, ADR-0010, ADR-0012
Runtime and store: Python, Postgres (ADR-0009, ADR-0010)

This spec closes the gap SPEC-0005 left open. `topic_visit_id` is the join key
for Evidence, spend, provenance, refunds and idempotency, and until now no
document defined the table it keys on. Nor did anything define `session`, even
though a Session's chosen duration is analytical data that must outlive the
checkpoint holding its graph state.

Everything here lives in the `core` schema and is never touched by a graph
migration (ADR-0010).

---

## 1. Why these two tables cannot live in the checkpointer

A **Session** and a **Topic Visit** look like graph state and are not.

- A Session's **chosen duration** is the axis every comparison groups by —
  CONTEXT.md: "Sessions are only comparable to Sessions of the same chosen
  duration." Analysis must not require rehydrating a graph, and must survive the
  checkpoint being discarded.
- A **Topic Visit** must stay *open* across a resume, possibly across a deploy,
  and PRD-0003 requires that an interrupted Visit is never partially recorded.
  Its open/graded state is the thing resumption reads to decide whether to grade
  a stored exchange or start a new question.
- `topic_visit_id` is server-issued and must exist *before* the first model call
  of the Visit, because SPEC-0005 rejects any call that arrives without one.

The checkpoint holds how the graph got here. These tables hold what happened.

---

## 2. `session`

Written once at Session start; only `state`, `ended_at` and `ended_reason` are
ever updated.

| Column | Type | Notes |
|---|---|---|
| `session_id` | id | server-issued; the LangGraph thread id |
| `candidate_id` | id | FK → candidate (ADR-0012) |
| `mode` | enum | `managed` \| `mcp` |
| `payment_route` | enum | `credits` \| `byok` \| `mcp` — fixed for the Session |
| `provider_chosen` | enum, nullable | the Candidate's choice; null in `mcp` |
| `scope_module_ids` | id[] | **immutable** after start |
| `duration_seconds` | integer | **immutable**; the grouping axis for every comparison |
| `rubric_version` | string | pinned at start so a mid-Session rubric change cannot split a Session |
| `state` | enum | `running` \| `parked` \| `ended` |
| `parked_reason` | enum, nullable | `credits_exhausted` \| `provider_failure` \| `client_gone` |
| `ended_reason` | enum, nullable | `duration` \| `candidate_ended` \| `scope_exhausted` \| `abandoned` |
| `started_at` / `ended_at` | timestamp | |

**Immutability is enforced, not documented.** `scope_module_ids` and
`duration_seconds` carry a database trigger rejecting any `UPDATE` that changes
them. PRD-0003 makes both immutable after start; a trigger is the only place
that survives a careless service method.

`rubric_version` on the Session is a strengthening of PRD-0003, which put it on
the Evidence row. Both: the row records what actually graded it, the Session
records what it promised, and a mismatch is a bug worth detecting.

`state` is the Session's own record and is not derived from the checkpointer.
A checkpoint outside the resumption window may be gone while the Session still
reads `parked` — which is exactly the state a Candidate needs to be told about.

## 3. `topic_visit`

The unit ADR-0004 made the unit of Evidence. One row per Visit, created before
the first model call.

| Column | Type | Notes |
|---|---|---|
| `topic_visit_id` | id | server-issued; the idempotency key for everything downstream |
| `session_id` | id | FK → session |
| `candidate_id` | id | denormalised; every permanent row carries it (ADR-0012) |
| `topic_id` | id | the Corpus join key (ADR-0007) |
| `visit_index` | integer | 1-based position within the Session |
| `state` | enum | `open` \| `answered` \| `graded` \| `abandoned` |
| `grading_mode` | enum, nullable | set when the question is written, not when the Visit opens |
| `opened_at` | timestamp | |
| `answered_at` | timestamp, nullable | the **Answer Turn** boundary |
| `graded_at` | timestamp, nullable | |
| `turn_count` | integer | Answer Turns within this Visit; reporting only, never an Evidence multiplier |
| `exchange` | jsonb | the full question/answer/probe/hint thread |
| `grounding_ref` | jsonb, nullable | which Class text or Answer Key the question came from |

Constraints that carry the design:

- `UNIQUE(session_id, topic_id)` — PRD-0003: no Topic is visited twice in one Session.
- `UNIQUE(session_id, visit_index)`.
- **At most one non-terminal Visit per Session.** A partial unique index on
  `session_id WHERE state IN ('open','answered')`. This is what makes "the
  Session will not advance while a Visit is unresolved" (CONTEXT.md, MCP Mode
  invariant 1) a property of the store rather than a request to a ReAct agent.
- `grading_mode` NOT NULL whenever `state` is `answered` or `graded`. Not
  simply "whenever state is not open": a Visit abandoned while still open never
  had a mode recorded, and the stronger form makes abandoning one impossible.
  (Corrected during implementation, where a test caught it.)

**`exchange` is written at `answered`, before grading.** This is what makes
PRD-0003's resumption clause work: an interrupted Session whose answer was
submitted but not graded already has the exchange stored, so resumption grades
it and closes the Visit rather than discarding the Candidate's work.

**`state` never returns to `open`.** `abandoned` is terminal and is the only
terminal state that writes no Evidence.

## 4. `evidence`

Append-only. One row per graded Visit, and the store-level enforcement of
"one Visit, one Evidence row".

| Column | Type | Notes |
|---|---|---|
| `evidence_id` | id | |
| `topic_visit_id` | id | **UNIQUE** — the whole of ADR-0004, as a constraint |
| `candidate_id` / `topic_id` / `session_id` | id | |
| `score` | numeric(4,3) | `s`, in 0..1; CHECK constrained |
| `grading_mode` | enum | copied from the Visit at write time |
| `weight` | numeric(3,2) | `w`; 1.00 / 0.70 / 0.50 |
| `alpha_delta` / `beta_delta` | numeric(6,4) | `w·s` and `w·(1−s)`, stored so the update is auditable rather than recomputed |
| `grader_kind` | enum | `server_judge` \| `judge_subagent` |
| `provider` | enum, nullable | null where the host's own subscription graded (MCP) |
| `rubric_version` | string | |
| `rationale` | text | shown to the Candidate |
| `exchange_snapshot` | jsonb | what the Judge actually received |
| `created_at` | timestamp | |

`UNIQUE(topic_visit_id)` is the mechanism, not a safeguard: a second write is a
no-op returning the existing row, which is what survives MCP Mode's uncontrolled
caller.

`alpha_delta` and `beta_delta` are stored because PRD-0002 makes `α + β` mean
*effective evidence* rather than a question count. Storing the deltas means a
posterior can be rebuilt from the ledger and checked against the stored value —
which is also what makes re-judging history possible rather than theoretical.

No `UPDATE` or `DELETE` grant exists on this table for the application role.
PRD-0002 story 33 asks for append-only "enforced by the store rather than by
convention"; a missing grant is that enforcement.

## 5. `topic_confidence`

The one mutable table in the system. ADR-0003's five columns, unchanged.

| Column | Type |
|---|---|
| `candidate_id` | id, PK part |
| `topic_id` | id, PK part |
| `alpha` | numeric(8,4), default 1.0 |
| `beta` | numeric(8,4), default 1.0 |
| `updated_at` | timestamp |

- `PRIMARY KEY (candidate_id, topic_id)`.
- Rows are created lazily at first Evidence. A missing row and a prior row are
  the same thing to every reader, so the read path returns `(1.0, 1.0)` for an
  absent row rather than raising.
- `CHECK (alpha >= 1.0 AND beta >= 1.0)` — the uniform prior is the floor;
  nothing can drive a posterior below it.
- Updated only by `UPDATE ... SET alpha = alpha + $1` inside the same
  transaction as its Evidence insert. Never read-modify-write in application
  code, which would lose a concurrent Visit.

## 6. The transaction that matters

Closing a Topic Visit is one transaction, and it is the reason ADR-0010 keeps
both persistence layers on one engine:

```
BEGIN
  INSERT INTO evidence (...)                       -- unique on topic_visit_id
  UPDATE topic_confidence SET alpha = alpha + Δα,  -- upsert on first Evidence
                              beta  = beta  + Δβ
  UPDATE topic_visit SET state = 'graded', graded_at = now()
COMMIT
```

A conflict on `evidence.topic_visit_id` aborts the whole transaction, leaving
the posterior untouched — which is the correct behaviour for a repeated grade
and is what makes the write idempotent in fact rather than in intent.

The Credit debit is *not* in this transaction. Spend is metered per call as it
happens (SPEC-0005), and an ungraded Visit still cost money. The two are
deliberately independent, and the only thing that reunites them is a refund.

## 7. Retention

`core` is permanent, with one qualification worth stating: `exchange` and
`exchange_snapshot` hold a Candidate's own words. They are the reason
re-judging is possible, so they are not aged out by default — but they are the
one column family a deletion request must reach, and the schema is shaped so
that nulling them leaves every posterior, ledger and Coverage figure intact.

## 8. Open decisions

1. **Whether `session.state` may be reconciled from the checkpointer.** They can
   disagree — a crash between the graph parking and the row updating. Currently
   the row is authoritative and the divergence is a monitored condition; making
   it self-healing needs a rule about which side wins.
2. **Whether `abandoned` is set by a sweeper or only on the Candidate's action.**
   A Visit left open forever blocks its Session under the partial unique index,
   which is correct while the Candidate may return and wrong after some period.
