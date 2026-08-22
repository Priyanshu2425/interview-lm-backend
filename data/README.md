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

## Rebuilding the index

    python scripts/embed_corpus.py --provider siglip

Run it after a scrape, or after changing the embedding model. Against an
unchanged Corpus it is a no-op that says so rather than a several-minute job
that looks like work; `--force` rebuilds anyway, which is what you want after
changing *how* the index is built rather than what it is built from.

    python scripts/embed_corpus.py --check

reports whether the artifact is current and, when it is not, which of the two
inputs moved. They are different problems: a re-scrape needs a rebuild and stops
neighbours being served until it happens, while a model swap leaves the existing
edges serving — nothing is embedded at request time, so they still describe the
Corpus consistently — and only matters to anything comparing a *new* vector
against these centroids.

The same reading is on the operator console beside the ledgers, because the
person who notices Related Topics has gone quiet is not always the person at a
terminal.

**Part of the test suite needs a Corpus**, and on a clean clone it says so
rather than passing quietly. Measured, with `data/corpus.json` absent:

    525 passed, 152 skipped, 17 failed

The 152 skips are deliberate: they take the Corpus through the `corpus` fixture,
which skips with a message naming this file. The 17 failures are tests that
assert on the *shipped* Corpus — how many Modules the picker lists, what a
Session scoped to one contains — and reach it through the API's dependency graph
rather than through that fixture, so nothing tells them to skip.

They fail rather than error because a deployment with no Corpus is a supported
state and behaves like one: `get_base_corpus` returns an empty Corpus, the
picker lists no shipped Modules, and notebooks compose onto nothing exactly as
they compose onto something.

Point `CORPUS_PATH` at any conformant Corpus and the whole suite passes. Closing
the last 17 properly means a small synthetic Corpus committed here — our own
content, a handful of Topics — which would also give `corpus/conformance.py` a
second Corpus to check itself against, and would let CI run the full suite on a
clean clone. It is not written yet.

## Bringing your own

Write an Adapter. `corpus/contract.py` is the whole contract, `corpus/
conformance.py` checks a Corpus against it and reports every violation rather
than the first, and `corpus/adapters/` holds three worked examples: a structured
course API, a folder of markdown, and a Candidate's uploaded notebook.
