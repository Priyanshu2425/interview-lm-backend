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


## Amendment — 2026-08-22, a dossier is loaded from rows

**One sentence changed and it is named here: "a dossier is a file read".** It is
now a read of `content.notebook_chunk` for a `topic_id`. Nothing else in this
ADR moved, and the distinction matters because the title still says *no vector
store* and that is still true of the interview loop.

What did **not** change, each of it still under test:

- **No query is embedded at question time.** Related Topics compares stored
  centroids that were written at ingest; nothing produces a vector to answer a
  request (`test_the_route_embeds_nothing`).
- **Topic selection is Thompson sampling over ids**, before any content is
  needed.
- **A dossier is loaded whole by `topic_id`**, and the loader's contract is
  unchanged. The whole Topic still fits; there is still no top-k.
- **No follow-up is answered out of a retrieval result.**

The third objection this ADR raised — *embeddings are a liability against a
re-scraped Corpus* — is not answered any more. It is **gone**. There is nothing
to re-scrape: the Corpus is documents in Postgres, and every vector was written
alongside the Topic it describes, so the two cannot disagree. The fingerprint and
staleness machinery that ISSUE-0029 and ISSUE-0030 built for a file went with the
file (ADR-0021).


## Amendment — 2026-09-01, the sampler moved to the front

**One sentence changed and it is named here: "Topic selection happens by
Thompson sampling over the 71 in-scope Topics *before* any content is needed."**
It is now *before the Session asks anything*. The sampler used to run once per
Topic Visit, inside the loop; since ISSUE-0041 it runs once, at the front, and
ranks the whole scope in one round of draws.

Nothing about the distribution changed. `TopicSelector.choose` is
`TopicSelector.rank(...)[0]` — one implementation, the same Beta draws, the same
weakest-or-least-known ordering, and the same injected randomness, so the same
seed still plans the same Session. What changed is *when* it is consulted and
over what: previous Sessions' posteriors rather than this Session's, because
this Session has written no Evidence at the moment it plans.

Why it moved is not a retrieval question at all, and this ADR is amended rather
than superseded for exactly that reason. The in-loop position was the only thing
requiring a posterior updated after every Visit, and that requirement was the
only thing requiring grading to happen mid-Session. Fixing the plan before the
first question removes the dependency, and removing it is what lets the Session
be graded once, at the end (ISSUE-0044). What is given up is adaptive selection
*within* one Session; what is bought is a plan the Candidate can see, in
`session_plan` and `plan_item`, fixed by a trigger and served by
`GET /v1/sessions/{session_id}/plan`.

The sentence this ADR exists for is untouched, and it is worth restating because
selection moving is the sort of change that looks like it should have moved
retrieval too. It did not. There is still no query to embed, at plan time least
of all: the planner is handed Topic **ids** and their titles, it groups them,
and the grouping is validated against the ids it was given. A dossier is still
loaded whole by `topic_id`, and no follow-up is answered out of a top-k result.
