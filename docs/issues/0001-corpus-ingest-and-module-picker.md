# ISSUE-0001 — Corpus ingest and the Module picker

Status: ready-for-agent
Type: AFK
Source: PRD-0001; ADR-0005, ADR-0007, ADR-0009
Covers: PRD-0001 §1, §18, §26; PRD-0003 §1

## What to build

The first end-to-end path: a **Corpus** produced by the Cortex **Adapter** is
validated at ingest, loaded by `topic_id`, served over HTTP, and rendered as the
Module picker a **Candidate** chooses scope from.

The Adapter emits a Module → Topic → leaf hierarchy with stable ids, explicit
ordering, and per-leaf declaration of whether it carries **Ground Truth**. The
contract is validated at ingest and rejects a Corpus that violates it, rather
than discovering the violation at question time. **Ground Truth is optional** —
its absence is expressed as a **Grading Mode** ceiling, never as a validation
failure.

The **Dossier Loader** takes a `topic_id` and returns that Topic's
content-bearing leaves in order. It is the only component that knows how Corpus
content is stored, and there is no vector store, no embedding step and no
retriever (ADR-0005) — a dossier is a file read.

This slice also establishes the surface's token layer by porting the prototype's
design system, so later slices add screens rather than each inventing a
vocabulary.

## Acceptance criteria

- [ ] Ingesting the real scraped Corpus succeeds and reports 2 Tracks, 15 Modules, 71 Topics
- [ ] A Corpus with a duplicate `topic_id`, a missing `order`, or an unparseable leaf is rejected at ingest with a message naming the offending id
- [ ] A Module with no Answer Keys ingests successfully and reports a reduced Grading Mode ceiling, not an error
- [ ] Re-ingesting unchanged material reproduces identical Module and Topic ids
- [ ] Loading a known `topic_id` returns every content-bearing leaf of that Topic, in order
- [ ] Loading a Topic whose leaves are all non-text returns an explicit empty dossier, distinguishable from not-found
- [ ] Loading an unknown `topic_id` is an explicit not-found, not an empty dossier
- [ ] Every Topic in the real Corpus loads under the documented token budget; the maximum observed is reported
- [ ] `GET /v1/corpus/modules` returns per-Module Topic counts and Answer Key counts read from the Corpus, not hard-coded
- [ ] Screen 01 renders those real counts, and the Ground-Truth-in-scope note updates as Modules are selected
- [ ] The picker gates its primary action: with no Modules selected the control is genuinely disabled, and activating it does nothing
- [ ] No difficulty value is read, derived, stored or displayed anywhere in this slice

## Blocked by

None — can start immediately.
