# SPEC-0006 — A Corpus is assembled, not shipped

Status: **draft — for review**
Supersedes in part: ADR-0005 (dossiers are file reads), ADR-0007 (the Cortex
Adapter as a runtime path)
Builds on: ADR-0015, ADR-0017, ADR-0018, ISSUE-0021 through 0029

## The change

Today there are two ways material reaches the examiner, and they share almost
nothing.

| | shipped Corpus | notebook |
|---|---|---|
| arrives as | a scrape, in the image | an upload |
| structure | authored | clustered at ingest |
| stored in | files on disk | Postgres |
| dossier | a file read | rows |
| lifecycle | immutable, redeployed | added to, re-ingested, deleted |
| embeddings | a committed artifact | pgvector rows |

The second column is a product. The first is a build artifact wearing a
product's clothes — and it is why `data/` had to be excluded from a public
repository, why Render's ephemeral disk is a problem, and why "add a document"
is a sentence that only makes sense on one side of the table.

**One column. Everything is the right-hand one.** Material arrives as documents,
is chunked and embedded into Postgres, and is added to over time. The scraped
Scaler course becomes *an import*, not a shipped asset.

## What already exists

Most of it, which is why this is a convergence rather than a rewrite.

`NotebookService.add_source()` already extracts, chunks, embeds, clusters,
labels, freezes, builds dossiers and validates against the contract. Adding a
source to a Corpus that already has one already works, and ADR-0015 already
guarantees it cannot move an existing Topic boundary — clustering runs inside a
single Source and cannot reach one it is not looking at. Re-ingest, PDF and URL
sources, Ground Truth mining, figures, deletion and retirement are all built and
tested.

What is missing is not the pipeline. It is the shipped Corpus being outside it.

## Naming

**`Corpus` stays the domain term.** It is precise, it is in 20 ADRs, the
contract, every adapter and CONTEXT.md, and a rename is a large mechanical change
whose main risk is being half-finished for months.

**The surface calls it a Library.** A set of documents somebody assembled, which
is what a Candidate sees and does: *add a document to your Library*, *this
Library has 15 Modules*. The mapping is recorded in CONTEXT.md and enforced the
way the vocabulary already is — the surface says Library, the API says corpus,
and neither leaks into the other. This is the same discipline ADR-0007 applies to
Cortex's own words.

## Ownership: personal

**A Corpus belongs to a Candidate.** There is no shared one. The Scaler material
is imported into a Candidate's own Corpus, and everyone who imports it gets
their own copy.

ADR-0010 is unchanged by this, which is the main argument for it: `content` stays
"the Candidate's, and deleted when they say so", one lifecycle, no visibility
rules, and ISSUE-0027's delete-and-retire path keeps working exactly as built.

Two consequences, stated rather than discovered:

**Mastery is not comparable between Candidates.** Each import mints its own
`topic_id`s, and Topic Confidence is keyed on them. Two people who studied the
same material have no Topic in common, so no cross-Candidate reading — cohort
averages, "how do I compare" — is possible without a shared Corpus. That is a
real limitation of this choice and it is the one that would be expensive to
reverse later, because Evidence accumulates against the ids.

**Every Candidate pays the import.** 71 Topics is roughly 298k tokens: about six
cents at Gemini's price through OpenRouter, per Candidate, once. Storage is
~460 chunks each. Neon's free 0.5GB holds on the order of a couple of hundred
Candidates' worth before it is a question.

## Where the documents live

**S3 holds the Sources; Postgres holds what was made of them.**

Today `notebook_source.text` holds extracted text and the original bytes are
discarded — a PDF is read once and thrown away. That is already thin (a
re-ingest cannot re-extract, and a citation cannot show the page it came from),
and it becomes untenable when the Corpus *is* the documents.

So: the uploaded bytes go to the object store `artifacts.py` already provides —
the same one holding figures, content-addressed, under the Candidate's prefix and
deleted with them. Extraction, chunks, embeddings and dossiers stay in Postgres.

The Scaler material sits in that bucket as a set of Sources like any other, and
importing it is the ordinary upload path with the file supplied by the platform
rather than by a browser.

## Structure is given, or derived, and the Adapter says which

The one thing an import must not do is cluster the Scaler material. It arrives
with 71 authored Topics; re-deriving them would produce different ids and mean
something different by every Topic.

ISSUE-0029 already built exactly this distinction for the Corpus index —
**structure is given, never derived** — and it generalises here. A Source
declares whether it carries divisions:

- **Given** — a structured import. Topics, order and titles come from the
  source; the pipeline only chunks and embeds. `topic_id` is derived from the
  source's own id so that two imports of the same material by the same
  Candidate are the same Corpus.
- **Derived** — an upload with no divisions. The existing clusterer runs, exactly
  as it does now.

This is a property of the Source, not a second pipeline.

## What retires

- `data/corpus.json` and `data/markdown/` as a runtime path. `CORPUS_PATH`
  becomes an import source rather than a mount.
- `get_base_corpus()` and `compose()`. There is no base to compose onto once
  every Corpus is a Candidate's.
- **`data/corpus-index.json` disappears entirely**, and this is a genuine
  simplification: with chunk vectors in pgvector, Related Topics is a query over
  a Candidate's own Topic centroids rather than a precomputed artifact. ADR-0018
  built the artifact because the Corpus was a file; once it is rows, the reason
  is gone. The fingerprint and staleness machinery go with it.
- ADR-0005 keeps its central claim — no query is embedded at question time,
  Topic selection is Thompson sampling over ids, a dossier is loaded whole —
  and loses only "a dossier is a file read".

## The open problem: importing takes half a minute

Embedding 71 Topics takes 30–40 seconds. A Candidate signing up cannot wait for
it, and SPEC-0000 refuses a message queue and Redis outright.

Three options, none free:

**A. Import on demand, not at signup.** The Candidate picks a Library and it
ingests while they watch a progress readout. Honest, needs no infrastructure,
and makes the wait the Candidate's choice rather than a mystery during signup.

**B. A background task in-process.** FastAPI `BackgroundTasks` or a thread. No
new infrastructure, but a Render free instance that spins down mid-import leaves
a half-imported Corpus — and ISSUE-0026 already established that ingest is
atomic per Source, so this needs resume rather than hope.

**C. Import lazily, per Module.** Only embed a Module when a Session first
scopes to it. Fastest start, but the first Session on each Module pays, and
Session setup is exactly where a delay is least welcome.

**Recommendation: A**, with the atomic-per-Source guarantee already built doing
the work — a resumed import re-embeds nothing it has already stored, because
chunks are content-addressed (ISSUE-0026).

## Open questions for review

1. **Is losing cross-Candidate comparison acceptable?** It is the expensive one
   to reverse. A shared Corpus with personal ones alongside would keep it, at
   the cost of a second lifecycle in a schema built for one.
2. **Does redistributing the Scaler material to every user need a decision?**
   Excluding it from a public repository was one question; serving it to every
   Candidate who signs up is a different and larger one.
3. **Does a Candidate see the Scaler Library as a starter, or upload their own
   from empty?** The first is a better product and the second avoids question 2
   entirely.
