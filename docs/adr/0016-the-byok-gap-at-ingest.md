# The BYOK gap at ingest

Status: **superseded by ADR-0019** — OpenRouter now serves embeddings, so the
gap this ADR was written about no longer exists. Kept because the reasoning
is what a reader will want if that ever changes back. No decision is owed.

ADR-0008 says BYOK accepts **OpenRouter keys only**, and OpenRouter is a chat
completions gateway. Ingesting a notebook needs embeddings. So a Candidate who
attached their own key has, at ingest time, a key that cannot do the work.

Everything else in ISSUE-0026 is built and tested: ingest is measured in our own
token counts, gated on balance before the first provider call, charged only on
what was actually embedded, idempotent per Source, and atomic — a Source lands
whole or leaves nothing behind. The embedder is reached through a port, so the
provider swap is one class.

What is not decided is what a BYOK Candidate's notebook costs, and to whom.

## The three defensible answers

**A. Ingest runs on the pool; Sessions stay on the key.** The Candidate is told
which ledger each act is on, which is Principle 3 working as intended. Costs us
real money for a Candidate who is otherwise self-funding, and the amount scales
with how much material they upload — the one number they control freely.

**B. Notebooks require Credits; BYOK Candidates top up to ingest.** Honest and
symmetric — the Candidate pays for the work they asked for. But it means a
Candidate who attached a key to avoid our billing hits our billing anyway, at
the first thing they try.

**C. Accept a second key type and amend ADR-0008.** Truest to BYOK's promise:
their material, their provider, their bill. Costs a second key in the vault, a
second validator, a second failure classifier, and it reopens a decision that
was deliberately closed.

## What is implemented while this is open

The metering path treats `route == "byok"` as **zero Credits and no Credit
message** — the Candidate is shown the provider, the embedding model and the
token count, and nothing else. That is correct under A and under C, and it is
the least-committal behaviour under B, because it charges nobody rather than
charging the wrong party.

The local embedder that ships today costs nothing to run, so no Candidate is
currently affected either way. The decision becomes real the moment a
provider-backed embedder is switched on, which is why it is recorded now rather
than discovered then.

## Recommendation

**A**, on the grounds that ingest is one-off and bounded while a Session is
open-ended: the cost we would absorb is a function of the material a Candidate
uploads once, not of how long they practise. It also keeps the first thing a new
Candidate does free of a billing wall, and it needs no change to ADR-0008.
