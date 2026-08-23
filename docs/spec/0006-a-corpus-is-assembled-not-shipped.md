# SPEC-0006 — A Corpus is assembled, not shipped

Status: **draft — for review**
Supersedes in part: ADR-0005 (dossiers are file reads), ADR-0007 (the InterviewLM
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
InterviewLM's own words.

## Ownership: shared and personal

**A Corpus is owned by the platform or by a Candidate**, and the difference is
visible in exactly two places: who may write to it, and whether it can produce a
comparison.

**Shared.** Imported once by an operator, read-only to every Candidate, and the
same `topic_id`s for all of them. That last part is the whole reason it exists —
Topic Confidence is keyed on `topic_id`, so a shared Corpus is what makes two
Candidates' Mastery on the same Topic the same measurement rather than two
unrelated ones. It is also cheaper: the import is paid once, not per signup.

**Personal.** A Candidate's own uploads, exactly as notebooks work today. Theirs,
private, deletable, and never compared to anyone — their cohort is one, by
construction.

ADR-0010 defined `content` as "the Candidate's, and deleted when they say so",
and a shared Corpus is not that. Two things follow and neither is optional:

- an owner and a visibility on the Corpus, and
- **a delete guard**. ISSUE-0027's retire path applies to a Candidate's own
  Corpus and must refuse a shared one — otherwise one Candidate can retire the
  Topics every other Candidate's Evidence is keyed on. This is the single most
  destructive thing the new model makes possible, and it is a constraint rather
  than a code path.

**The Scaler material is the first shared Corpus.** Recorded as a deliberate
decision of the project owner, taken with the redistribution question in view
and not by omission.

Candidates publishing their own Corpora to others is out of scope. Nothing here
forecloses it, and everything about moderation, consent and takedown that it
would require is unwritten.

## Comparison: per Topic, never as a rank

A Candidate can see where they stand against everyone else examined on the same
shared Topic. What they cannot see is a position in a list, because that needs a
number this product refuses to produce.

> **PRODUCT.md, Principle 4** — *Refuse the number you cannot justify. No
> difficulty label, no fused Coverage-and-Mastery percentage.*

A leaderboard needs one figure per Candidate. Ranking on Mastery alone puts
someone who answered two questions perfectly above someone who answered two
hundred at ninety percent; ranking on Coverage alone rewards volume over
understanding; fusing them is the refusal, verbatim. So the comparison happens
**inside a Topic**, where Mastery means one thing and needs no fusing:

> On *Attention Mechanisms*, you are above the median of 340 Candidates.

**An exact rank, with ties shared.** Within one Topic, Mastery is a single
number and ordering it fuses nothing, so `#7 of 340` is available and Principle 4
is untouched. What is *not* available is separating two Candidates the
mathematics cannot separate: Mastery is the mean of a Beta posterior and carries
a spread, so 0.82 and 0.81 may be the same measurement twice. Where posteriors
overlap, Candidates share a position — `#7= of 340` — and where they are
genuinely apart, the rank is exact.

This costs nothing to compute: the posterior is already stored per Candidate per
Topic, and the same spread that decides whether a Topic reads *Untested* decides
whether two Candidates are distinguishable. It is one rule applied twice.

The alternative was an unconditional rank, and it would have claimed an ordering
the data does not have — and shuffled a Candidate's position when other people
took a Session, on a day they did nothing.

Three further rules hold it honest, and two of them are existing rules applied
again rather than new ones.

**Only tested Candidates are in the cohort.** A Candidate whose Band on that
Topic is `UNTESTED` is not counted as zero — counting them would be exactly the
fabrication *untested is not zero* exists to prevent, and it would drag every
median down in proportion to how many people had not got there yet. The gate is
`Band.tells()`, already written and already under test.

**A Cohort Floor, beside the Evidence Floor.** Below a threshold of tested
Candidates, no rank is shown: it reads *not enough Candidates yet* and no
number, which is the same shape and the same reasoning as *Untested*.

With exact ranks the argument is mostly privacy rather than meaning. `#1 of 2`
discloses the other Candidate's standing completely, and `#3 of 4` nearly so —
a rank over a handful of people is a statement about them as much as about you.

**Provisionally 10, and it needs revisiting with real data.** Unlike the Evidence
Floor, this number is not derived from anything: it is a privacy judgement, and
ten is the smallest cohort in which one person's position does not describe
everyone else's. It should be reviewed once there are enough Candidates to know
how thinly they spread across 71 Topics — a floor that is never reached is the
same as a feature that does not exist.

**Coverage is compared as Coverage.** "Examined on 45 of 71 Topics, more than
78% of Candidates" is a second, separate reading. It is never combined with the
first into a position, and no function returns the combination.

**No new storage.** `core.topic_confidence` is already `(candidate_id, topic_id,
alpha, beta)`, so a percentile is a query against Evidence that already exists —
filtered to one `topic_id`, restricted to rows the Evidence Floor admits. The
shared Corpus is what makes the `topic_id`s line up; nothing else is needed.

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

**Decided: B, with the upload separated from the ingestion.** The import runs in
the background while the surface polls for progress — and the polling is not only
for the progress bar.
An idle Render instance spins down, and any inbound request resets that timer,
so the progress poll keeps the server alive for as long as somebody is watching.
That is a side effect of a request we need anyway rather than a keep-alive built
for its own sake, which matters: the free tier allows about one instance running
full time, so deliberately holding it awake would spend the allowance on nothing.

**The upload outlives the ingestion.** A Source exists as soon as its bytes do:
the file lands in the object store, the row is written, and the document appears
in the Library at once, marked as not yet ingested. Ingestion starts by itself.

This is not a weakening of ISSUE-0026's atomicity. It is the distinction
ISSUE-0023 already drew and this design finally uses — a stub is "a Module that
exists, is visible, and states why it carries nothing", and
`notebook_source.state` is already `ready | stub`. An un-ingested document is
another state on that column rather than a new concept. A Module still appears
only when every stage has succeeded, so there is still no partial Module, no
orphan Topic, no chunk belonging to nothing and no double charge.

The states are **uploaded → ingesting → ready**, with **failed** beside them.

**A killed worker needs no timeout to detect.** The worker runs in-process, so
none survives a restart: any row still marked `ingesting` when the process starts
is stale by definition and is reset at boot. A worker that stalls inside a live
process is the harder case, and it reports elapsed time and last progress rather
than being guessed at.

**Retry re-ingests; it does not re-upload.** The bytes are already stored, so a
failed document offers a Retry that costs the embedding again — a 200-page PDF is
about two cents — and nothing else. Starting over rather than resuming is
deliberate: resuming would mean chunks belonging to no Module, a class of partial
state worth considerably more than the two cents it saves.

## Settled since the first draft

1. **Ownership is shared *and* personal**, not personal-only. Cross-Candidate
   comparison was the reason, and it is the thing that would have been expensive
   to reverse once Evidence had accumulated against per-Candidate ids.
2. **Comparison is per-Topic percentile**, not a leaderboard. Principle 4 stands
   unamended.
3. **The Scaler material is the first shared Corpus**, decided by the project
   owner with the redistribution question in view.

## Settled since the second draft

4. **Rank is exact, and ties are shared.** Ordering within one Topic fuses
   nothing, so the number is available; overlapping posteriors share a position,
   so it never claims a difference the measurement does not support.
5. **Import runs in the background and is not resumed.** Atomicity already
   guarantees nothing partial survives, and re-uploading costs about two cents.
6. **No comparison on a Topic a Candidate has not been examined on.** There is no
   measurement of them to compare, and showing the cohort's figures there is a
   study recommendation wearing a statistic — which FUTURE-PIPELINE defers for
   want of calibration data.

## Still open

1. **The Cohort Floor is a guess at 10.** It is a privacy judgement rather than
   a derived number, and it should be revisited once there is data on how
   thinly Candidates spread across 71 Topics.
2. **A stalled background import looks identical to a slow one.** Nothing partial
   is written, so there is no corruption — but a Candidate watching a progress
   bar that has stopped needs to be told, and how long is too long is unknown
   until real documents have been through it.
