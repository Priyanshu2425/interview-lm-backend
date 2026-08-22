# The BYOK gap at ingest closed itself

Status: **accepted** — supersedes the question ADR-0016 was asked to answer

## What ADR-0016 was for

ADR-0008 chose OpenRouter as the only route. ADR-0016 then recorded a problem
that followed from it:

> ADR-0008 says BYOK accepts **OpenRouter keys only**, and OpenRouter is a chat
> completions gateway. So a Candidate who attached their own key has, at ingest
> time, a key that cannot do the work.

It offered three answers — ingest on the pool, notebooks require Credits, or
accept a second key type — recommended the first, and was left unsigned because
none of them is obviously right and an agent should not pick one alone.

## What changed

OpenRouter now serves embeddings, at `POST /api/v1/embeddings`, including
`google/gemini-embedding-2-preview` at $0.20 per million tokens.

The premise is gone. A BYOK Candidate's key can embed. There is no gap to
choose an answer to, and the fourth option — the one none of the three
anticipated — is that the question stopped being asked.

## What this decides

**Embeddings go through OpenRouter**, the same gateway and the same key as
grading. This is ADR-0008 being *satisfied* rather than worked around: one
route, one credential, and one chokepoint where a call can be counted, which is
what SPEC-0005 means when it says an unmetered call must be impossible rather
than discouraged.

**A BYOK Candidate's ingest bills their key**, exactly as their Sessions do,
which is what BYOK promised in the first place. ADR-0016's Principle 3 concern —
that a BYOK Candidate must never see a Credit message — is unaffected and still
enforced: they are shown the provider, the model and the token count.

**ADR-0016 is superseded rather than signed.** It stays in the record because
the reasoning is still the reasoning a reader will want if OpenRouter ever drops
embeddings again, but its three options are moot and no human owes a decision on
them.

## What did not change

**Paid is still opt-in.** `EMBEDDING_ALLOW_PAID=1` is still required before any
billing provider is selected, and the registry still refuses at boot without it.
The gate was written for ADR-0016's problem and outlives it for a better reason:
a deployment should never start spending money because a default moved.

**Local stays the default.** `EMBEDDING_PROVIDER` still defaults to the lexical
stand-in, and SigLIP still runs locally at zero cost (ADR-0017). Nothing about
this ADR makes a deployment start paying; it makes paying *possible*, on one
route, with one key.

**Our own numbers.** Cost is computed from our own token counts and our own
arithmetic (ADR-0014). The provider's dashboard is the authority on what was
actually spent; what we compute is what we would have billed.

## The dimension consequence

Gemini's embeddings are Matryoshka-trained, so a prefix of a longer vector is a
usable embedding once re-normalised — and re-normalising is not optional,
because every similarity in this system is a dot product that assumes unit
length. The store holds `vector(768)` (ADR-0017), 768 is one of the widths
Google recommends, and a wider return is truncated to it rather than triggering
a migration.

A *narrower* return is refused. Padding a vector to fit a column would be
inventing dimensions, and it would be undetectable afterwards.

## Consequence worth naming

Changing embedding provider is now a change of vector space, on a route that
bills. Both were already true of ADR-0017's `http` provider; what is new is that
the easy path — the key already in the environment — leads there. `re_embed()`
carries Topic memberships across a model change as stored data, and the Corpus
index refuses to serve edges it did not build (ADR-0018), so the machinery for
crossing spaces exists. What does not exist is a reason to cross casually.
