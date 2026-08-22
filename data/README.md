# data/

Empty in this repository, and deliberately.

This directory holds the **Corpus** — the material a Candidate is examined on.
For the deployment this project was built against, that is Scaler Cortex course
content: 387 markdown files and a `corpus.json` manifest over them. It is
Scaler's material rather than ours, so the code that examines a Corpus is
published here and the Corpus is not.

Nothing is missing from the *implementation*. What is missing is somebody's
copyrighted coursework.

## What belongs here

| file | what it is | how it is produced |
|---|---|---|
| `corpus.json` | Tracks → Modules → Topics → Leaves, conforming to `corpus/contract.py` | `scripts/scrape.mjs`, or any Adapter (ADR-0007) |
| `markdown/` | the leaf text `corpus.json` points at | same |
| `corpus-index.json` | Topic centroids and precomputed Related Topics | `scripts/embed_corpus.py` (ADR-0018) |
| `pending-transcripts.json` | Lecture Recordings carrying no text | `scripts/scrape.mjs` |

`CORPUS_PATH` points the loader elsewhere, so none of this has to live here.

## Running without it

**A notebook is a complete Corpus.** The Notebook Adapter (ADR-0015) turns an
uploaded markdown file or PDF into Modules and Topics with no scrape involved,
and that path needs nothing in this directory. It is the honest way to try this
project on material you actually own.

**Related Topics** stays absent until `corpus-index.json` exists. That is a
designed state rather than a broken one: a missing or stale index serves no
neighbours instead of wrong ones (ADR-0018).

**Part of the test suite needs a Corpus**, and on a clean clone it says so
rather than passing quietly. Measured, with `data/corpus.json` absent:

    499 passed, 152 skipped, 17 failed, 26 errors

The 152 skips are deliberate — they take the Corpus through the `corpus`
fixture, which skips with a message naming this file. The failures and errors
are not: those tests reach the shipped Corpus through the API's own dependency
graph rather than through a fixture, so they raise a missing-file error instead.

Point `CORPUS_PATH` at any conformant Corpus and the whole suite passes. Closing
the gap properly means a small synthetic Corpus committed here — our own
content, a handful of Topics — which would also give `corpus/conformance.py` a
second Corpus to check itself against. It is not written yet.

## Bringing your own

Write an Adapter. `corpus/contract.py` is the whole contract, `corpus/
conformance.py` checks a Corpus against it and reports every violation rather
than the first, and `corpus/adapters/` holds three worked examples: a structured
course API, a folder of markdown, and a Candidate's uploaded notebook.
