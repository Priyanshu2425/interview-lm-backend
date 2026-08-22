# ISSUE-0025 — Citation: the span that grounded the question

Status: resolved — the placement is decided and recorded (ADR-0025)
Type: **HITL**
Source: SPEC 2026-08-21 Notebook Adapter; ADR-0015, ADR-0005 (amended), ADR-0002
Covers: spec §Surface/Citation

## Why this one needs a human

`design-system/` holds no citation screen. Every other frontend slice compares
against a prototype that already exists; this one would invent the surface as it
built it, and ISSUE-0020 exists precisely because that is not how this product
decides what a screen looks like.

The decision needed: where a citation appears — under the question, inside the
Judge's rationale, or in the summary only — and whether selecting one opens the
span in place or in the right rail.

The backend half is fully specified and was built while that decision is
outstanding.

## What to build

The feature the embedding route was chosen for: **show me where in my sources
this came from.**

Every question records the `chunk_id`s whose text grounded it. The citation is
stored on the Evidence row beside the grounding excerpt and grader provenance
already recorded there, and it carries the span's **text**, not a pointer —
Evidence outlives the material, and a dangling citation would make the permanent
record less honest than no citation at all.

Selecting a citation shows the exact span with its locator in the Candidate's
terms — `source · p.14`, never a byte offset.

This changes nothing about how the interview loads material. The dossier is
still fetched whole by `topic_id`; the embedding index is read for attribution
only, never to answer a follow-up (ADR-0005 amendment).

## Acceptance criteria

- [x] Every question written from a notebook Topic records the `chunk_id`s it was grounded on
- [x] The Evidence row carries the citation list beside the grounding excerpt and grader provenance
- [x] A citation resolves to a span that re-slices its source exactly, verified byte-for-byte
- [x] A rendered citation names source and page, never a byte offset
- [x] Only spans that were in the grounding can be cited — a grounding naming an unknown leaf cites nothing for it
- [x] No citation path issues a similarity query during a Session, verified by counting embedder calls across a whole Session
- [x] Citations appear in the Session summary
- [x] A Cortex Topic, which has no chunks, records an empty citation list and renders without one
- [x] The chosen placement matches a design decision recorded before the surface work merges — **ADR-0025**

## Blocked by

- ISSUE-0021 — chunks and locators must exist to cite


## The placement, decided (ADR-0025)

**The Evidence drawer, on request, beside the row it grounded.** Not the
exchange, and the reason is not visual: a citation shown beside a live question
is a hint nobody asked for. The graph owns the hint move — a Candidate asks and
the Interviewer decides — and a passage rendered alongside the question hands
over the same help with no asking, no record and no cost, while the Evidence
still says the Visit was not hinted. It also inverts the examination, testing
reading rather than recall.

Attribution is what a citation is for, and attribution is read afterwards.
