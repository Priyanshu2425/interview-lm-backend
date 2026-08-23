# ISSUE-0021 — Notebook ingest: one source becomes a conformant Corpus

Status: resolved
Type: AFK
Source: SPEC 2026-08-21 Notebook Adapter; ADR-0015, ADR-0007, ADR-0005, ADR-0010; PRD-0001
Covers: spec §Architecture, §Contract conformance, §Why Module equals source

## What to build

The thinnest complete path for a Corpus nobody divided: a Candidate's own
markdown file becomes a **Module** with **Topics**, and a Session runs on it.

A third **Adapter** — the **Notebook Adapter** — sits beside the InterviewLM and
markdown-folder Adapters and imports neither. Its pipeline:

    extract → chunk → embed → cluster → label → freeze → dossier build → validate

**Extract** yields text plus a **locator** for every span — `{source_id, page,
char_start, char_end}`. Markdown and plain text only in this slice; page is
always 1. The locator is not decoration: it is what a citation will point at, and
every later slice depends on it existing from the first ingest.

**Chunk** at 500–800 tokens, splitting on structure where structure exists
(headings, paragraph boundaries), no overlap. Each chunk carries a `chunk_id`, a
content hash, its locator and its embedding.

**Embed** through a port, not a provider. This slice ships a deterministic stub
embedder so the pipeline is testable without a network or a bill; ISSUE-0026
replaces it. The port takes a list of texts and returns vectors, and nothing
upstream of it knows which implementation answered.

**Cluster** the chunks of one source into Topics, sized against the 10k-token
dossier budget. A cluster over budget splits at the chunk boundary nearest its
median; a cluster under the floor merges into its nearest neighbour. Both are
arithmetic. The clusterer does not decide how big a Topic may be — the budget
does.

**Label** each cluster with one cheap model call returning a Topic title. On
failure the title falls back to the first heading, or the first line of the
earliest chunk; labelling never blocks ingest. Ground Truth detection is
ISSUE-0024 — every Topic here declares Text-grounded.

**Freeze** mints `topic_id` and persists it with the cluster centroid and the set
of chunk hashes that formed it. `module_id` is `hash(notebook_id, source_id)`.
Nothing in this slice re-clusters; ISSUE-0022 is where that promise is tested.

**Order** comes from position, never from the clusterer: Module order is upload
index, Topic order is the offset of the cluster's earliest chunk, leaf order is
locator order.

**Dossier build** concatenates a Topic's chunks in locator order — not cluster
order — and caches the result whole. The Interviewer still loads it by
`topic_id`, as ADR-0005 requires; no similarity query runs at question time.

**Validate** against `corpus/contract.py` and report every violation rather than
the first, reusing the existing conformance check rather than a second one.

One uploaded source is one Module (ADR-0015). Clustering therefore runs inside a
source and cannot move a boundary in a source it is not looking at.

Chunks, embeddings, centroids and dossiers live in the **content** schema — the
deletable side of ADR-0010.

## Acceptance criteria

- [ ] A notebook of one markdown file ingests to a Corpus that passes `corpus/conformance.py` with zero violations
- [ ] The Notebook Adapter imports neither the InterviewLM Adapter nor the markdown-folder Adapter, and the backbone imports none of the three
- [ ] Every chunk carries a locator whose `char_start`/`char_end` re-slice the original source text exactly
- [ ] No Topic dossier exceeds 10k tokens, and ingest reports p50 and max
- [ ] A source small enough for one chunk yields exactly one Topic and validates
- [ ] A cluster over budget splits at a chunk boundary; no chunk is ever divided by the splitter
- [ ] Topic order equals the offset order of each cluster's earliest chunk, verified against a fixture with clusters deliberately out of source order
- [ ] Dossier text is chunks in locator order, byte-identical to the source spans concatenated
- [ ] Ingesting the same fixture twice yields identical `topic_id`s and byte-identical dossiers
- [ ] A failed label call produces the deterministic fallback title and ingest still completes
- [ ] Every Topic reports Text-grounded in this slice; no Topic claims Ground Truth
- [ ] The embedder is reached through a port; swapping the stub for another implementation touches no pipeline code
- [ ] The picker lists the notebook's Module, and a Session scoped to it asks a question from one of its Topics
- [ ] Store tests run against real Postgres

## Blocked by

- None — can start immediately
