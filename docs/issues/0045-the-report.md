# ISSUE-0045 — The report

Status: open
Type: AFK
Source: SPEC-0007 §9
Covers: what the Candidate reads when the Session ends

## What to build

`GET /sessions/{id}/report` — the one place a Session's result is shown, now that no
turn carries a score.

It holds:

- the plan as it was fixed, and what became of each item (`asked` or `unreached`)
- per reached Topic: `band`, `coverage`, `mastery_or_none`, `source_score`,
  `truth_score`, `question_count`, `citations`
- `planned_not_reached[]` — named, with no numbers against them

`summary.py` needs fixing rather than replacing: `SummaryService.for_session` filters
on `topic_visit.state == "graded"`, and that state no longer exists. It reads Evidence
by `(session_id, topic_id)` now. `GET /sessions/{id}/summary` keeps working.

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

- [ ] The report names reached and unreached Topics, and distinguishes them
- [ ] No field fuses Coverage with Mastery, and none fuses the two sub-scores
- [ ] An unreached Topic carries no band, no score and no interval
- [ ] A Topic below the Evidence Floor renders the word, not a number
- [ ] `GET /summary` still answers, reading Evidence by `(session_id, topic_id)`
- [ ] A Session with no reached Topics returns a report rather than an error
- [ ] The report is stable — the same Session returns the same reading twice

## Blocked by

- ISSUE-0044 — there is nothing to report before the grading lands
