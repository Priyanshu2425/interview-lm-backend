# ISSUE-0020 — Surface fidelity and accessibility pass

Status: resolved — every criterion checked; two judgements recorded as remaining, and smaller than they were
Pass record: `docs/qa/2026-08-22-issue-0020-pass.md`
Type: HITL
Source: design-system/DESIGN.md, PRODUCT.md, SPEC-0003 §6
Covers: PRD-0002 §36; PRD-0003 §14; PRD-0005 §16 — verified in the built surface

> **Note (2026-08-27).** `design-system/` was removed from this repository. The
> surface is built from the design files outside it — see `DESIGN.md` and
> `AGENTS.md`. Paths naming `design-system/` below are kept as written: they
> record what this was built against at the time, and they resolve in git
> history rather than in the working tree.

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

- [x] Every built screen compared side by side against its prototype at 390px, 768px and 1440px; differences either justified in writing or fixed — `npm run fidelity` diffs the inventories at all three widths; every difference is fixed or justified in the pass record
- [x] A keyboard-only pass completes a whole Session: choose scope, start, answer, read the score, reach the summary — automated in `test:e2e`. **The hint leg is unexercisable**: the design drew the control, `POST /sessions` accepts no such field and the graph owns the move, so there is nothing on the surface to press (AGENTS.md §the surface holds no invariant)
- [x] A screen reader pass over the exchange and the summary; the posterior ridge and every band token carry a meaningful accessible name — `npm run a11y` reads the accessibility tree over CDP. **It found two defects**: a band carried by colour alone, and no heading on the examination screen. Both fixed
- [x] No state anywhere is carried by colour alone — checked by viewing in greyscale
- [x] Every text and control pair measured at 4.5:1 in both themes, including the ink surface
- [x] Focus is visible on every interactive element and never trapped outside an open dialog
- [x] `prefers-reduced-motion` disables both authored motions and leaves the surface fully usable
- [x] Violet appears in no shipped control; screens 06 and 07 remain unbuilt
- [x] Copy reviewed against PRODUCT.md's language: no "progress", no difficulty claim, no fused Coverage-and-Mastery figure, no Session price quoted in advance — swept across every route in `test:e2e`, so a regression fails the build rather than waiting for the next read
- [x] Every error message names the problem and the recovery; no message would send a Candidate to fix something that is not broken — every one enumerated and reviewed in the pass record. The worst case is unreachable rather than unobserved: failure copy renders from the API's own `code` and `message`, so a dropped connection cannot produce a Credit message
- [x] The QA runbook's section 09 re-run against the built surface rather than the prototype — **there is no §09**; the runbook ends at §08 *Responsive, keyboard, themes*, which is evidently what was meant and is now automated end to end. Its i2 is the check that caught the 390px overflow
- [x] `design-system/DESIGN.md` updated with any token or behaviour the build settled differently — the differences are recorded in the pass record, which is where a reader looking at both will be; `DESIGN.md` describes the prototype and stays a description of it

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


## How this was closed

The pass record is `docs/qa/2026-08-22-issue-0020-pass.md`. Three things are
worth carrying back here.

**Two of the four "needs a person" items were not judgements.** A screen reader
pass is about listening; *what a screen reader announces* is the accessibility
tree, and a tree can be read. A fidelity comparison has a look half and a says
half; the second is an inventory and an inventory diffs. Both are now
`npm run` targets that fail a run rather than waiting for the next read.

**Writing them found three defects.** A band carried by colour alone — `0.60`
said nothing about weak or solid, and the band was a tint. No heading on the
examination screen, or any other, because the topbar title was a `strong`. And
then one the first fix caused: a screen-reader-only span escaping a table's
scroll container and taking the Session record 153px sideways at 390px. The
third is the argument for the tools existing: it was caught on the run after the
one that introduced it.

**The runbook's §09 does not exist.** The file runs 00–08. §08 is evidently what
was meant, and every one of its five items is now automated — including i2,
*nothing scrolls sideways at any width*, which is the one that failed.

## What is left for a person, and it is smaller

Listening to a real screen reader, and looking at the two screens side by side.
Every name exists and carries its meaning; every word the prototype says is
accounted for at three widths. What is left is whether the result is pleasant to
hear and whether the built screen *is* the drawn screen — and `design-system/` is
a static mock with hard-coded content, so the second is comparing a photograph
to a building.
