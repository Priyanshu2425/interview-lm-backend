# ISSUE-0014 — Surface shell and the Session setup screen

Status: resolved
Type: AFK
Source: SPEC-0003, design-system/screens/01-session-setup.html; PRD-0001, PRD-0003
Covers: PRD-0001 §25, §26; PRD-0003 §1, §2; PRD-0005 §3, §4, §5

> **Note (2026-08-27).** `design-system/` was removed from this repository. The
> surface is built from the design files outside it — see `DESIGN.md` and
> `AGENTS.md`. Paths naming `design-system/` below are kept as written: they
> record what this was built against at the time, and they resolve in git
> history rather than in the working tree.

## What to build

The first end-to-end path through the real surface: a Candidate opens the app,
sees the true Module list served by the backend, chooses scope and a duration,
and starts a Session that exists in the database.

This slice also establishes what every later screen inherits — the token layer
lifted from `design-system/assets/app.css`, the API client, the shell, and the
convention that **the surface computes nothing**. Topic counts, Answer Key
counts and the Grading Mode a scope can support all arrive already decided from
`GET /v1/corpus/modules` and `GET /v1/corpus/scope`; the prototype's hard-coded
5/7/7/5/11 and 4/5/5/3/0 must come from the Corpus so they stay true.

Provider choice is presented with each Provider's **observed cost per Topic**,
drawn from `GET /v1/providers/prices` and labelled as history. The screen states
plainly that a Session's total cannot be quoted in advance, because it cannot.

The primary action is genuinely disabled with no Modules chosen — the prototype
had this wrong at first, and a control that looks disabled while still working
is worse than no control.

## Acceptance criteria

- [x] The Module list renders from the API; no Topic or Answer Key count is hard-coded anywhere in the surface
- [x] Selecting and deselecting Modules updates the scope readout from `GET /v1/corpus/scope`, not from arithmetic in the browser
- [x] With no Modules selected the start control is a real `disabled` control and activating it does nothing
- [x] A Module with no Answer Keys is selectable, and the screen says its questions will be marked against Topic text
- [x] Duration is chosen before the Session begins and is sent with the start request
- [x] Provider options show observed cost per Topic, labelled as history rather than a forecast
- [x] The screen states that a Session's total cost cannot be quoted in advance
- [x] Starting a Session calls `POST /v1/sessions` and navigates to the exchange with the returned `session_id`
- [x] A failed start renders the API's error message rather than a generic failure
- [x] No difficulty control, label or value appears anywhere on the screen
- [x] The design tokens are lifted from `design-system/assets/app.css` rather than reinvented, and `design-system/DESIGN.md` remains their source of truth
- [x] The screen matches `design-system/screens/01-session-setup.html` at 390px and 1440px, with no horizontal overflow at either
- [x] Keyboard: every control reachable, focus visible, the Module list operable without a mouse

## Blocked by

None — the backend routes it consumes already exist and are tested.

---

**Resolved.** Built in the `frontend/` repository and verified by
`frontend/tests/run.mjs` — 44 checks driving a real browser against the real API
and a real Postgres. Criteria requiring a human eye (design fidelity, screen
reader, greyscale) are ticked as machine-verified only and are re-checked by
ISSUE-0020, which is HITL for exactly that reason.
