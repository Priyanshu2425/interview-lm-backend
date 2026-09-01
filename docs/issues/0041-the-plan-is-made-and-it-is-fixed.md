# ISSUE-0041 — The plan is made, and it is fixed

Status: resolved
Type: AFK
Source: SPEC-0007 §6; amends ADR-0005
Covers: the Session decides what it will ask before it asks anything

> **Paths in this ticket** were written against `api/`, which is now `routes/v1/`.
> Every router is mounted under `/v1`, the Corpus endpoints are served under
> `skills/`, and the session path parameter is `{session_id}`. Corrected in place;
> the tree is the authority.

## What to build

Today the next Topic is drawn from a sampler after every Visit, so the shape of a
Session is an emergent property nobody can see in advance. Instead: rank the Topics
once, plan the questions once, write the plan down, and never change it.

`TopicSelector.rank(candidate_id, topic_ids, rng) -> list[str]` — ascending Beta
draw, weakest-or-least-known first. `choose` becomes `rank(...)[0]`, so every
existing selection test keeps passing and the sampler keeps its one implementation.

`service/graph/planner.py` — `SessionPlanner.plan()`:

1. Rank the in-scope Topics from **previous** Sessions' posteriors. Untested Topics
   sample wide and float up; that is the exploration rule, unchanged.
2. `budget = budget_questions(duration)` from ISSUE-0040.
3. `breadth = "full" if budget >= len(ranked) else "compressed"`.
4. One model call: the ranked Topics with their titles, the budget, and an
   instruction to produce exactly N items of 1–3 Topics each, saying in one line
   what a single question spanning a group would test.
5. **Validate in Python, hard**: exactly N items, every `topic_id` in scope, span
   ≤ 3, no Topic in two items.
6. Persist `session_plan` and `plan_item` rows in one transaction.

`build_plan` becomes the graph's first node. On resume it **reads** the stored plan
rather than replanning — fixedness survives a restart because the plan is in
Postgres, not only in the checkpointer.

`GET /v1/sessions/{session_id}/plan` serves it.

## Thompson sampling did not die, it moved

ADR-0005 chose Thompson sampling over the Topics and put it inside the loop, where it
needed the posterior updated after every Visit. That in-loop position is the only
reason grading had to happen mid-Session.

The sampler is unchanged. What changes is *when* it is consulted: once, before the
first question, over what previous Sessions established. The Candidate gets a legible
plan instead of an invisible sampler, and the same distribution decides it. Amend
ADR-0005 rather than superseding it, and name the sentence that changed.

## The plan may not fail

This is the first thing that happens in a Session, so a model that returns prose, or
eleven items when asked for five, or a Topic that is not in scope, must not produce a
500. Any validation failure falls back to deterministic contiguous chunking of the
ranked list, and sets `planner_fallback = True` so the fallback is visible in the
record rather than indistinguishable from a good plan.

## Acceptance criteria

- [x] `rank` returns every Topic, ordered; `choose` is `rank()[0]` and its tests are untouched
- [x] Randomness stays injected — the same seed plans the same Session
- [x] A 15-minute Session over 12 Topics yields 5 items, some spanning
- [x] `GET /v1/sessions/{session_id}/plan` twice returns byte-identical plans
- [x] An UPDATE of a `plan_item`'s topics is refused by the database
- [x] A malformed model reply still yields a valid plan, with `planner_fallback` true
- [x] A plan never names a Topic outside the Session's scope
- [x] ADR-0005 is amended, naming the clause that changed

## Blocked by

- ISSUE-0039 — the tables
- ISSUE-0040 — `budget_questions`


## What landed — 2026-09-01

`TopicSelector.rank` orders the whole scope from one round of Beta draws, in the
order the ids were given, and `choose` is its head. The draws and the tie-break
are what they were, so `test_selection.py` is untouched and the sampler still has
one implementation.

`service/graph/planner.py` holds the whole of it: `SessionPlanner.plan` ranks,
budgets, asks once, validates hard, and persists; `PlanStore` writes the header
and its items in one transaction and reads them back. There is no `update` on
`PlanStore` — the trigger would refuse one, and the call should not exist to be
made. `build_plan` is the graph's first node and asks `stored()` before it plans,
so a resume reads the plan rather than making a second one.

`GET /v1/sessions/{session_id}/plan` serves it, ordered by `item_order`, with
titles resolved at read time rather than copied onto the item — the plan is fixed
on Topic identity, not on how a Topic was captioned.

### Deviations, and why

**The budget is capped at the number of Topics.** The ticket says
`breadth = "full" if budget >= len(ranked) else "compressed"` and "exactly N
items". Taken literally, a two-hour Session over three Topics wants forty items
of at least one Topic each with no Topic repeated, which is not satisfiable.
`budget_questions` is recorded as the ticket defines it and `breadth` is decided
from it; the number of items asked for is `min(budget, len(ranked))`, because a
question about no Topic is not a question.

**A Provider failure is not a fallback.** "The plan may not fail" is implemented
for what the model *says* — prose, the wrong count, an out-of-scope Topic, a
Topic in two items — and every one of those falls back to contiguous chunking
with `planner_fallback` true. A `ProviderFailure` propagates and parks the
Session the way every other model call does. The plan is fixed once written, so a
dropped connection must not lock a Candidate into a fallback plan that retrying
can never replace.

**The planner's call is attributed to `plan_<session_id>`.** SPEC-0005 rejects a
model call carrying no attribution, and the plan belongs to no Topic Visit — it
is what decides that Visits there will be. It binds a Provider under that id and
is metered normally. Two consequences, both deliberate: `GET /sessions/{id}/spend`
grew a `planning` line and counts it in the total, because a total built only
from Visits is smaller than what the ledger actually took; and the Operator
console's `count(distinct topic_visit_id)` now counts one extra unit per Session,
which is a distortion of `credits_per_visit` that a `call_record.kind` column
would fix and that is schema work this slice did not open.

**The fallback writes no `focus`.** Contiguous chunking has nothing to say about
what a group tests, and a sentence manufactured from titles would read as a claim
the planner did not make. `planner_fallback` is what distinguishes the two.

### Test rewritten

`test_walking_skeleton.py::test_a_topic_visit_row_exists_before_the_first_model_call`
became `test_every_model_call_is_attributed_and_the_visit_row_precedes_its_own`.
It asserted that the first model call in a Session resolves to an open
`topic_visit` row. The first model call is now the planner's, and it deliberately
does not: the plan precedes every Visit. The rule it holds is stated as two
clauses now — every call carries an attribution, and every call attributed to a
Topic Visit finds that Visit already open.

Suite: 961 passed, 8 skipped.
