# ISSUE-0044 — The Session is graded at the end

Status: resolved
Type: AFK
Source: SPEC-0007 §9; amends ADR-0004
Covers: one Evidence row per Topic, extracted from the transcript when the Session ends

> **Paths in this ticket** were written against `api/`, which is now `routes/v1/`.
> Every router is mounted under `/v1`, the Corpus endpoints are served under
> `skills/`, and the session path parameter is `{session_id}`. Corrected in place;
> the tree is the authority.

## What to build

`service/judge/session_grader.py`. For each Topic that appears in any message's
`topic_ids`:

1. Pull that Topic's messages in `seq` order.
2. Build the blind bundle — interviewer messages with `kind == "question"` only, plus
   the Candidate's answers. Probes, hints and turn counts are dropped. Reuse the
   filter behind `Judge._answer_only` so there is one implementation of blindness
   rather than two that drift.
3. `Judge.grade` against that Topic's own dossier and mode.
4. One Evidence row plus the posterior update, in one transaction.

`grade_session` is a graph node on the edge to END — an edge cannot not run. It marks
every still-`planned` item `unreached` and calls the service.
`POST /v1/sessions/{session_id}/end` calls it too, and so does the resumption path for a Session
whose graph finished without Evidence.

Idempotent on `UNIQUE(session_id, topic_id)`: grading twice is a no-op, which is what
makes it safe to call from three places.

## ADR-0004 is amended, and strengthened

ADR-0004 forbade a Beta update per turn, because follow-ups on one concept are one
observation examined closely rather than several trials. That holds exactly as
written. What moves is the unit: **the Topic within a Session**, not the Topic Visit.

The count is unchanged — one observation per Topic per Session, before and after. An
observation may now be assembled from several questions (a spanning one plus a
dedicated one), and one question may contribute to several observations. The refusal
it encodes is stronger than before, because there is no longer an in-loop write path
at all: `UNIQUE(session_id, topic_id)` makes a second write impossible rather than
merely absent.

## Planned but never reached is not a zero

A Session that runs out of clock leaves items unasked. Those Topics have no messages,
so they get **no Evidence row and no posterior touch**. Untested is not zero — it is
the Evidence Floor's whole argument, and a Session that silently scored every
unreached Topic at zero would corrupt a Candidate's record for material they were
never shown.

## Blindness is at risk from spanning questions, not from the transcript

One answer to a question spanning three Topics is graded three times, against three
different groundings. The per-Topic prompt must name only that Topic's grounding, and
must carry no probe or hint text and no other Topic's title. This is asserted in
`test_architecture.py`, which already polices rules of this kind — care is not a
mechanism.

## Acceptance criteria

- [x] Exactly one Evidence row per reached Topic, none for unreached ones
- [x] Grading the same Session twice writes nothing the second time
- [x] A spanning question produces one row per Topic it named
- [x] The assembled prompt contains no probe text, no hint text, no other Topic's title
- [x] Kill the process mid-Session, resume, end — the grade still lands, once
- [x] `/end` grades; a Session ended by the clock grades; both reach the same rows
- [x] Unreached items are recorded as `unreached`, distinguishable from `asked`
- [x] ADR-0004 amended, naming the unit that changed and the count that did not

## Blocked by

- ISSUE-0042 — there is no transcript to grade before there is a transcript
- ISSUE-0043 — the Verdict shape


## What landed

`service/judge/session_grader.py`. `SessionGrader.grade(session_id)` reads the
transcript, groups it by the `topic_ids` the plan fixed, and for each Topic that
appears in any message assembles a blind bundle — that Topic's `question`
messages plus every Candidate turn — grades it against that Topic's own dossier,
and writes one Evidence row with the posterior update in one transaction. A
Topic no message names is never iterated over, which is how "planned but never
reached is not a zero" is enforced: by an absence rather than a branch.

**Idempotency is a constraint, not a read.** `EvidenceLedger.write_topic` is a
new sibling of `write` — `write` stays, keyed on `topic_visit_id`, because MCP
Mode still grades per Visit — and it inserts `ON CONFLICT (session_id, topic_id)
DO NOTHING`, returning the existing row when it loses. Two callers racing get
one observation. The insert reports what it did through `RETURNING` rather than
`rowcount`: a plain INSERT reports `rowcount` as `-1`, and `-1` is truthy, so
the obvious check would have called every conflict a write.

**`grade_session` is a graph node on the edge to END**, and both conditional
edges that used to point at `__end__` now point at it. It does *not* grade a
Session parked for want of Credits: that Session reaches END the same way but is
not finished — topping up resumes it — and grading it there would write a Beta
observation for a Candidate about to be asked more about the same Topics.

### Deviations

**`mark_unreached` lives in the service, not in the node.** The ticket puts it
in the node. Putting it one layer down means `/end` and the resumption path get
it too, so a Session ended by hand and one ended by the clock leave the same
plan states behind — with it in the node, `/end` would have had to remember, and
a rule two callers must remember is a rule one of them will not. The node still
calls `mark_unreached` itself when there is no grader wired, so the two paths
never both do it. `SessionRunner._interpret` no longer does it at all.

**An Evidence row keeps a `topic_visit_id`.** ISSUE-0039 made the column
nullable because a row need not descend from any single question — not because
nothing knows which ones it did. It carries the last Visit that examined the
Topic, so a grade stays traceable, `/spend` still finds its Visit, and the
re-judge path still has one to call the model with. Uniqueness is not on it: a
spanning question's three rows share it.

**Grading is billed to a Visit that happened.** Grading is a model call and
therefore a charge. Rather than mint a `grade_<session_id>` reference and a
second `/spend` line, the grader rebinds the metered client to the Visit whose
question it is grading, so `/spend`'s per-Visit totals still add up to what the
ledger took.

**A Topic whose material was withdrawn mid-Session is not graded.** The dossier
will not load, so there is no grounding, and a Verdict reached against nothing
is a measurement nobody made.

**Mode is the Topic's own, not the question's.** A spanning question records the
weakest mode across its dossiers (ISSUE-0042). Grading is per Topic against that
Topic's dossier, so it uses that Topic's own mode — `question_writer.mode_for`,
extracted so the ladder is stated once rather than copied.

**Answered Visits become `graded` when their Session is graded.**
`VisitLifecycle.mark_graded` closes them Session-wide. ISSUE-0042 left
`answered` terminal for the managed loop because nothing graded a question any
more; a question inside a graded Session owes nothing further, and leaving them
`answered` would have kept `open_topic_ids` pinning their material open forever
(ISSUE-0027). MCP Mode is untouched and still closes its own Visits.

Tests rewritten rather than deleted, each because this slice changes what is
true: `test_running_the_plan.py::test_no_evidence_row_is_written_while_the_session_is_running`
now asserts that after every turn *while the Session is still running* there is
no Evidence, no posterior and no Judge call — the claim ISSUE-0042 actually
made, which ISSUE-0044 does not weaken; and the walking skeleton's soft-deadline
test expects the completed Visit in `graded` rather than `answered`, because
reaching the end of a Session grades it. `conftest.grade_session` is now the
real `SessionGrader.grade` under the name every test already calls, so the two
dozen tests that need Evidence exercise the shipped path.

The unreached property is proved against a real Session, not a fixture:
`_outran_its_clock` plans thirty minutes of questions, advances the frozen clock
past the deadline while the first question is in flight, and asserts that the
Topics behind the `unreached` items have no Evidence row, no posterior and no
row in `evidence` at all.

Suite: 1001 passed, 8 skipped.
