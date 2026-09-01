# ISSUE-0045 — The report

Status: resolved
Type: AFK
Source: SPEC-0007 §9
Covers: what the Candidate reads when the Session ends

> **Paths in this ticket** were written against `api/`, which is now `routes/v1/`.
> Every router is mounted under `/v1`, the Corpus endpoints are served under
> `skills/`, and the session path parameter is `{session_id}`. Corrected in place;
> the tree is the authority.

## What to build

`GET /v1/sessions/{session_id}/report` — the one place a Session's result is shown, now that no
turn carries a score.

It holds:

- the plan as it was fixed, and what became of each item (`asked` or `unreached`)
- per reached Topic: `band`, `coverage`, `mastery_or_none`, `source_score`,
  `truth_score`, `question_count`, `citations`
- `planned_not_reached[]` — named, with no numbers against them

`summary.py` needs fixing rather than replacing: `SummaryService.for_session` filters
on `topic_visit.state == "graded"`, and that state no longer exists. It reads Evidence
by `(session_id, topic_id)` now. `GET /v1/sessions/{session_id}/summary` keeps working.

## The refusals this endpoint inherits

Everything `AGENTS.md` already refuses applies here, and this is the screen most
likely to want to break them:

- Coverage and Mastery do not fuse. There is no headline number for a Session.
- `source_score` and `truth_score` are shown separately. The combination that fed
  the posterior is not shown as a score — it is an input to the math, and showing it
  would be exactly the fusion the previous rule refuses.
- An unreached Topic gets the word, never a zero and never a band.
- Below the Evidence Floor, `mastery_or_none` is absent and the word appears instead.
- No rank, no leaderboard, no cohort figure outside one Topic's drawer.

## Acceptance criteria

- [x] The report names reached and unreached Topics, and distinguishes them
- [x] No field fuses Coverage with Mastery, and none fuses the two sub-scores
- [x] An unreached Topic carries no band, no score and no interval
- [x] A Topic below the Evidence Floor renders the word, not a number
- [x] `GET /v1/sessions/{session_id}/summary` still answers, reading Evidence by `(session_id, topic_id)`
- [x] A Session with no reached Topics returns a report rather than an error
- [x] The report is stable — the same Session returns the same reading twice

## Blocked by

- ISSUE-0044 — there is nothing to report before the grading lands

## What landed

`GET /v1/sessions/{session_id}/report`, served by a new `ReportService` in
`backend/src/interviewer/service/confidence/report.py` and wired as
`wiring().report`. It reads only, so the same Session reports the same twice.

It returns the plan as it was fixed — header plus one entry per item carrying
`state` (`asked`, `unreached`, or `planned` while the Session is still
running), its Topics and whether each was reached — a reading per reached
Topic, and `planned_not_reached[]`.

**Reached is read off the Evidence, not off the transcript or the plan.** The
Evidence row *is* the measurement (ISSUE-0044), so a Topic without one was not
measured whatever else happened around it. That makes the two lists disjoint by
construction rather than by care: an unreached Topic is not merely missing its
numbers, it is in a different list, whose entries hold `topic_id` and `title`
and nothing else. There is no band, no posterior, no interval and no zero to be
misread — and no field on the reading that could hold one, because the shape
that carries numbers is not the shape unreached Topics are built into.

`evidence.score` is deliberately not carried out of the module. It is the
combination that fed the posterior — an input to the maths, not a reading —
and `source_score` and `truth_score` are reported apart beside `question_count`
and `citations`, either of them null where the Judge took only one reading.
There is no Session-wide figure of any kind: `SessionReport` has no `coverage`,
no `mastery` and no `score` field, and that absence is under test.

Two deviations, both naming rather than behaviour:

- The per-Topic field is `mastery`, not `mastery_or_none`. The value is
  `Posterior.mastery_or_none` — absent below the Evidence Floor, never zero —
  but `summary`, `candidate_readings` and the surface's `bandClass` all already
  say `mastery` for exactly this, and a second name for one reading is how a
  client ends up reading the one it did not expect.
- The ticket says `SummaryService.for_session` filters on
  `topic_visit.state == "graded"` and that the state no longer exists. Neither
  was still true: ISSUE-0044 restored `graded` via `VisitLifecycle.mark_graded`
  and the filter already read `("answered", "graded")`. What was actually
  stale is what the ticket asked for next — the Evidence join was keyed on
  `topic_visit_id`, so a spanning question's three rows share one key, two of
  the three were dropped and the survivor was read against the wrong Topic.
  It is keyed `(session_id, topic_id)` now, which is the fix the ticket meant.

No test was rewritten: nothing asserted behaviour this slice changes.
`test_report.py` is new and covers each acceptance criterion, running real
Sessions — the unreached case comes from a plan that outran its clock, because
a hand-built fixture reaches everything its author thought to write down.

Suite: 1019 passed, 8 skipped.
