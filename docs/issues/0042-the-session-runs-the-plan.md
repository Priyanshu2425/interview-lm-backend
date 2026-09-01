# ISSUE-0042 — The Session runs the plan

Status: resolved
Type: AFK
Source: SPEC-0007 §7–8; amends ADR-0001
Covers: the loop executes planned items, writes a transcript, and grades nothing

> **Paths in this ticket** were written against `api/`, which is now `routes/v1/`.
> Every router is mounted under `/v1`, the Corpus endpoints are served under
> `skills/`, and the session path parameter is `{session_id}`. Corrected in place;
> the tree is the authority.

## What to build

The graph becomes:

    START -> build_plan -> next_planned_item -> load_dossiers -> generate_question
          -> answer_turn -> interviewer_move  ^(probe/hint)
          -> record_exchange -> decide_next   -> next_planned_item | grade_session -> END

- `select_topic` becomes `next_planned_item`: takes the next `planned` item and opens
  one `topic_visit` carrying its `topic_ids` and `plan_item_id`. The provider-binding
  block moves **verbatim** — metering is not part of this change.
- `load_dossier` becomes `load_dossiers`, plural.
- `generate_question` takes several dossiers and the item's `focus`. For a spanning
  item the Grading Mode is the **weakest** across its dossiers: a composite question
  is only as grounded as its least-grounded part, and claiming otherwise would record
  a Ground-Truth grade against material that has no answer key.
- `record_exchange` replaces `record_answer`: one `message` row per turn — question,
  probe, hint, answer — each labelled with its `kind` and the item's `topic_ids`.
  Labels come from the plan, deterministically. Nothing asks a model what a message
  was about.
- `grade` and `update_confidence` are **deleted from the loop**.
- `decide_next` keeps its duration and credits logic; scope exhaustion becomes plan
  exhaustion.

`GET /v1/sessions/{session_id}/transcript` serves the messages in order.

`POST /v1/sessions/{session_id}/turns` stops returning `last_visit`. A turn carries the next
question and nothing else.

## What does not change

`answer_turn` keeps its `interrupt` contract and its payload keys, so resumption,
idempotency and the surface's turn loop are untouched. `Interviewer.next_move` is
untouched — probe, hint and close already do exactly what this product wants, and
this slice must not take the opportunity to rewrite them.

## The Candidate stops seeing a score per question

This is a product change, not a refactor. PRD-0003 promises a score and a rationale
after every Topic Visit; there is no longer a per-Visit grade to show. The score
arrives once, in the report (ISSUE-0045). Amend PRD-0003 §12–14 and note that the
frontend's visit-result screen becomes report-only — it lives in another repository
and this slice breaks its contract deliberately.

## Acceptance criteria

- [x] A full Session runs end to end under `INTERVIEWER_FAKE_MODEL=1`
- [x] No turn response carries a score, a band, or `last_visit`
- [x] The transcript holds every question, probe, hint and answer, correctly labelled
- [x] A spanning item's messages carry all of its `topic_ids`
- [x] A spanning item grades under the weakest mode among its dossiers
- [x] No Evidence row is written while the Session is running
- [x] Resumption still works: the graph parks and resumes at `answer_turn` as before
- [x] Metering is unchanged — one provider binding per question, spend still recorded
- [x] ADR-0001's node list is amended; PRD-0003 §12–14 amended

## Blocked by

- ISSUE-0041 — there is no plan to run before there is a plan

## What landed

The graph is `build_plan → next_planned_item → load_dossiers →
generate_question → answer_turn → interviewer_move → record_exchange →
decide_next`, and `grade` and `update_confidence` are gone from it. A running
Session writes questions, answers and a transcript, and no Evidence at all.
`GET /v1/sessions/{session_id}/transcript` serves the messages in order, and a
turn carries the next question and nothing else. `Interviewer.next_move` was not
touched, the `interrupt` contract kept every key it had — `topic_ids`,
`topic_titles` and `plan_item_id` were **added** beside them — and the
provider-binding block moved verbatim.

Five things the ticket did not say, each a consequence of it rather than a
choice made beside it.

**`uq_visit_one_open_per_session` narrowed to `state = 'open'`.** The index used
to cover `state IN ('open','answered')`, because grading followed answering
immediately and an answered Visit was one still owed a score. Nothing is owed
between questions now, so a Session that asked twice would have collided with
itself on its second question. What the index still refuses is what it was
always about: two questions open at once. MCP Mode grades per Visit and still
refuses to advance past an answered one — it enforces that in `McpServer`
through `visits.unresolved`, which is unchanged. A new `visits.being_asked`
reads only the open one, and `POST /sessions/{id}/end` uses it: on the old
reading a Session that had answered anything could never be ended early.
`_migrate_core_indexes` applies the narrowing to a database that predates it.

**A question's terminal state is `answered`.** `record_exchange` closes it
there rather than at `graded`, because nothing in this slice grades. ISSUE-0044
moves it on. `SummaryService.for_session` counts answered *or* graded Visits, or
a Session mid-flight would report having examined nothing.

**PRD-0002 §16 is amended too.** It promised the opening question would be
drawn by curriculum order rather than by sampling — an exemption that existed
only because the sampler ran inside the loop. The sampler runs once now, before
the first question, and the ranking it produces *is* the order, so there is no
mid-Session draw left to exempt the opening from.

**A spanning question's `grounding_ref` gained a `spanning` shape**, one part
per Topic, and `citations.resolve` reads it: a citation belongs to the Topic it
came from, and flattening the ref would have let one Topic's Evidence cite
another's material. A single-Topic question keeps exactly the shape it had.

**Material withdrawn mid-Session ends the Session at the boundary.** The plan is
fixed and still names Topics a Candidate has since deleted the notebook for, so
`decide_next` checks the next item against scope and ends with
`scope_exhausted` when nothing of it survives — which is what ISSUE-0027 always
did, under the name it always had. `load_dossiers` drops a retired Topic from a
question that spans others rather than failing the question.

Tests rewritten rather than deleted, each because this slice changes what is
true: the walking skeleton's Evidence assertions, the agentic region's
"produces one Evidence row", resumption's grade-the-stored-exchange, the
retried-turn idempotency check (it counts answers in the transcript now), the
curriculum-order opening, the plan endpoint's item states, and the summary's
coverage reading. Where a test needs Evidence and is not about when Evidence is
written — the Judge, re-judging, citations, notebook lifecycle, identity — it
calls `conftest.grade_session`, which is the shape ISSUE-0044 will take at the
end of a Session.

Suite: 983 passed, 8 skipped.
