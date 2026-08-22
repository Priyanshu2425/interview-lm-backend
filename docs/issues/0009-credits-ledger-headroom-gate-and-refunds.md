# ISSUE-0009 — Credits: ledger, headroom gate and refunds

Status: ready-for-agent
Type: AFK
Source: PRD-0005; ADR-0010, ADR-0014; SPEC-0005
Covers: PRD-0005 §1, §2, §6–§12, §22, §23, §36, §43, §44

## What to build

**Credits** become real. One Credit is one US cent of what OpenRouter charged us —
not a house currency, not a smoothed average. A $9.70 call spends 970 Credits, so
Credits float with the **Provider** and the Candidate sees that.

Balance is derived from an append-only ledger. There is no balance column to
drift and no code path that edits one. Rounding is floor, per call: a sub-cent
call costs zero rather than one, because rounding up turns a chatty Visit into a
rounding-fee product.

**The spend check runs at the Topic Visit boundary and nowhere else.** A Visit
opens only if the balance clears a headroom threshold; once open it runs to
completion — Judge call included — regardless of what the balance does. **A
balance may end a Visit negative. A Visit may never be truncated.** This is the
decision the design settles in the Evidence model's favour: a Visit cut off
mid-exchange corrupts a permanent write, and the overrun costs a few Credits.

Exhaustion at the boundary is a clean end, not an error: the Session stops opening
Visits and parks, and topping up resumes it.

Metering is per call, so an ungraded Visit still cost money and the ledger says
so. Refunds are the exception that reunites spend and Evidence, and they key on
`topic_visit_id` — one explicit ledger entry, only for failures that were ours.
**A refund is never a balance edit.**

Grants are written only once payment clears, which is what makes
`pool ≥ sum(candidate balances)` hold by construction rather than by
reconciliation. Pool drawdown is recorded in our own summed call costs, with the
provider's figure stored beside it (ADR-0014).

Payment processing is out of scope: this slice consumes a *payment cleared* event
and produces a grant.

## Acceptance criteria

- [ ] $9.70 of reported cost converts to exactly 970 Credits
- [ ] A sub-cent call converts to 0 Credits, not 1
- [ ] Conversion is exact at values that would drift under floating point; balances are integers at every step
- [ ] A debit larger than the balance produces a negative balance rather than a clamped zero or an error
- [ ] Headroom clears and fails at the boundary value, in both directions
- [ ] Balance is computed from ledger rows and matches the sum of grants, debits and refunds
- [ ] A grant is written only after payment clears, and a replayed payment event grants once
- [ ] The spend gate is called from exactly one place; a test asserts no other call site exists
- [ ] A Session parks when the balance fails headroom at a Visit boundary and writes no partial Visit
- [ ] An in-flight Visit completes and grades when the balance is exhausted mid-Visit, ending negative
- [ ] Topping up resumes a parked Session rather than starting a new one
- [ ] An ungraded Visit still has its calls metered — spend and Evidence are independent
- [ ] A refund keyed on a `topic_visit_id` refunds every call under that Visit exactly once; a repeat is a no-op
- [ ] No code path updates a balance directly
- [ ] `pool ≥ sum(candidate balances)` holds across a grant/spend/refund sequence
- [ ] Screen 05 shows the balance with its definition, the per-Visit ledger, an ungraded Visit that still cost money, and its refund as a separate line
- [ ] No Session cost is quoted before the Session runs; per-Provider figures are presented as history

## Blocked by

- ISSUE-0008 — the ledger debits what the metered client records
