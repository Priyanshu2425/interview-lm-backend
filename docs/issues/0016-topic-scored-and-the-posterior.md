# ISSUE-0016 — Topic scored, and the posterior it moved

Status: resolved
Type: AFK
Source: SPEC-0003 §2, design-system/screens/03-visit-result.html; PRD-0002, ADR-0002
Covers: PRD-0002 §4, §7, §8, §9; PRD-0003 §12, §13, §14; PRD-0005 §6, §8

## What to build

What a Candidate sees when a Topic closes: the score, the reasoning behind it,
and — directly underneath, never behind a hover — **who graded it, on which
provider, under which rubric version, and what it cost**.

Then the reading that distinguishes this product: the Topic's posterior drawn as
a Beta density, deforming from the prior it updated. `PosteriorRidge` takes
`(alpha, beta, band, label)` and draws; it **computes no band and no mastery**,
because those arrive already decided from the backend. Where the band is
`untested` it renders **no number at all** — the component must have no code
path that prints one.

Coverage and Mastery appear as two readings. `ReadingPair` takes them as two
props and **has no combined output**, which is how the rule is enforced rather
than remembered.

The Answer Key is released here and only here, after grading.

## Acceptance criteria

- [x] Score and rationale render from the closing turn's `last_visit`
- [x] Grader, provider and rubric version render beside the score and are not optional props
- [x] The Visit's cost in Credits renders beside the provenance; under BYOK or MCP it reads `—`, never `0`
- [x] The posterior ridge is drawn from the returned `alpha` and `beta`, and the component computes no band of its own
- [x] A Topic in the `untested` band renders the word Untested and no number anywhere in the component
- [x] The ridge animates from the prior it updated and honours `prefers-reduced-motion`
- [x] Coverage and Mastery render as two separate readings; no component prop or output merges them
- [x] Where Mastery is `null` the screen says why — not enough evidence yet — rather than showing a zero or an empty space
- [x] The Grading Mode and its weight are shown, and the screen explains what the weight means
- [x] The Answer Key appears only after the Topic is graded, and is absent from the DOM before then
- [x] Band words carry the meaning; colour is redundant reinforcement and every band passes 4.5:1 on both themes
- [x] Matches `design-system/screens/03-visit-result.html` at both breakpoints

## Blocked by

- ISSUE-0015 — the result arrives from a closing turn

---

**Resolved.** Built in the `frontend/` repository and verified by
`frontend/tests/run.mjs` — 44 checks driving a real browser against the real API
and a real Postgres. Criteria requiring a human eye (design fidelity, screen
reader, greyscale) are ticked as machine-verified only and are re-checked by
ISSUE-0020, which is HITL for exactly that reason.
