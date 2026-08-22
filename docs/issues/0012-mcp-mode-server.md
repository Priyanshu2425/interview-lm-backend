# ISSUE-0012 — MCP Mode server

Status: ready-for-agent
Type: AFK
Source: PRD-0004; ADR-0002, ADR-0006, ADR-0009
Covers: PRD-0004 (all 16 stories)

## What to build

A **Session** that runs inside someone's Claude session. Our system is an MCP
server; the host Claude drives it through our tools, steered by prompts we supply.

The host is a ReAct agent we do not control. **Prompts steer it; they do not
constrain it.** Any invariant that matters is therefore enforced by the server,
never asked for in a prompt. Two survive both modes:

1. **Evidence is written once per Topic Visit** — not because the host is asked to
   behave, but because the write is idempotent on a server-issued
   `topic_visit_id`, and the Session will not advance while a Visit is
   unresolved.
2. **No Answer Key enters the interviewing context.** The host holds its context
   in front of the Candidate, so an Answer Key reaching the host is leaked by
   construction, and no prompt can unsee it. Grading material is redeemed directly
   by the **Judge Subagent** against a Visit id and never passes through the host.

`submit_answer` opens a Visit and returns a `topic_visit_id`. The Judge Subagent
calls the server itself to redeem grading material against that id. Redemption is
single-use or narrowly time-scoped, so a leaked id has a bounded blast radius. The
host orchestrates and never sees an Answer Key.

Blindness is satisfied because it was never about which machine grades — it is
context isolation. A subagent starts fresh, receives only the question, the answer
and the grounding, applies the same rubric, and ends.

**Grader Provenance** records `judge_subagent` on these rows, and the raw exchange
is stored, so MCP-graded Evidence is re-judgeable in batch like any other.

MCP Mode has no metering: the host's subscription pays for both the interviewing
and the Judge Subagent. There is no key to hold and nothing to meter.

## Acceptance criteria

- [ ] Tool descriptions state the intended loop, so steering is available even though it is not a constraint
- [ ] `submit_answer` returns a server-issued `topic_visit_id`
- [ ] Submitting a second score for the same `topic_visit_id` leaves the posterior unchanged and reports the existing result
- [ ] The Session will not advance while a Visit is unresolved, enforced by the server
- [ ] No tool available to the host returns an Answer Key or grading material, for any Visit, in any state
- [ ] Grading material is redeemable only against a Visit id, and redemption is single-use or time-scoped
- [ ] A replayed redemption after expiry is refused
- [ ] A host that skips grading cannot advance the Session; a host that grades twice writes once
- [ ] A host that requests Topics outside the Session's scope is refused by the server
- [ ] Evidence rows record provenance as Judge Subagent and store the raw exchange
- [ ] Rubric version is recorded on every MCP-graded row
- [ ] A completed MCP Session's Evidence rows are indistinguishable in shape from Managed Mode rows, and distinguishable in provenance
- [ ] MCP Sessions write no ledger rows and no call records against our key
- [ ] MCP Mode renders no Credit or key-related failure event
- [ ] Weights are set by Grading Mode alone; no mode-4 is invented for MCP

## Blocked by

- ISSUE-0007 — MCP Mode reuses the Topic Visit lifecycle and resumption invariants
