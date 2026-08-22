# ISSUE-0017 — Session summary and the Candidate's record

Status: resolved
Type: AFK
Source: SPEC-0003, design-system/screens/04-session-summary.html; PRD-0002
Covers: PRD-0002 §1, §2, §3, §5, §6, §10, §34, §36; PRD-0003 §18, §19, §21

## What to build

The screen that refuses the single number hardest.

Coverage reads as Topics examined against the whole Corpus. Mastery reads as how
many look solid and how many look weak, among those with enough evidence to say.
**They are never multiplied together**, and the response model has no field that
would let them be.

Each examined Topic carries its own distribution, so width tells the reader how
much to trust the reading. Topics below the Evidence Floor say *Untested* and
carry no figure.

The largest section on the page is the one a conventional summary cannot express:
**the Topics never asked about**, grouped by Module, with whether each Module
carries Ground Truth. This is the product's central claim and it should read as
the page's subject rather than a footnote.

The weakest-Topics list comes from `GET /v1/candidates/{id}/weakest` and
**excludes untested Topics** — they are unknown, not weak, and ranking them last
is the same conflation the model exists to prevent.

## Acceptance criteria

- [x] Coverage and Mastery render as two readings from `GET /v1/sessions/{id}/summary`
- [x] No element on the page combines them, and a search of the rendered DOM finds no fused percentage
- [x] Coverage is described as effective Topic Visits wherever it is shown
- [x] Every examined Topic shows its band word, and only Topics above the floor show a number
- [x] Per-Topic distributions render from the returned `alpha` and `beta`
- [x] The untested section reports real counts per Module and whether each carries Ground Truth
- [x] The untested count and the examined count sum to the Corpus total
- [x] The weakest list renders from the API and contains no untested Topic
- [x] Session duration and provider are shown, since Sessions are only comparable at the same duration
- [x] Spend for the Session renders, reading `—` under BYOK or MCP
- [x] A Candidate with no Sessions yet sees an empty state that teaches the screen rather than an error
- [x] Dense tables keep their columns at 390px and gain the scroll affordance rather than collapsing
- [x] Matches `design-system/screens/04-session-summary.html` at both breakpoints

## Blocked by

- ISSUE-0016 — the readings and the ridge component

---

**Resolved.** Built in the `frontend/` repository and verified by
`frontend/tests/run.mjs` — 44 checks driving a real browser against the real API
and a real Postgres. Criteria requiring a human eye (design fidelity, screen
reader, greyscale) are ticked as machine-verified only and are re-checked by
ISSUE-0020, which is HITL for exactly that reason.
