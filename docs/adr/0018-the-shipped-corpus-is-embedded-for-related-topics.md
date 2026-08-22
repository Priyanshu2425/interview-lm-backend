# The shipped Corpus is embedded, for Related Topics and nothing else

ADR-0005 refused a vector store and named the one case it would allow:

> If something needs cross-Topic similarity — "what else relates to this?",
> sideways exploration, cross-Module connections — that genuinely is a vector
> problem. It is not the interview loop, and it can be added alongside without
> disturbing dossier lookup.

FUTURE-PIPELINE recorded the same case with an instruction attached: **"Do not
pre-build it."** That instruction was right for as long as there was no consumer.
There is one now, and this ADR is the reversal written down, because a reversal
nobody records is indistinguishable from a rule nobody read.

## What is embedded, and what is not touched

Every Topic of the shipped Corpus gets a centroid, and every Topic gets up to
five precomputed neighbours. That is the whole feature.

Unchanged, and each one tested rather than asserted:

- Topic selection is Thompson sampling over ids, before any content is needed.
- A dossier is loaded whole by `topic_id`.
- **No query is embedded at question time.** Neighbours are centroid against
  centroid, computed offline, so at runtime the answer is a lookup in a file.
  ADR-0005's "there is no query to embed" stays *literally* true of the running
  system rather than approximately true.
- Citations stay derived from what was handed to the model, never from a
  similarity search (`corpus/citations.py`).

## Structure is given, never derived

This is the decision that mattered most and it is the one that could have gone
silently wrong.

The Notebook Adapter mints `topic_id`s by clustering, because a Candidate's file
arrives with no divisions. The shipped Corpus arrives with 71 Topics that are the
join key for every row of Evidence and Topic Confidence in `core`. Running the
same pipeline over it would have produced a different 71 and orphaned months of
Mastery — with no error, and a symptom that surfaces long after the cause.

So the build chunks, embeds, and stops. It never clusters, never labels, never
mints an id, never moves a boundary. A test asserts the id set matches the Corpus
exactly, and another replaces the clusterer and the id-minter with functions that
raise, so "it did not cluster" is verified by call count rather than by reading
the code.

## The index is an artifact, built offline

Produced the way `data/corpus.json` is produced: one build, read many times,
never written by the API. A deployment reads it and therefore needs no model to
*serve* Related Topics — only to rebuild them.

It carries its own provenance: the corpus fingerprint, the embedding model
identity, and the format version. The fingerprint is over content — Topic ids and
leaf text — rather than over `scrapedAt`, because re-running the scraper and
getting the same material back is not a change, and an index that cried stale
every time somebody refreshed the Corpus would be ignored within a week.

This answers ADR-0005's third objection — *"embeddings are a liability against a
re-scraped Corpus"* — the way ADR-0015 answered it for notebooks: recorded rather
than dismissed. A stale index serves **no** neighbours rather than wrong ones.
Making that state visible is ISSUE-0030; making it safe is done, because a thing
that can silently lie must not ship first and be fixed second.

## Mean-centring, and why it is not a tuning knob

ADR-0017 warned that SigLIP 2's text tower is caption-trained and would sit below
a dedicated retrieval encoder on prose. Measured on this Corpus, it was worse
than "below": it was unusable.

Every pair of Topics scored between **0.974 and 0.998**. The ranking was noise
wearing the clothes of a similarity score — "NumPy — Numerical Computing
Foundation" came back nearest to "CNN Fundamentals", and "Sorting Algorithms"
nearest to "Attention Mechanisms, Transformers & BERT". Anisotropy: the encoder
maps all long technical prose into one narrow cone.

Subtracting the mean of the Corpus's own centroids and re-normalising restores
the spread — the same pairs then range from **-0.705 to 0.820**.

Judged against whether a Topic's five neighbours come from its own Track (DSA and
AIML are different subjects, so a cross-Track neighbour is nearly always wrong):

| | same-Track in top 5 |
|---|---|
| picking at random | 68% |
| raw cosine | 86% |
| **centred cosine** | **92%** |
| centred, scored on top-3 chunk pairs | 85% |

Chunk-pair scoring was tried because it should preserve specificity better than
averaging; on this material it amplified noise instead, and it is recorded here
so nobody spends the afternoon again.

Centring is therefore a property of the space rather than a preference, and the
mean travels in the artifact — stored centroids without the origin they were
compared from cannot be compared to anything later.

Two consequences worth stating plainly. **The quality ceiling is the model's**,
and 92% is good enough to show a reader "what else relates to this" while being
nowhere near good enough to drive a decision — which is one more reason Related
Topics is a statement about the material and never about the Candidate. And **a
similarity threshold only means something after centring**: the floor below which
an edge is dropped lives in the centred space and nowhere else.

## The chunker moved

Cutting text into contiguous spans is the same job whatever produced the text,
and it lived inside the Notebook Adapter. Two chunkers would mean two answers to
"is this the same span", which is the question content addressing exists to
settle — and chunk hashes decide what is re-embedded, what is re-billed, and what
a notebook Topic is called.

It now lives in `corpus/chunking.py`. The one genuinely notebook-specific rule
inside it — a heading announcing worked answers starts a new chunk (ISSUE-0024) —
is injected by the Adapter that understands worked answers, so no Adapter's
vocabulary leaks into shared code and ADR-0007 holds.

## What was deliberately not built

**Notebook ↔ Corpus alignment** — which shipped Topics does a Candidate's own
material correspond to? — is possible now and is not built. It needs no new
embedding: ADR-0017 put both corpora in one 768-d space, and the artifact keeps
centroids and the mean precisely so that question can be answered later by
comparison rather than by re-running a model on a machine that may not have one.

**Where a Candidate sees this** is ISSUE-0031 and is HITL. A list of related
Topics rendered beside a score reads as *"study these next"*, which is Topic
recommendation — deferred in FUTURE-PIPELINE for want of calibration data, and a
claim about a person that this index cannot support.
