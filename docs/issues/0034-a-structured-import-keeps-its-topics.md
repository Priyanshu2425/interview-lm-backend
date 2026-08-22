# ISSUE-0034 — A structured import keeps the Topics it arrived with

Status: open
Type: AFK
Source: SPEC-0006 §Structure is given or derived; ADR-0015; ISSUE-0029
Covers: importing authored material without re-deriving its divisions

## What to build

The Notebook Adapter *mints* `topic_id`s by clustering, because a Candidate's
file arrives with no divisions. Authored material arrives with its own — the
Scaler course has 71 Topics — and running the clusterer over it would produce a
different 71 and mean something different by every one.

A Source declares whether it carries divisions, and exactly one stage changes:

- **Derived** — the existing path. Cluster, mint ids.
- **Given** — skip clustering entirely. Topics, order and titles come from the
  source, and `topic_id` is derived from the source's own id so that importing
  the same material twice is the same Corpus.

Everything before that stage (extract, chunk, embed) and everything after it
(freeze, dossier build, validate) is shared. This is not a second pipeline; it is
ISSUE-0029's rule — *structure is given, never derived* — applied to storage
rather than to a file.

The import lands in a Corpus like any other, so it is metered, atomic per Source
and conformance-checked by machinery that already exists.

## Acceptance criteria

- [ ] A Source declares given or derived structure, and derived stays the default
- [ ] A given import produces `topic_id`s identical to the source's, none minted
- [ ] The clusterer and the id-minter are **not reached** by a given import, verified by call count
- [ ] Importing the same material twice yields identical ids and byte-identical dossiers
- [ ] Topic order comes from the source, not from the clusterer
- [ ] The imported Corpus passes `corpus/conformance.py` with zero violations
- [ ] An import is atomic per Source and metered like any other ingest
- [ ] A Session scoped to an imported Module asks a question from one of its Topics

## Blocked by

- ISSUE-0032 — a shared Corpus is what this imports into
