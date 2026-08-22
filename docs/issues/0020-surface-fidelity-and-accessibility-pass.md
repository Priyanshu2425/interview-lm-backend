# ISSUE-0020 — Surface fidelity and accessibility pass

Status: in progress — machine half done, human half outstanding
Type: HITL
Source: design-system/DESIGN.md, PRODUCT.md, SPEC-0003 §6
Covers: PRD-0002 §36; PRD-0003 §14; PRD-0005 §16 — verified in the built surface

## What to build

Not a feature. A pass across every built screen, comparing what shipped against
`design-system/DESIGN.md` and the prototype, and checking the things only a person can.

The design settled several decisions the build must not quietly relitigate: ink
is the examination and light is everything else; violet marks designed-but-unbuilt
surfaces and appears nowhere in shipped UI; mobile is the exchange and nothing
else; semantic colour is darker than Scaler's brand palette so the Evidence Floor
bands clear contrast; there are exactly two authored motions and everything else
is state feedback.

**Why HITL:** a screen reader run, a keyboard-only pass and a fidelity comparison
are judgements. So is the copy — errors must name the problem and the recovery in
the product's own language, and the one rule a machine cannot fully police is
whether a message would send a Candidate to fix the wrong thing.

## Acceptance criteria

- [ ] Every built screen compared side by side against its prototype at 390px, 768px and 1440px; differences either justified in writing or fixed
- [ ] A keyboard-only pass completes a whole Session: choose scope, start, answer, take a hint, read the score, reach the summary
- [ ] A screen reader pass over the exchange and the summary; the posterior ridge and every band token carry a meaningful accessible name
- [x] No state anywhere is carried by colour alone — checked by viewing in greyscale
- [x] Every text and control pair measured at 4.5:1 in both themes, including the ink surface
- [x] Focus is visible on every interactive element and never trapped outside an open dialog
- [x] `prefers-reduced-motion` disables both authored motions and leaves the surface fully usable
- [x] Violet appears in no shipped control; screens 06 and 07 remain unbuilt
- [ ] Copy reviewed against PRODUCT.md's language: no "progress", no difficulty claim, no fused Coverage-and-Mastery figure, no Session price quoted in advance
- [ ] Every error message names the problem and the recovery; a human confirms no message would send a Candidate to fix something that is not broken
- [ ] The QA runbook's section 09 re-run against the built surface rather than the prototype
- [ ] `design-system/DESIGN.md` updated with any token or behaviour the build settled differently

## Blocked by

- ISSUE-0017, ISSUE-0018, ISSUE-0019 — the pass needs the screens to exist

---

## Machine half — done

`frontend/tests/a11y.mjs`, 14 checks across all four built screens in both
themes. Two real defects found and fixed:

1. **`--muted` failed contrast on the selected-option ground.** `#61738e` clears
   4.5:1 on paper and on the tint, and fails at 4.29:1 on `--tint-2` — which is
   exactly where the provider descriptions sit once a Module is chosen.
   Measuring against a single background is how that hides. Now `#596a83`.
2. **The composer signalled focus with a border hue change only.** No outline,
   no shadow — colour-only signalling on the one control a keyboard user must be
   able to find. It now carries a real ring.

One finding was a **defect in the audit, not the surface**: it treated
`rgba(46,158,107,.2)` as opaque instead of compositing it over the ink rail, and
reported a 1.9:1 failure where the true ratio is 8.3:1. The audit now composites
every translucent layer down the ancestor chain. An audit that invents failures
is worse than no audit, because it trains people to ignore it.

## Human half — still outstanding

These are judgements and no test replaces them:

- [ ] A screen reader pass over the exchange and the summary — does the
      posterior ridge's label actually tell a non-sighted user what the reading is?
- [ ] Side-by-side fidelity against `design-system/` at all three widths
- [ ] Copy read aloud against PRODUCT.md's language
- [ ] A person confirming no error message would send a Candidate to fix
      something that is not broken
- [ ] `docs/qa/frontend-integration.html` worked through end to end
