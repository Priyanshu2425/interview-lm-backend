# The precomputed index outlived its reason

Supersedes: ADR-0018 (the artifact, not its findings)
Amends: ADR-0005 (one clause — see its 2026-08-22 amendment)
Source: SPEC-0006; ISSUE-0037

## The decision

`data/corpus-index.json` is deleted, with its fingerprint, its staleness reading
and its build script. Related Topics is a comparison of the Topic centroids
already stored in `content.notebook_topic`, computed when asked.

## Why the reason went away rather than the feature

ADR-0018 built a file because the Corpus **was** a file. Nothing in Postgres knew
what a shipped Topic was, so a vector for one had nowhere to live but beside the
`corpus.json` it was derived from — and a file derived from another file can
disagree with it, which is why that ADR needed a fingerprint, a model identity
and a rule for serving nothing when they stopped matching.

SPEC-0006 removed the premise. Every Corpus is documents in Postgres, chunked
and embedded on the way in, and a Topic's centroid is written in the same
transaction as the Topic. A stored centroid cannot be stale against the Topic it
was stored with. So the artifact is not merely redundant: it is a second copy of
something that can now only be wrong.

That is the shape of this decision. It is a **simplification, not a retreat** —
the feature is unchanged from a Candidate's side, and three things it took a
measurement to learn are carried over verbatim.

## What survives

- **Mean-centring is not optional.** A caption-trained text tower maps long
  technical prose into a narrow cone: raw cosines between Topics sat between
  0.974 and 0.998, and the ranking was noise wearing the clothes of a similarity
  score. Centring moved same-Track accuracy from 86% to 94%, against 68% for
  chance. `related.centre` carries the measurement in its docstring, and the
  quality floor still runs under `INTERVIEWER_MODEL_TESTS=1`.
- **Five neighbours, and a floor.** `TOP_K` and `MIN_SCORE` are unchanged, and
  `MIN_SCORE` still belongs to the centred space and nowhere else.
- **Ties break by id**, so two reads of the same rows agree.
- **Nothing rather than something wrong.** The failure mode changed shape and
  kept its rule: a Corpus this deployment does not hold, and a Topic with no
  neighbour above the floor, both render as nothing.

## What is new, and is a constraint rather than a preference

**A neighbour is only ever within one Corpus.** `notebook.embedding_model` is
per Corpus, so two Libraries can hold vectors from two different spaces. A cosine
across them is a number with no meaning, and the query is scoped to the Topic's
own Corpus so that it cannot be taken.

This is stricter than the artifact was — it held one Corpus and could not have
crossed one — and it is the price of the Corpus being something a Candidate
assembles rather than something a build produces.

## What this costs

The comparison is done when asked rather than once, offline. A Corpus's
centroids are read and centred per request, cached per Corpus and dropped when
that Corpus is ingested into. For 71 Topics that is a few thousand floats and
arithmetic measured in milliseconds; the shape that would not survive is
comparing every Topic to every Topic across every Corpus, and nothing does that.

## What it stops costing

A deployment no longer has to be told when its Corpus changed. There is no
command to re-run after a scrape, no artifact to review in a diff, no format
version to bump, and no state in which Related Topics is quietly serving
nothing because a file went out of date. ISSUE-0030 existed to make that state
legible; the state does not exist any more.
