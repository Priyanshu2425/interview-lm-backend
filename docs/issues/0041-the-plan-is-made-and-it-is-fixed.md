# ISSUE-0041 — The plan is made, and it is fixed

Status: open
Type: AFK
Source: SPEC-0007 §6; amends ADR-0005
Covers: the Session decides what it will ask before it asks anything

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

`GET /sessions/{id}/plan` serves it.

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

- [ ] `rank` returns every Topic, ordered; `choose` is `rank()[0]` and its tests are untouched
- [ ] Randomness stays injected — the same seed plans the same Session
- [ ] A 15-minute Session over 12 Topics yields 5 items, some spanning
- [ ] `GET /plan` twice returns byte-identical plans
- [ ] An UPDATE of a `plan_item`'s topics is refused by the database
- [ ] A malformed model reply still yields a valid plan, with `planner_fallback` true
- [ ] A plan never names a Topic outside the Session's scope
- [ ] ADR-0005 is amended, naming the clause that changed

## Blocked by

- ISSUE-0039 — the tables
- ISSUE-0040 — `budget_questions`
