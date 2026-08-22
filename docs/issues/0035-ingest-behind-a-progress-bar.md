# ISSUE-0035 — A document is in the Library before it is ingested

Status: open
Type: AFK
Source: SPEC-0006 §The open problem; SPEC-0000 §refusals; ISSUE-0023, ISSUE-0026
Covers: a forty-second import nobody stares through, and an upload that survives it

## What to build

Embedding a 200-page PDF takes roughly forty seconds, and SPEC-0000 refuses
Redis and a message queue outright. So the work runs in-process, the surface
polls — and the **upload and the ingestion are separated**, which is the part
that makes a failure survivable.

**A Source exists as soon as its bytes do.** Upload stores the file (ISSUE-0033)
and writes the Source row immediately, so the document appears in the Library at
once, marked as not yet ingested. Ingestion starts by itself.

**A Module still appears only when ingestion completes.** This is not a
weakening of ISSUE-0026's atomicity — it is the distinction that ADR-0023
already drew and that this slice finally uses. A stub is "a Module that exists,
is visible, and states why it carries nothing", and `notebook_source.state` is
already `ready | stub`. An un-ingested document is another state on that column,
not a new concept. No partial Module, no orphan Topics, no chunks belonging to
nothing, no double billing — all of that stays exactly as it is.

So the states are: **uploaded → ingesting → ready**, with **failed** beside them
and `stub` unchanged.

**A killed worker is detectable without a timeout.** The worker runs in-process,
so no worker survives a restart — which means any row still marked `ingesting`
when the process starts is stale by definition. Reset them at boot rather than
guessing at how long is too long. A stalled worker in a *live* process is the
harder case and needs elapsed time and last progress reported, not a guessed
deadline.

**Retry re-ingests, it does not re-upload.** The bytes are in the object store,
so a retry costs the embedding again — about two cents — and nothing else.
Starting over rather than resuming is deliberate: resuming would mean chunks
belonging to no Module, which is a class of partial state worth more than the
two cents it would save.

**The poll is doing two jobs.** It drives the progress readout, and because an
idle host spins down and any inbound request resets that timer, it keeps the
server alive while somebody is watching. That is a side effect of a request we
need anyway rather than a keep-alive built for its own sake — the free tier
allows roughly one instance running full time, and holding it awake deliberately
would spend the whole allowance on nothing.

## On the surface

The Library lists every document with its state. Progress is work done against
work found — sections embedded of sections found — never an indeterminate
spinner, because forty seconds of spinner is indistinguishable from a hang.

A document that is not `ready` is listed and **not selectable for a Session**.
The surface already handles this: `ScopePicker` filters on `selectable` and
`Confidence` disables the cell. What it has never done is say *why* — nothing
renders `stub_reason` today, so ISSUE-0023's "states why it carries nothing" has
been unfulfilled on the surface since it was written. This slice delivers it, for
stubs and for un-ingested documents alike.

## Acceptance criteria

- [ ] An uploaded document appears in the Library immediately, before ingestion
- [ ] Adding a Source returns at once and does not block on embedding
- [ ] Ingestion starts automatically after upload
- [ ] Progress reports work done against work found, never an indeterminate state
- [ ] A document that is not ready is listed, not selectable, and says why
- [ ] `stub_reason` is rendered on the surface, for stubs as well as for failures
- [ ] A killed process leaves the Source listed and marked failed, never stuck ingesting
- [ ] Rows left `ingesting` are reset at startup, since no worker survives a restart
- [ ] A failed document offers Retry, and retrying re-ingests without re-uploading
- [ ] A retry is billed as a fresh ingest and never double-charges a completed one
- [ ] A killed run still leaves no Module, no chunks and no ledger entry
- [ ] A Source already ingesting refuses a second start, so two tabs cannot run it twice
- [ ] Polling stops when the job ends and does not hold the process awake afterwards
- [ ] A completed ingest appears as a usable Module without a reload

## Blocked by

- ISSUE-0033 — the bytes must be durable before the Source can outlive its ingest
