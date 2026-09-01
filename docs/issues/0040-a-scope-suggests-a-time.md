# ISSUE-0040 — A scope suggests a time

Status: resolved
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

- [x] `pacing.py` is pure — no imports from `service/`, `db/` or `adapters/`
- [x] `GET /corpus/scope` returns all three figures for a real scope
- [x] 12 Topics suggests 36 minutes and a minimum of 12
- [x] A one-Topic scope has a minimum of one question, never zero
- [x] No figure on this endpoint is derived from dossier length
- [x] `test_pacing.py` covers the boundaries without touching a database

## Blocked by

Nothing. This slice touches no table and can land before ISSUE-0039.

## What landed

`service/graph/pacing.py` holds the arithmetic and imports nothing but
`__future__`, which `test_pacing.py` asserts by parsing the module rather than by
trusting it — a pure module stays pure only if something notices when it stops.
The endpoint grew `suggested_seconds`, `minimum_seconds` and
`questions_at_full_coverage`, each read off `topic_count` and nothing else, and
`ScopeOut`'s standing comment about difficulty and cost gained the sentence
saying a time is neither.

Two functions exist that the ticket does not name. `questions_at_full_coverage`
is the endpoint's third figure and is a function rather than a bare
`topic_count` at the call site, so the surface reads a promise instead of a
coincidence. `is_compressed` answers the question ISSUE-0041 has to ask —
whether the clock forces grouping — and belongs beside the constants it is
derived from rather than in the planner that consumes it.

### Deviation

The route is `GET /v1/skills/scope`. The ticket says `/corpus/scope`, which was
its name when the ticket was written; the restructure that landed with
ISSUE-0039 renamed the router, and the ticket was not rewritten to follow. Same
endpoint, same response model, new path.

The implementation itself arrived inside the ISSUE-0039 commit rather than its
own, carried along by that restructure. What this slice added afterwards is the
missing half of its second criterion: the three figures were asserted for an
empty scope and not for a real one, so a scope of ten Topics now checks 1800 and
720 against the endpoint, and checks that the suggestion is the Topic count
times the per-question constant — which is where a dossier-length reading would
show up if one ever crept in.
