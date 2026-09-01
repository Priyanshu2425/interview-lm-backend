# ISSUE-0040 — A scope suggests a time

Status: open
Type: AFK
Source: SPEC-0007 §4
Covers: telling a Candidate how long their chosen scope actually needs

## What to build

A Candidate picks Modules and then picks a duration, with nothing connecting the
two. Eight Modules in fifteen minutes is a Session that ends having examined three
Topics, and the Candidate finds that out afterwards.

`service/graph/pacing.py`, pure and dependency-free:

    SECONDS_PER_QUESTION   = 180   # opening question plus up to max_turns follow-ups
    MAX_TOPICS_PER_QUESTION = 3

    suggested_seconds(topic_count)  -> one question per Topic
    minimum_seconds(topic_count)    -> ceil(topic_count / 3) questions
    budget_questions(seconds)       -> how many questions fit, at least 1

`GET /corpus/scope` grows `suggested_seconds`, `minimum_seconds` and
`questions_at_full_coverage`.

## The reading is Coverage, not difficulty

Time is derived from **Topic count only**. Not from `Dossier.approx_tokens`, and not
from anything else the Corpus knows about the material. "This Topic has more text so
it needs longer" is a difficulty reading dressed as a duration, and difficulty is not
a Corpus property (`AGENTS.md`, ADR-0007). Topic count is a Coverage fact, which the
product already publishes on this very endpoint.

`ScopeOut` carries a comment saying difficulty and cost are deliberately absent. It
stays, and gains a sentence: a time is neither.

## Acceptance criteria

- [ ] `pacing.py` is pure — no imports from `service/`, `db/` or `adapters/`
- [ ] `GET /corpus/scope` returns all three figures for a real scope
- [ ] 12 Topics suggests 36 minutes and a minimum of 12
- [ ] A one-Topic scope has a minimum of one question, never zero
- [ ] No figure on this endpoint is derived from dossier length
- [ ] `test_pacing.py` covers the boundaries without touching a database

## Blocked by

Nothing. This slice touches no table and can land before ISSUE-0039.
