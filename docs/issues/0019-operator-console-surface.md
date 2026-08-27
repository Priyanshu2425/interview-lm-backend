# ISSUE-0019 — Operator console on the surface

Status: resolved
Type: AFK
Source: SPEC-0003, design-system/screens/08-operator.html; PRD-0005 §7, ADR-0014
Covers: PRD-0005 §38, §39, §40, §41, §42, §43, §44, §45

> **Note (2026-08-27).** `design-system/` was removed from this repository. The
> surface is built from the design files outside it — see `DESIGN.md` and
> `AGENTS.md`. Paths naming `design-system/` below are kept as written: they
> record what this was built against at the time, and they resolve in git
> history rather than in the working tree.

## What to build

The internal surface, authenticated separately from Candidate access.

**Pool headroom leads**, shown against its alert threshold, because it is the
only figure that can strand a Candidate mid-Session. Beside it, float as a
working-capital figure — one-way, recoverable as service and not as cash.

Then the two readings that exist to make a bug visible before it costs money:
the **unpriced call rate** per Provider, and the **drawdown divergence** between
the provider's reported usage and our own summed call costs. The divergence is
signed, because its direction says which failure you have.

Per-Provider spend and failure rates, and spend rolling up call → Visit →
Session → Candidate. All of it reads off records that already exist; the screen
adds no instrumentation.

BYOK and MCP Sessions render `—`, never `0`. The console states that weights are
set by Grading Mode alone and that no normaliser is applied to any figure.

## Acceptance criteria

- [x] The console is unreachable without an operator token, and a Candidate session does not grant one
- [x] Pool headroom renders against its threshold with the alert state from the API
- [x] Float renders as a working-capital figure and is described as one-way
- [x] Unpriced call rate renders per Provider and is visibly distinct from a zero-cost call
- [x] Drawdown divergence renders signed, and the screen explains what each direction means
- [x] Per-Provider spend, cost per Visit and failure rate render from the API
- [x] Session rollup renders, with BYOK and MCP rows showing `—` rather than `0`
- [x] Sessions that ended on a balance park and a provider park are distinguishable
- [x] Refunds appear as their own entries, never as adjusted debits
- [x] The screen states that no provider normaliser is applied
- [x] Dense tables keep their columns on narrow screens and gain the scroll affordance
- [x] Matches `design-system/screens/08-operator.html` at both breakpoints

## Blocked by

- ISSUE-0014 — the shell and the API client. Independent of the exchange.

---

**Resolved.** Built in the `frontend/` repository and verified by
`frontend/tests/run.mjs` — 44 checks driving a real browser against the real API
and a real Postgres. Criteria requiring a human eye (design fidelity, screen
reader, greyscale) are ticked as machine-verified only and are re-checked by
ISSUE-0020, which is HITL for exactly that reason.
