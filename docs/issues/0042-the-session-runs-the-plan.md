# ISSUE-0042 — The Session runs the plan

Status: open
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

- [ ] A full Session runs end to end under `INTERVIEWER_FAKE_MODEL=1`
- [ ] No turn response carries a score, a band, or `last_visit`
- [ ] The transcript holds every question, probe, hint and answer, correctly labelled
- [ ] A spanning item's messages carry all of its `topic_ids`
- [ ] A spanning item grades under the weakest mode among its dossiers
- [ ] No Evidence row is written while the Session is running
- [ ] Resumption still works: the graph parks and resumes at `answer_turn` as before
- [ ] Metering is unchanged — one provider binding per question, spend still recorded
- [ ] ADR-0001's node list is amended; PRD-0003 §12–14 amended

## Blocked by

- ISSUE-0041 — there is no plan to run before there is a plan
