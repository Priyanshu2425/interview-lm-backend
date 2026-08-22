# ISSUE-0005 — Session config and Topic selection

Status: ready-for-agent
Type: AFK
Source: PRD-0002, PRD-0003; ADR-0001, SPEC-0002
Covers: PRD-0003 §2, §3, §4, §17, §20, §22, §40; PRD-0002 §14

## What to build

A **Session** becomes real: scoped to Modules the **Candidate** chose, running
for a duration they chose, with Topics selected rather than taken in order.

Scope and duration are fixed before the Session begins and immutable afterwards,
enforced in the database. Duration is recorded on the Session because Sessions
are only comparable to Sessions of the same chosen duration.

**The deadline is soft.** The Session ends *after* the current **Topic Visit**
finishes, never inside one — a truncated Visit produces either no Evidence or
Evidence from a half-examined answer, and both corrupt the record the Session
exists to build. The Candidate may also end early.

Selection is Thompson sampling over the in-scope Topics: draw one sample from each
posterior, examine the highest. Untested Topics sample widely, so exploration
falls out of the model rather than needing a separate rule. Two explicit
exemptions — the opening Topic follows curriculum order, and Topics already
visited in this Session are excluded. Randomness is injected, not called.

Scope enforcement is the selector's job, not the Interviewer's: the Topic is
handed to it.

Screens 01 and 04 complete — the picker writes a real Session, and the summary
reports what was examined against what was not.

## Acceptance criteria

- [ ] A Session records its chosen Modules and duration, and both reject modification afterwards
- [ ] No Topic outside the Session's chosen Modules is ever visited
- [ ] No Topic is visited twice within one Session
- [ ] The opening Topic follows curriculum order; subsequent Topics come from the selector
- [ ] A returning Candidate's opening difficulty is seeded from stored posteriors rather than restarting from the prior
- [ ] Untested Topics are selected without a separate exploration rule
- [ ] The selector receives its randomness; two Sessions with the same injected source produce the same Topic sequence
- [ ] When the duration expires the Session ends after the current Visit completes, never inside one
- [ ] A Candidate ending early completes the current Visit and then ends
- [ ] A Session whose scope is exhausted ends with that reason recorded, distinguishably from a duration end
- [ ] Screen 04's summary distinguishes Topics never asked about from Topics answered badly
- [ ] Screen 04 reports the count of Topics never examined, against the full Corpus
- [ ] No claim about difficulty appears anywhere

## Blocked by

- ISSUE-0004 — selection samples the posteriors the tracker maintains
