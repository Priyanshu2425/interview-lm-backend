# No vector store — dossiers are looked up by Topic id

The **Interviewer** loads a **Topic** dossier by reading the markdown files
listed for that `topic_id` in `corpus.json`. There is no embedding model, no
vector store, and no retriever.

## Why the obvious thing was rejected

This is a deliberate deviation from LangChain's default path, recorded because a
future reader will assume the retrieval layer is missing rather than absent by
choice.

**There is no query to embed.** Topic selection happens by Thompson sampling
over the 71 in-scope Topics *before* any content is needed. The Interviewer
never asks "find content about attention"; it says "give me Topic
`cmrlq73jd...`". That is a file read.

**The whole Topic fits.** Dossiers run ~5k tokens at the median and 9.3k at the
maximum. Chunking would actively harm the agentic region defined in ADR-0001:
follow-ups need the entire Topic, and top-k retrieval is precisely how a concept
gets probed while its explanation sits in an unretrieved chunk.

**Embeddings are a liability against a re-scraped Corpus.** Every re-run of
`scripts/scrape.mjs` would require re-embedding to stay consistent.

## When this should be revisited

If something needs cross-Topic similarity — "what else relates to this?",
sideways exploration, cross-Module connections — that genuinely is a vector
problem. It is not the interview loop, and it can be added alongside without
disturbing dossier lookup.

## Amendment — 2026-08-21, the Notebook Adapter

The **Notebook Adapter** (ADR-0015) chunks, embeds and clusters its sources. This
does not reverse the decision above; it is the "added alongside" case this ADR
already permits.

What is unchanged: Topic selection is Thompson sampling over ids before any
content is needed, a dossier is loaded whole by `topic_id`, no query is embedded
at question time, and no follow-up is answered out of a retrieved chunk.

What is added: an embedding index over chunks, used at ingest to derive Topics
and at read time to cite the exact span of the exact source behind a question, an
answer or a Judge rationale. It lives in the content schema and is deleted with
the notebook.

The third objection above — that embeddings are a liability against a re-scraped
Corpus — is answered rather than dismissed: `embedding_model` is recorded on the
notebook, and a model change re-embeds chunks while Topic membership stays frozen
as stored data.


## Amendment — 2026-08-22, the figure index

ADR-0017 puts a second modality in the same index: figures lifted out of PDF
sources, embedded by the image tower of the same model into the same 768
dimensions as the prose.

What is unchanged is what was unchanged last time, and for the same reason.
Topic selection is Thompson sampling over ids before any content is needed, a
dossier is loaded whole by `topic_id`, and no query is embedded at question
time. A figure is never a Leaf, never enters a dossier, and never answers a
follow-up.

What is added is reach: a citation can now name the diagram a question came from
rather than only the paragraph beside it. That is attribution, which is the use
this ADR has permitted since its first amendment.

## Amendment — 2026-08-22, Related Topics

The closing clause of this ADR — "if something needs cross-Topic similarity ...
it can be added alongside" — has been taken up. The shipped Corpus is embedded
and every Topic carries up to five precomputed neighbours (ADR-0018).

The three objections above are unaffected, and the first two are why this is an
amendment rather than a repeal. There is still no query to embed: neighbours are
centroid against centroid, computed offline, so a request is a lookup in a file
and nothing is embedded at question time. The whole Topic still fits, and is
still loaded whole by id.

The third — that embeddings are a liability against a re-scraped Corpus — is
answered here the same way the Notebook Adapter answered it: the index records
the corpus fingerprint and the embedding model it was built from, and an index
that no longer matches serves **no** neighbours rather than wrong ones.

What has *not* changed is the sentence this ADR exists for: the interview loop
runs no retriever. Topic selection is Thompson sampling over ids, a dossier is
loaded whole, and no follow-up is answered out of a top-k result.
