# ISSUE-0047 — A partial ingest resumes

Status: open
Type: **HITL**
Source: reverses ISSUE-0035 §"Not in this slice"
Covers: reusing the embeddings a killed ingest already paid for

## Why this exists

ISSUE-0035 is resolved, and it decided against this twice — once in its
reasoning and once in what it excluded:

> **Retry re-ingests, it does not re-upload.** The bytes are in the object
> store, so a retry costs the embedding again — about two cents — and nothing
> else. Starting over rather than resuming is deliberate: resuming would mean
> chunks belonging to no Module, which is a class of partial state worth more
> than the two cents it would save.

A reversal nobody writes down is indistinguishable from a rule nobody read, so
this is a ticket rather than a change.

## What the objection is, and what it is not

The objection is precise and it is right: **a chunk belonging to no Module is a
class of partial state worth more than two cents.** It is not a cost argument
with a tolerance; it is a structural one, and it does not get cheaper.

It is also narrower than "do not resume". `finish_ingest` writes Topics and
chunks in one transaction, so a killed run leaves no orphan — that is what makes
the current retry safe, and nothing here proposes weakening it. What 0035 read
as the only way to resume was persisting `notebook_chunk` rows incrementally,
which does produce chunks with no Topic.

There is a second thing a killed run leaves behind, and 0035 does not consider
it: **the vectors themselves**. A vector keyed by content hash is not a chunk.
It has no Topic, no Module, no order and no place in a Corpus — it is a cached
answer to "what does this text embed to", and it is either present or absent.
It cannot be partially anything, which is the whole of the objection.

`ReusingEmbedder` already exists and already does this — it keys vectors by
`digest(text)` and is documented as being for exactly this case:

> An ingest that failed halfway leaves chunks already embedded and already
> stored. Resuming it must not pay for them again.

It reads `notebook_chunk`, which `finish_ingest` never wrote. So the mechanism
is built, is reasoned about, and in the case it names does nothing.

## What has to be decided

**Is the cost premise still two cents?** That is the question this ticket cannot
answer from inside the repository, and it is the one that decides it.

`estimate()` in `service/notebooks/metering.py` costs an ingest at
`credits_per_1k_tokens` against a token count taken before the first provider
call — so the number is a measurement and can be read off real ingests rather
than guessed. Two cents was true of a small document on the embedder in use when
0035 was written. What matters now:

- What a 200-page PDF costs on the embedder actually being shipped. ISSUE-0035
  puts one at roughly forty seconds of wall clock, which is the other half of
  the price: a Candidate watching a progress bar restart from zero is paying in
  something the ledger does not record.
- How often this fires. Every restart during a deploy fails every in-flight
  ingest by design — `reset_stale_ingests` is correct and stays. The question is
  how many that is per deploy, and how many deploys there are.

If the answer is still two cents and it happens twice a month, 0035's decision
stands and this ticket should be closed unbuilt. Complexity that buys nothing is
worse than the cost it saves.

## Scope if approved

- A staging table in the `content` schema — `(notebook_id, content_hash,
  embedding_model) → vector`, written in its own short transaction as each embed
  batch returns. It holds no Topic, no Module and no ordering, and it is not read
  by anything that composes a Corpus.
- `embeddings_by_hash` unions it, scoped to the same `embedding_model`. A vector
  from another model is a different space and must not be reused (ADR-0017).
- Cleared inside `finish_ingest`'s existing transaction: once the chunks are in
  `notebook_chunk`, the staging rows are a second copy of a thing that already
  has a home. `delete_source` clears them too.
- No change to chunking, clustering, mining or freezing. They are deterministic
  and cheap; a retry re-runs them against reused vectors and mints the same
  `topic_id`s, because `topic_id_for` derives from sorted chunk hashes.

## What must not change

- `finish_ingest` stays one transaction. Topics and chunks are written whole or
  not at all.
- `ready` stays an unclaimable state, so a completed ingest is not retried and
  cannot bill twice.
- The debit stays keyed on `call_id = f"ingest:{source_id}"` against
  `uq_ledger_debit_call`. A resumed run reports fewer `embedded_tokens`, which is
  the true number; it must not become a second debit.
- `reset_stale_ingests` still fails every `ingesting` row at boot. Resuming is
  about what a retry pays, not about a worker surviving a restart — no worker
  survives a restart, and none is proposed.

## Blocked by

Nothing technically. Open on the cost measurement above, and on a signature
reversing ISSUE-0035.
