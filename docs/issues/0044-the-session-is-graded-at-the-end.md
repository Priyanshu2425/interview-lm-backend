# ISSUE-0044 — The Session is graded at the end

Status: open
Type: AFK
Source: SPEC-0007 §9; amends ADR-0004
Covers: one Evidence row per Topic, extracted from the transcript when the Session ends

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
`POST /sessions/{id}/end` calls it too, and so does the resumption path for a Session
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

- [ ] Exactly one Evidence row per reached Topic, none for unreached ones
- [ ] Grading the same Session twice writes nothing the second time
- [ ] A spanning question produces one row per Topic it named
- [ ] The assembled prompt contains no probe text, no hint text, no other Topic's title
- [ ] Kill the process mid-Session, resume, end — the grade still lands, once
- [ ] `/end` grades; a Session ended by the clock grades; both reach the same rows
- [ ] Unreached items are recorded as `unreached`, distinguishable from `asked`
- [ ] ADR-0004 amended, naming the unit that changed and the count that did not

## Blocked by

- ISSUE-0042 — there is no transcript to grade before there is a transcript
- ISSUE-0043 — the Verdict shape
