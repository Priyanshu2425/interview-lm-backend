# ISSUE-0015 — The live exchange

Status: resolved
Type: AFK
Source: SPEC-0003 §5, design-system/screens/02-topic-visit.html; PRD-0003, ADR-0011
Covers: PRD-0003 §5, §6, §7, §8, §11, §14, §15, §16, §17; PRD-0005 §7

> **Note (2026-08-27).** `design-system/` was removed from this repository. The
> surface is built from the design files outside it — see `DESIGN.md` and
> `AGENTS.md`. Paths naming `design-system/` below are kept as written: they
> record what this was built against at the time, and they resolve in git
> history rather than in the working tree.

## What to build

The screen the product exists for. A question arrives, the Candidate answers,
and the surface renders whatever the graph parks on next — a probe, a hint, a
closed Topic, or the end of the Session.

**The turn loop is the whole of this slice**, and it follows ADR-0011 exactly:

```
submit → POST /v1/sessions/{id}/turns   [long-running]
              ├─ 200 kind=probe|hint      → append to the thread, reopen the composer
              ├─ 200 kind=question        → a new Topic opened; render its result first
              ├─ 200 kind=session_ended   → go to the summary
              ├─ 200 kind=session_parked  → render the reason, offer the recovery
              └─ timeout / network        → GET the Session and resume from its state
```

The **idempotency key is generated once per composed answer and reused on every
retry**. A mashed submit button, a dropped connection and a browser refresh must
all converge on one Answer Turn, because the thing on the other side is a
permanent write.

On mobile the screen is purely question and answer: header, exchange, composer,
nothing else. Cost, Grading Mode and the Topic list live behind one pull-up
sheet. On desktop the same file gains the Session rail and the numbered Visit
rail, both sharing the exchange's ink ground.

The composer is disabled while a turn is in flight and shows that the request is
running — never disabled by a timer. A turn that times out is a park, not an
error, and recovers through the same path an interruption already uses.

## Acceptance criteria

- [x] The opening question renders from the start response with its Grading Mode chip
- [x] Submitting an answer disables the composer, shows the request running, and re-enables it on the next park
- [x] A `probe` or `hint` appends to the thread and reopens the composer without losing the earlier turns
- [x] The idempotency key is generated once per composed answer; a double submit produces one Answer Turn and one Evidence row
- [x] A refresh mid-turn recovers by reading `GET /v1/sessions/{id}` and resuming, with no answer lost
- [x] A `session_parked` response renders the API's own message and its recovery action; a credits park offers a top-up, a provider park does not
- [x] `session_ended` navigates to the summary carrying the closing Visit's result
- [x] Asking for a hint is possible at any point and does not end the Topic
- [x] The turn thread shows follow-ups and hints distinctly, and states that the whole thread resolves into one score
- [x] No Answer Key or grading material appears at any point before the Topic is scored
- [x] Mobile at 390px shows only header, exchange and composer, with the composer in view without scrolling
- [x] Desktop at 1440px shows both rails on the exchange's ground, and the Visit list reflects real Visit state
- [x] The running total is reachable from the sheet via `GET /v1/sessions/{id}/spend`
- [x] Keyboard: the composer submits on the documented shortcut and focus returns to it after each park

## Blocked by

- ISSUE-0014 — the shell, the API client and the token layer

---

**Resolved.** Built in the `frontend/` repository and verified by
`frontend/tests/run.mjs` — 44 checks driving a real browser against the real API
and a real Postgres. Criteria requiring a human eye (design fidelity, screen
reader, greyscale) are ticked as machine-verified only and are re-checked by
ISSUE-0020, which is HITL for exactly that reason.
