# ISSUE-0029 — The shipped Corpus, embedded, and Related Topics served

Status: resolved
Type: AFK
Source: ADR-0005 §"When this should be revisited"; FUTURE-PIPELINE §Cross-Topic
similarity; ADR-0017 (the embedder and the space it embeds into)
Covers: the sideways exploration ADR-0005 permitted and deferred

## What to build

The shipped Corpus gets the same embedding treatment a notebook already gets,
and it feeds exactly one thing: **Related Topics** — "what else relates to
this?", the case ADR-0005 named when it said a vector store could be added
alongside dossier lookup without disturbing it.

A build step runs the embedding model over the Corpus once and writes a
versioned artifact holding, per Topic, a centroid and its top five neighbours
with scores. A loader reads that artifact and serves the neighbours over the
API. Nothing embeds anything at request time.

**Structure is given, never derived.** This is the whole risk of the slice. The
Notebook Adapter's pipeline *mints* `topic_id`s by clustering, because its
source arrives with no divisions. The shipped Corpus arrives with 71 Topics that
are the join key for every row of Evidence and Topic Confidence in `core`.
Running the clusterer over it would produce different ids and orphan the lot. So
the build chunks and embeds and **stops**: it never clusters, never labels,
never mints an id, and never writes a Topic boundary. Chunk vectors are pooled
into the Topic they already belonged to.

**Chunking moves to a shared home.** It currently lives inside the Notebook
Adapter and is not notebook-specific — cutting text into contiguous spans is the
same job whatever produced the text. The one notebook-specific rule inside it,
the Ground-Truth heading boundary (ISSUE-0024), becomes a predicate the Notebook
Adapter injects rather than something the chunker knows. No adapter ends up
importing another, which ADR-0007 forbids and a test already enforces.

**The artifact is data, and it is built offline.** Produced the way
`data/corpus.json` is produced — one run, read many times, never written by the
API. It records the corpus fingerprint and the embedding model identity beside
the vectors, so a re-scrape or a model change is detectable rather than assumed.
A deployment reads it; a deployment never builds it, and therefore never needs
torch.

**Fail closed.** A missing artifact, a fingerprint that does not match the
Corpus being served, or a model identity that does not match the running one all
produce *no neighbours* rather than wrong ones. The route exists either way and
returns an empty list, which is how this product already treats an Untested
Topic: absent, never a wrong number. Making that state *visible* is ISSUE-0030;
making it *safe* is here, because a thing that can silently lie must not ship
first and be fixed second.

Edges carry the neighbour's Module id and are not filtered by it. A Topic's
nearest neighbours are often its own Module's, which is true and useful for
"what leads into this"; cross-Module edges are the sideways exploration
FUTURE-PIPELINE actually asked for. Which to show is the consumer's decision and
is not baked into the artifact.

Centroids are kept in the artifact, not only the edges. They are what allows a
later slice to ask which shipped Topics a Candidate's own notes correspond to,
on a machine that has no model — and both corpora already share one 768-d space
(ADR-0017), so that question costs a comparison rather than a re-run.

Carries **ADR-0018**, recording why "do not pre-build it" was reversed, that
Related Topics is precomputed rather than queried, and that the artifact is a
fourth lifecycle: derived, disposable, rebuilt from the image.

## What must not change

Stated as acceptance criteria below because each is a way this slice could do
real damage quietly:

- Topic selection is Thompson sampling over ids. It does not read this artifact.
- A dossier is loaded whole by `topic_id`. It does not read this artifact.
- No query is embedded at question time, by anything, ever (ADR-0005).
- Citations stay derived from what was handed to the model, never from a
  similarity search (`corpus/citations.py` says so and stays true).

## Acceptance criteria

- [x] A build command embeds the shipped Corpus and writes the artifact
- [x] Every one of the 71 `topic_id`s in the artifact matches the Corpus exactly — none minted, none renamed, none missing
- [x] Running the build twice on an unchanged Corpus produces a byte-identical artifact
- [x] No clusterer, labeller or id-minting function is reached by the build, verified by call count rather than by reading the code
- [x] Topic centroids are unit vectors of the width the deployment embeds at, and every Topic carrying text has one
- [x] Each Topic lists its top five neighbours with scores and Module ids, and never itself
- [x] `GET` on a Topic returns its neighbours, and 404s for a `topic_id` the Corpus does not have
- [x] A missing artifact yields an empty list and a served route, not an error
- [x] An artifact whose fingerprint does not match the Corpus yields an empty list
- [x] An artifact built by a different embedding model than the one running yields an empty list
- [x] The chunker is reached from a shared home by both the Notebook Adapter and the Corpus build, and the Ground-Truth boundary rule is injected rather than known
- [x] The whole existing suite passes unchanged, including the conformance and architecture rules
- [x] Importing the API still loads no machine-learning stack
- [x] ADR-0018 is written and records the reversal, the precomputation, and the artifact's lifecycle

## Blocked by

- None — can start immediately

## What the build actually measured

Recorded here because the number decided the design. Raw cosines between Topics
all sat between 0.974 and 0.998 — the ranking was noise, and "NumPy" came back
nearest to "CNN Fundamentals". Mean-centring the space fixed it:

| | same-Track neighbours in top 5 |
|---|---|
| random | 68% |
| raw | 86% |
| **centred (shipped)** | **92%** |

ADR-0018 carries the reasoning. The floor is held by a test that runs against
real weights under `INTERVIEWER_MODEL_TESTS=1`.
