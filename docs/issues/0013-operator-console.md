# ISSUE-0013 — Operator console

Status: ready-for-agent
Type: AFK
Source: PRD-0005 §7; ADR-0014; SPEC-0005
Covers: PRD-0005 §38–§42; ADR-0014

## What to build

The internal surface that makes pre-funding a scheduled act rather than an
emergency, and keeps a metering gap visible.

**Pool headroom** leads, because it is the only figure that can strand a Candidate
mid-Session. It is shown against its alert threshold so topping up is scheduled
off a reading rather than triggered by a Candidate's failure. Pool balance is
reported as working capital — a one-way float, recoverable as service and not as
cash — because how large it runs is a live decision even though the failure mode
is gone.

**Unpriced call rate** sits beside it: the proportion of calls where the provider
reported no cost, per Provider. A rising figure is a metering regression, and it is
only visible because unpriced was never collapsed into zero.

**Drawdown divergence** is the third reading — cumulative difference between the
provider's reported usage and our own summed call costs. It should sit near zero,
and its direction is informative: a gap upward means calls are happening that
produce no call record, which is exactly what the metering chokepoint exists to
prevent; a gap downward means Candidates are being charged for calls the provider
did not bill (ADR-0014).

Per-Provider spend and failure rates, and spend rolling up call → Visit → Session
→ Candidate, all read off records that already exist. **No new instrumentation.**

Promotional Credits spend from the same pool as purchased ones, which makes a
promotion a margin question and never an availability one.

## Acceptance criteria

- [ ] Pool headroom is computed as pool minus the sum of Candidate balances, and shown against its threshold
- [ ] An alert is raised when headroom falls below the threshold
- [ ] Float is reported as a working-capital figure
- [ ] Promotional grants draw from the same pool and are visible as such
- [ ] Unpriced call rate is reported per Provider and is distinguishable from zero-cost
- [ ] Drawdown divergence is reported cumulatively and signed, so its direction is readable
- [ ] Per-Provider spend, cost per Visit and failure rate are derived from call records with no additional instrumentation
- [ ] Spend rolls up call → Topic Visit → Session → Candidate on existing keys
- [ ] BYOK and MCP Sessions render `—` rather than `0` for Credits
- [ ] Sessions that ended on a balance park and a provider park are distinguishable
- [ ] Refunds appear as their own rows, never as adjusted debits
- [ ] No provider normaliser is applied to any figure, and the console states that weights are set by Grading Mode alone
- [ ] Operator access is authenticated separately from Candidate access
- [ ] Screen 08 renders every reading above

## Blocked by

- ISSUE-0009 — every reading is derived from the ledgers that slice creates
