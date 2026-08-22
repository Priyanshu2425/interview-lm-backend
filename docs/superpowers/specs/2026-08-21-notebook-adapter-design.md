# Notebook Adapter — examining a Candidate on sources they brought

Date: 2026-08-21
Status: implemented as ISSUE-0021–0027, except the two decisions ISSUE-0025 and
ISSUE-0026 are waiting on (citation placement; the BYOK gap, ADR-0016)
Amends: ADR-0005 (additive), ADR-0007 (see ADR-0015)
Depends on: PRD-0001, PRD-0002, PRD-0003, PRD-0005, ADR-0003, ADR-0010

## Problem Statement

The backbone examines a Candidate on a Corpus and keeps a durable record of what
they could explain. Today exactly one Corpus exists — a scrape of Scaler Cortex —
and it arrives pre-divided: Cortex supplies Modules, Topics, curriculum order and
23 Answer Keys, for free.

A Candidate who is preparing from their own material gets none of that. Their
sources are PDFs, notes and pages. There is no Module, no Topic, no order, and no
Ground Truth. The machinery that would examine them is already built and idle.

ADR-0007 anticipated this: the Interviewer is corpus-agnostic behind an Adapter
contract, and `scripts/scrape.mjs` is the Cortex Adapter rather than the system.
That claim has never been tested by a second Source. This design tests it with
the hardest one available — material with no structure at all.

The structural problem is not extraction. It is that `topic_id` is the join key
for months of accumulated Topic Confidence, and a Source with no Topics forces
something to invent them. Anything that re-invents them on each upload does not
fail loudly; it produces Beta posteriors that quietly stop referring to what they
referred to last week.

## Solution

A second Adapter — the **Notebook Adapter** — that takes text-extractable sources
a Candidate uploads and emits a contract-conformant Corpus.

Two commitments carry the design:

**Chunks are the unit of citation.** Sources are chunked, embedded and clustered.
The embedding index exists so that a question, an answer and a Judge rationale can
each point at the exact span of the exact source that grounds them. It is an
attribution path, not a retrieval path for the interview loop.

**Topics are clustered once and frozen.** The first ingest of a source clusters its
chunks into Topics and mints their ids. No later ingest re-clusters. New chunks
attach to frozen centroids; material that fits nowhere mints a new Topic and is
recorded as a Corpus Version event. Boundaries may move, but never silently.

## Decisions Taken

| Question | Decision |
|---|---|
| Relationship to the existing product | A second Adapter on the same backbone. The Cortex Corpus, Session, Judge, Evidence tables and Credits ledger are unchanged. |
| Topic derivation | The model decides. No user confirmation step. Chunk → embed → cluster → label. |
| Ground Truth | Mined, never invented. Question/answer-shaped chunks are tagged Ground Truth (weight 1.0); everything else grades Text-grounded (0.7). A notebook with none is valid, exactly as the DSA Track is today. |
| Deletion | Content is deletable; Evidence is not. Deleting a notebook removes chunks, embeddings and dossiers, retires its Topics, and leaves Evidence rows and posteriors standing on denormalised snapshots. |
| Source types in v1 | PDF, markdown/text, URL. YouTube and audio are named and deliberately not built. |
| Ingest cost | Metered on the existing ledger alongside Session spend. No quote, no confirmation gate. An insufficient balance refuses ingest before spending and names the shortfall. |
| Module | One uploaded source is one Module. |

## Why Module equals source

Module is the unit of Session scope: the Candidate picks Modules before the first
question. Making a Module a source document buys three things.

Clustering runs *within* a source rather than across the notebook, so adding a
fifty-first PDF cannot move a boundary inside the first fifty. The picker shows
names the Candidate recognises, because they are the names of files they uploaded.
And the only case that needs centroid matching at all is a changed version of a
source already ingested.

The cost is real and accepted: a concept spread over three PDFs appears as three
Modules. Thematic Modules that cross sources were considered and rejected, because
their membership shifts whenever a source is added.

## Architecture

### Ingest pipeline

    extract → chunk → embed → cluster → label → freeze → dossier build → validate

**Extract.** Local and free. PDF, markdown/text and URL yield text plus a
**locator** for every span: `{source_id, page, char_start, char_end}`. The locator
is the reason the embedding route was chosen; it is what a citation points at.

*Amended during implementation (ISSUE-0023):* the server does not fetch a URL.
HTML arrives already fetched from the browser the Candidate was reading it in,
with the URL supplied alongside for citation. Following a user-supplied URL
server-side is an SSRF surface this product has no need to open, and SPEC-0005's
rule that no module outside `metering` opens a socket is worth more than the
convenience.

**Chunk.** 500–800 tokens, split on structure where structure exists (headings,
paragraph boundaries), no overlap. Each chunk carries `chunk_id`, a content hash,
its locator and its embedding.

**Embed.** One batched call per source. Token count is known after extraction, so
the spend is measured rather than estimated.

**Cluster.** Chunks of one source cluster into Topics, sized against the 10k-token
dossier budget. A cluster over budget splits at the chunk boundary nearest its
median; a cluster under a floor merges into its nearest neighbour. Both are
arithmetic, not judgment.

**Label.** One cheap model call per cluster returns a Topic title and whether the
cluster's chunks are question/answer shaped. On failure the title falls back to the
first heading, or the first line of the earliest chunk. Labelling never blocks
ingest.

**Freeze.** `topic_id` is minted and persisted with the cluster's centroid and the
set of its chunk hashes. This is the record that later ingests match against.

**Dossier build.** A Topic dossier is its chunks concatenated in locator order —
not cluster order — and cached whole. Ground-Truth chunks are stored in a separate
field and are never merged into the teaching material (PRD-0001 §4, §8).

**Validate.** The ADR-0007 contract is checked and every violation is reported, not
the first.

### The interview loop is untouched

Topic selection is Thompson sampling over in-scope Topics before any content is
needed; the Interviewer then asks for a dossier by `topic_id` and receives it
whole. That is a lookup, exactly as ADR-0005 requires. Nothing in the loop issues
a similarity query, and no follow-up is answered out of a top-k result.

### Contract conformance

| Contract term (ADR-0007) | Satisfied by |
|---|---|
| Module → Topic → leaf hierarchy | Source → cluster → chunk |
| Stable ids across re-ingests | `module_id = hash(notebook_id, source_id)`; `topic_id` minted at first ingest and persisted with centroid and chunk-hash set |
| Explicit ordering | Module order is upload index; Topic order is the offset of its earliest chunk; chunk order is locator order |
| Topic dossiers under a token budget | Enforced at cluster-split, verified again at validate; p50 and max reported at ingest |
| Ground Truth optional | Mined where present, declared absent where not |
| Content-free leaves recorded as stubs | A source that extracts to nothing becomes a stub Module — visible, unselectable, reason stated |

### Persistence

Chunks, embeddings, centroids, dossiers and the notebook itself live in the
**content** schema — the ephemeral side of ADR-0010, deletable by the Candidate.

Evidence rows, Topic Confidence and Corpus Version events live in the permanent
schema. An Evidence row carries a denormalised Topic title, the grounding excerpt
it was scored against, and the `chunk_id` list it cited, so a retired Topic still
renders in the record after its content is gone.

## Surface

Three additions to `docs/spec/0003-candidate-web-surface.md`, one deliberate
absence.

**Notebook list and upload.** Sources are dragged in. Each shows its state:
extracting, embedding, ready, or stub with the reason it produced no text.

**Session setup.** The existing Module picker, now listing the Candidate's sources.
Duration selection is unchanged.

**Citation.** Every question records the chunks that grounded it. The Judge's
rationale cites `chunk_id`s. Selecting one shows the exact span with its locator —
source and page. Citations are written to Evidence, so they survive into the
Session summary and the permanent record.

**No ingest confirmation.** Ingest starts when sources are added. Cost appears in
the existing cost readout. Nothing is quoted in advance.

Unchanged: the exchange, the blind Judge, Thompson sampling, the Evidence Floor,
the separation of Coverage from Mastery, and the retired-word rules.

## Failure Modes

| Case | Behaviour |
|---|---|
| Scanned PDF, JS-only or paywalled URL | Stub Module: visible, unselectable, reason stated. Coverage measures the real notebook, not what happened to parse. |
| Provider failure mid-ingest | Ingest is atomic per source — a Module appears only after extract, embed, cluster and validate all pass. Resume is idempotent: chunks are keyed by content hash and already-embedded chunks are neither re-embedded nor re-billed. |
| Label call fails | Deterministic title fallback. Ingest proceeds. |
| Same source uploaded twice | Identical content hash deduplicates to the existing Module. No second charge, no twin Topics. |
| A changed version of an ingested source | Chunks match frozen centroids above a similarity floor and keep their `topic_id`. Unmatched mass mints a new Topic and logs a Corpus Version event. |
| Embedding model version changes | `embedding_model` is recorded on the notebook. A change re-embeds chunks; Topic membership is stored data and is not recomputed. |
| Contract violation at validate | The source is rejected whole and the report names every violation. |
| Notebook deleted mid-Session | The Session ends after the current Topic Visit, never inside one. Evidence is written; Topics retire. |
| Insufficient balance | Ingest is refused before spending and the shortfall is named. A BYOK Candidate is shown the provider and never a Credit message. |

## Testing

- **Fixture notebook in-repo** — a small markdown file, a small PDF, a scanned PDF that must produce a stub, and a URL. PRD-0001 §22's conformance check runs against it.
- **Determinism** — ingesting the fixture twice produces identical `topic_id`s and byte-identical dossiers.
- **Append stability** — adding a paragraph to a source mints no new Topics and changes no ids.
- **Drift honesty** — replacing half a source mints a new Topic *and* logs a Corpus Version event. Silence is the failure.
- **Budget** — every dossier is at or under 10k tokens; p50 and max are reported at ingest.
- **Ground Truth separation** — Ground-Truth text never appears in the teaching field handed to the question-asker.
- **Judge blindness** — the Judge receives the grounding excerpt and `chunk_id`s only, never the conversation (ADR-0002).
- **Deletion** — after a notebook is deleted, Evidence rows and their citations still render from snapshots.
- **Metering** — embedding and labelling calls land on the same ledger as Session spend, with provider recorded.

## Out of Scope

YouTube transcripts and audio sources. Cross-source thematic Modules. Any use of
the embedding index inside the interview loop. Sharing a notebook between
Candidates. Re-clustering an ingested source.
