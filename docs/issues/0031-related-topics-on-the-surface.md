# ISSUE-0031 — Related Topics on the surface

Status: **machine half done** — the API is ready, the placement is not chosen
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

- ~~ISSUE-0030~~ — **no longer applicable.** That dependency existed because a
  precomputed artifact could go out of date against the Corpus it described.
  ISSUE-0037 deleted the artifact: neighbours are the stored centroids of the
  Topics themselves, written in the same transaction, so there is no stale
  reading a surface could show (ADR-0021). The remaining block is the placement
  decision, which was always the real one.

## What is ready

Everything on the server side, and it was ready before this issue was written:

- `GET /v1/corpus/topics/{topic_id}/related` returns up to five neighbours,
  **ranked by the server**, each carrying `module_id` and `same_module` so the
  two kinds can be told apart without the client deciding which to show.
- A Topic with no neighbours returns `[]`, and so does a Topic whose Corpus this
  deployment does not hold. They are indistinguishable from outside on purpose:
  the surface renders nothing in both cases and nothing is honest in both.
- Nothing is embedded at request time, and a test asserts it.

What is missing is a screen, and inventing one is the trap this issue exists to
stop in front of.

## The question, unchanged and still unanswered

Which of A, B and C above — and the answer has to carry the reason, because the
difference between them is not visual. Related Topics is a claim about the
**material**; a list of Topics beside a score is a claim about the **person**.
Placement is what decides which of the two a Candidate reads.
