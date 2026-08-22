# ISSUE-0031 — Related Topics on the surface

Status: open
Type: **HITL**
Source: ISSUE-0029; DESIGN.md; AGENTS.md §"The surface holds no invariant"
Covers: where sideways exploration appears to a Candidate, and whether it should

## Why this one needs a human

`design-system/` never drew this. There is no screen, no component and no
placement for "what else relates to this?", and inventing one is exactly the
trap ISSUE-0025 stopped in front of: a surface that ships a control the design
never sanctioned is a surface nobody can compare against its source of truth.

There is also a product question underneath the visual one, and it is the more
important of the two.

**Where does a Candidate meet a Related Topic without it becoming a suggestion?**
This product's central claim is that Coverage and Mastery are two readings and
never one figure, and that untested is not weak. A list of related Topics
rendered next to a score reads as *"and you should do these next"* — which is
adaptive Session termination and Topic recommendation, neither of which exists,
both of which are deferred in FUTURE-PIPELINE for want of calibration data.
Related Topics is a statement about the **material**, not about the Candidate,
and the placement has to carry that difference or the product starts making a
claim it cannot support.

Three placements are defensible and they are not equivalent:

**A. In the Session summary, as a map of the material.** Furthest from the
score, closest to the truthful reading: here is how what you were examined on
connects to what you were not. Says nothing about what to do next.

**B. On the Topic Visit result, after a Topic is scored.** Most useful moment,
most dangerous framing — it is the exact spot where a list reads as a
recommendation, and where a Candidate scoring badly is handed neighbours to
misread as remediation.

**C. On the Module picker, before a Session.** Reframes it as scope-setting
rather than feedback: these Modules touch each other, choose accordingly. It
changes nothing about how a Session runs and makes no claim about the person.

## What to build once that is decided

Everything below is independent of which placement wins and can be built either
way:

- The surface reads neighbours from the API and renders what the server decided,
  computing no ordering and no threshold of its own (ADR-0009)
- Same-Module and cross-Module neighbours are visually distinguishable, because
  they mean different things: one is "what leads into this", the other is the
  sideways connection this whole line of work was for
- A Topic with no neighbours renders as nothing at all — no empty state, no
  explanatory copy. A deployment with no index is indistinguishable from a Topic
  that simply has none, and both are honest
- The accessibility pass ISSUE-0020 applies to every route applies here

## Acceptance criteria

- [ ] The placement is chosen by a human and recorded, with the reason it does not read as a recommendation
- [ ] Related Topics never appear where they could be read as what to study next, unless that reading is explicitly accepted and written down
- [ ] The surface renders server-decided neighbours and computes no ordering or threshold of its own
- [ ] Same-Module and cross-Module neighbours are distinguishable
- [ ] A Topic with no neighbours, and a deployment with no index, both render nothing
- [ ] No Coverage-and-Mastery figure is combined, implied or introduced anywhere in the new copy
- [ ] `npm run verify` passes, and `npm run audit` reports no new finding

## Blocked by

- ISSUE-0030 — a surface that can show a stale reading before staleness is legible is a surface that shows a wrong one
