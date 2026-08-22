# ISSUE-0002 — Walking skeleton: one graded Topic Visit

Status: ready-for-agent
Type: AFK
Source: PRD-0002, PRD-0003; ADR-0001, ADR-0003, ADR-0004, ADR-0010, ADR-0011; SPEC-0000, SPEC-0002
Covers: PRD-0003 §34, §35, §36, §37; PRD-0002 §20, §21

## What to build

The thinnest complete path through every layer: a **Session** starts, one
question is asked, a **Candidate** answers, and exactly one **Evidence** row
lands in Postgres.

The **Session** runs as an explicit state machine —
`select_topic → load_dossier → generate_question → interrupt → grade →
update_confidence → decide_next` — with model calls made *inside* nodes rather
than deciding which node runs next. The model is stubbed in this slice; the point
is the machine around it. Everything that must happen exactly once is an edge,
because an edge cannot not run.

`interrupt()` is the **Answer Turn**. The graph parks and the surface resumes it
over an ordinary HTTP request carrying an idempotency key (ADR-0011). The graph
waits for a turn *event* and never reads a particular kind of input.

Persistence is one Postgres instance with two schemas (ADR-0010): `graph` for the
checkpointer, `core` for `session`, `topic_visit`, `evidence` and
`topic_confidence`. Closing a Visit is one transaction, and a conflict on
`evidence.topic_visit_id` aborts the whole thing rather than half-writing.

Topic selection is out of scope: this slice takes the first Topic in curriculum
order. Scope, duration, real grading, cost and provenance all arrive later.

## Acceptance criteria

- [ ] Both Alembic trees apply from empty; `core` and `graph` are separate schemas
- [ ] The application role holds no DDL permission on `core`
- [ ] `scope_module_ids` and `duration_seconds` reject an `UPDATE` that changes them, enforced in the database
- [ ] At most one non-terminal Topic Visit can exist per Session, enforced by constraint rather than application logic
- [ ] A `topic_visit` row exists before the first model call of that Visit
- [ ] A completed Session over one Module produces one Evidence row per completed Topic Visit and no more
- [ ] Writing Evidence twice for the same `topic_visit_id` leaves the posterior unchanged and returns the existing row
- [ ] `POST /v1/sessions` returns a session id, a first question and a `topic_visit_id`
- [ ] `POST /v1/sessions/{id}/turns` returns only when the graph next parks
- [ ] Replaying the same turn request with the same idempotency key returns the original result and writes nothing new
- [ ] A Session interrupted mid-Visit writes no Evidence for that Visit
- [ ] The exchange is stored at the moment the answer is accepted, before grading
- [ ] Screen 02 renders the question, accepts an answer, and shows the result — mobile shows the exchange and nothing else
- [ ] Store tests run against real Postgres, not an in-memory substitute

## Blocked by

- ISSUE-0001 — the loop needs a real dossier to ask a question from
