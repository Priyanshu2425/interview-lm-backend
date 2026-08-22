# ISSUE-0007 — Resumption and replay determinism

Status: ready-for-agent
Type: AFK
Source: PRD-0003; ADR-0001, ADR-0003, ADR-0011; SPEC-0000
Covers: PRD-0003 §15, §16, §38, §41, §42

## What to build

An interrupted **Session** ends with an error the Candidate can act on, and is
picked up from where it stopped rather than being lost. The mechanism already
exists — a Session is a checkpointed thread, the **Answer Turn** is a park, and
resumption is another caller of resume.

An interrupted **Topic Visit** stays open until it is graded and is never
partially recorded. Where the answer was submitted but grading did not complete,
the exchange is already stored, so resumption grades it and closes the Visit — and
the idempotency key makes a repeated grade a no-op rather than a double write. **No
Evidence is ever written for a Visit that was not graded.**

Determinism is the other half of this slice, and it is a requirement rather than a
nicety: replay is the only way to know whether grading is any good. Every
non-deterministic input is injected rather than called — randomness for
selection, the clock for the duration check, and model responses. A recorded
Session re-runs against a changed prompt or rubric and the difference is
attributable.

On the surface, a turn request that times out is a park, not an error: recovery
reads Session state and resumes, which is the same path an interruption already
takes.

## Acceptance criteria

- [ ] A Session interrupted after submission but before grading, then resumed, grades the stored exchange and closes the Visit
- [ ] Resuming a Session that was already fully graded writes nothing new
- [ ] A Visit left open blocks its Session from advancing, enforced by constraint
- [ ] A Session that errors ends in a state the Candidate can act on, with the reason recorded
- [ ] `session.state` is the Session's own record and is readable when its checkpoint is gone
- [ ] A Session replayed with the same injected randomness, clock and scripted responses produces an identical Visit sequence and identical scores
- [ ] A Session replayed with a changed rubric version produces different scores against the same exchanges
- [ ] No module in the graph reaches for the clock, a random source, or a provider client directly
- [ ] A graph schema migration applied to a database holding `core` rows leaves those rows byte-identical
- [ ] Applying every graph migration while a resumable Session exists is prevented
- [ ] A timed-out turn request recovers by reading Session state, using the same code path as an interruption
- [ ] Screen 02 recovers from a dropped connection without losing a submitted answer

## Blocked by

- ISSUE-0006 — replay must cover the agentic region, not just the skeleton
