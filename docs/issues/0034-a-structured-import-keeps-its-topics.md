# ISSUE-0034 — A structured import keeps the Topics it arrived with

Status: resolved
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

- [x] A Source declares given or derived structure, and derived stays the default
- [x] A given import produces `topic_id`s identical to the source's, none minted
- [x] The clusterer and the id-minter are **not reached** by a given import, verified by call count
- [x] Importing the same material twice yields identical ids and byte-identical dossiers
- [x] Topic order comes from the source, not from the clusterer
- [x] The imported Corpus passes `corpus/conformance.py` with zero violations
- [x] An import is atomic per Source and metered like any other ingest
- [x] A Session scoped to an imported Module asks a question from one of its Topics

## Blocked by

- ISSUE-0032 — a shared Corpus is what this imports into

## Not reached, and nothing to reach

The given branch lives in its own module and **imports** no clusterer and no
id-minter. That is stronger than not calling them: a rule held only by a code
path that happens not to be taken is a rule the next edit re-opens without
noticing. Two tests hold it — one monkeypatches both functions to raise, the
other asserts the module's namespace does not carry them.

## Two things travel that were not obvious

**Leaf kind.** Ground Truth decides a Module's Grading Mode ceiling, so an
import that dropped it would silently downgrade every imported Module to model
judgment and report nothing. `GivenLeaf` carries `kind` and `answers_leaf_id`,
and a leaf that answers another points at that leaf's first span.

**Module id.** Session scope is keyed on `module_id`, so a Module that changed
id on the way into Postgres would be a different Module to every Session that
named it. A structured import keeps the source's own.

## Chunk ids come from the leaf

Each leaf is chunked on its own, so `chunk_id` derives from the leaf's id rather
than from a running counter over the Source. That is what makes re-importing the
same material produce the same dossier byte for byte, and it keeps a prompt and
its worked answer in different chunks — the boundary ISSUE-0024 exists to hold.
Offsets are rebased onto a Topic-wide cursor, because everything downstream
reads a Topic's chunks in locator order.

## How the Scaler material gets in

`scripts/import_corpus.py`, one Source per Module, resumable: a Source is
deduplicated on the content *and* the structure it carries, so re-running after
an interruption costs nothing for the Modules already in. `POST
/operator/corpora/{id}/import` is the same thing over the wire.
