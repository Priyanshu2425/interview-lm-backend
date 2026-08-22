# ISSUE-0006 — The agentic region: probe, hint, close

Status: ready-for-agent
Type: HITL
Source: PRD-0003; ADR-0001, ADR-0004
Covers: PRD-0003 §6–§11, §28, §29

## What to build

The one place in the system where the model's judgement is the product. Inside a
**Topic Visit**, the **Interviewer** decides whether to probe a vague answer,
offer a hint, or close and grade.

Agency is confined to this region. The loop around it stays rigid, and off-script
Candidate behaviour gets explicit handling rather than emerging from the model.
The deterministic skeleton already exists (ISSUE-0002), which is deliberate: every
guarantee in the design is a property of that skeleton, and growing the agentic
region afterwards keeps the seam visible.

A Visit may contain many **Answer Turns** and yields exactly one score. Probing
one concept three times is one observation examined closely, not three
observations — writing three updates would inflate **Coverage** threefold on a
single question's worth of information, and Thompson sampling reads those
posteriors.

An answer reached after hints is a real answer worth roughly half, expressed in
`s`. A Candidate who genuinely does not know may move on, so one blank Topic does
not consume the Session. A Visit is bounded in turns, so a single evasive exchange
cannot run forever.

**Why HITL:** the hint policy, the probing voice and the decision to close are
behavioural, not structural. A human reads real transcripts and signs off before
this accumulates permanent Evidence.

## Acceptance criteria

- [ ] A Topic Visit with four Answer Turns produces exactly one Evidence row
- [ ] Follow-ups, hints and probes are all recorded in the stored exchange
- [ ] A vague answer draws a follow-up rather than being silently marked down
- [ ] Requesting a hint is possible at any point and does not void the question
- [ ] Hint assistance appears in `s` and never as a reduced weight
- [ ] A Candidate may decline and move on; the Visit grades what was given and closes
- [ ] A Visit exceeding its turn bound closes and grades rather than running forever
- [ ] The Candidate is asked one thing at a time
- [ ] The Answer Key is never rendered before the Visit is graded
- [ ] Screen 02 renders the turn thread visibly resolving into one score
- [ ] A human has reviewed at least 10 real Visit transcripts across all three Grading Modes and signed off on hint timing and probing tone
- [ ] Loop tests remain deterministic with scripted model responses

## Blocked by

- ISSUE-0005 — the region operates inside a fully scoped, selected Visit
