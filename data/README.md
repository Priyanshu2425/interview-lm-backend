# data/

Empty in this repository, and deliberately — and since ISSUE-0037, **not needed
at runtime at all.**

This directory holds material to *import*. For the deployment this project was
built against that is Scaler Cortex course content: 387 markdown files and a
`corpus.json` manifest over them. It is Scaler's material rather than ours, so
the code that examines a Corpus is published here and the Corpus is not.

Nothing is missing from the *implementation*, and nothing is missing from a
clean clone either. Every Corpus the API serves lives in Postgres (SPEC-0006):
this directory is an import source, not a mount.

## What belongs here

| file | what it is | how it is produced |
|---|---|---|
| `corpus.json` | Tracks → Modules → Topics → Leaves, conforming to `corpus/contract.py` | `backend/scripts/scrape.mjs`, or any Adapter (ADR-0007) |
| `markdown/` | the leaf text `corpus.json` points at | same |
| `pending-transcripts.json` | Lecture Recordings carrying no text | `backend/scripts/scrape.mjs` |

## Importing it

    python backend/scripts/import_corpus.py --corpus data/corpus.json --title "Scaler Cortex"

One Source per Module, into a shared Corpus that every Candidate can be examined
on. The Topics keep the ids they arrived with, which is what makes two people's
Mastery on a Topic the same measurement (ISSUE-0034); the Modules keep theirs,
so a Session's scope still names the same Module it always did.

Re-running it is a no-op per Module, so an interrupted import is resumed by
running the same command again. `--dry-run` reports what would be imported and
writes nothing. `CORPUS_PATH` is where this reads from and is not read by the
API.

**Restart the API afterwards.** The script writes to Postgres from its own
process, and a running API holds the composed Corpus in memory — it rebuilds
that when *it* ingests something, and it has no way to notice somebody else did.
An import is a deployment step, so a restart is the honest place to put that
rather than a route that exists to invalidate a cache.

## Running without it

**A notebook is a complete Corpus.** The Notebook Adapter (ADR-0015) turns an
uploaded markdown file or PDF into Modules and Topics with no scrape involved,
and that path needs nothing in this directory. It is the honest way to try this
project on material you actually own.

**Related Topics needs no artifact.** Neighbours are the stored Topic centroids
of one Corpus compared against each other, written at ingest (ADR-0021). There
is nothing to build and nothing that can go stale.

**The test suite skips rather than fails.** Tests that need authored material
take it through the `corpus_path` fixture, which skips with a message naming this
file. Measured, with `data/corpus.json` absent:

    604 passed, 155 skipped

No failures. Before ISSUE-0037 there were 17, and they were tests that reached
the *shipped* Corpus through the API's dependency graph rather than through that
fixture — so nothing told them to skip. There is no such path any more.

## Bringing your own

Write an Adapter. `corpus/contract.py` is the whole contract, `corpus/
conformance.py` checks a Corpus against it and reports every violation rather
than the first, and `corpus/adapters/` holds three worked examples: a structured
course API, a folder of markdown, and a Candidate's uploaded notebook.
