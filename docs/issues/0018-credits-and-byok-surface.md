# ISSUE-0018 — Credits and BYOK on the surface

Status: resolved
Type: AFK
Source: SPEC-0003, design-system/screens/05-credits.html; PRD-0005, ADR-0008, ADR-0013
Covers: PRD-0005 §1, §2, §6, §9, §12, §13, §14, §16, §17, §18, §19, §20, §22, §23

## What to build

The balance, with the definition of a Credit stated on the same screen: one US
cent of what the provider charged us. The per-Visit ledger, including a Topic
that was never graded but still cost money, and its refund as **its own line**
rather than a number quietly edited.

Key attachment, which accepts **OpenRouter keys only** and validates live at
attach so a dead key fails here rather than mid-Session. The stored key is shown
by fingerprint; the plaintext is never requested back from the server because no
route returns it.

And the part that matters most: **both failure messages, and the rule between
them**. A credit failure names Credits and offers a top-up. A BYOK failure names
the provider and the reason and **contains no reference to Credits at all** —
the surface renders whatever `code` and `message` the API returns and must never
compose its own billing copy, because that is where the rule leaks.

Under BYOK the balance reads `—`, not `0`. Zero reads as "it was free" rather
than "this ledger does not apply to you".

## Acceptance criteria

- [x] Balance renders with the Credit definition beside it, and reads `—` under BYOK
- [x] The ledger renders grants, debits and refunds as distinct rows in order
- [x] A refund appears as its own row; no row is ever shown as an adjusted debit
- [x] A Topic Visit that cost money but was never graded is visible in the ledger
- [x] The low-balance state is rendered from the API's own flag, not computed in the browser
- [x] Attaching a key calls the API; a raw vendor key is refused and the API's message is shown verbatim
- [x] The screen states that only OpenRouter keys are accepted, and there is no field that would take another
- [x] A key is displayed by fingerprint only; the plaintext appears nowhere in the DOM, in state, or in storage
- [x] Removing a key falls back to Credits without touching the Candidate's record
- [x] Every failure message is rendered from the API's `code` and `message`; the surface composes no billing copy of its own
- [x] A rendered BYOK failure contains no occurrence of the word "credit" — asserted as a test over the DOM
- [x] Under BYOK the credits-spent reading is `—` rather than `0`
- [x] No Session cost is quoted in advance anywhere on the screen
- [x] Matches `design-system/screens/05-credits.html` at both breakpoints

## Blocked by

- ISSUE-0014 — the shell and the API client. Independent of the exchange.

---

**Resolved.** Built in the `frontend/` repository and verified by
`frontend/tests/run.mjs` — 44 checks driving a real browser against the real API
and a real Postgres. Criteria requiring a human eye (design fidelity, screen
reader, greyscale) are ticked as machine-verified only and are re-checked by
ISSUE-0020, which is HITL for exactly that reason.
