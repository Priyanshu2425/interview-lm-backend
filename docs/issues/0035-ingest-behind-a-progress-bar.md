# ISSUE-0035 — A document is in the Library before it is ingested

Status: resolved
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

- [x] An uploaded document appears in the Library immediately, before ingestion
- [x] Adding a Source returns at once and does not block on embedding
- [x] Ingestion starts automatically after upload
- [x] Progress reports work done against work found, never an indeterminate state
- [x] A document that is not ready is listed, not selectable, and says why
- [x] `stub_reason` is rendered on the surface, for stubs as well as for failures
- [x] A killed process leaves the Source listed and marked failed, never stuck ingesting
- [x] Rows left `ingesting` are reset at startup, since no worker survives a restart
- [x] A failed document offers Retry, and retrying re-ingests without re-uploading
- [x] A retry is billed as a fresh ingest and never double-charges a completed one
- [x] A killed run still leaves no Module, no chunks and no ledger entry
- [x] A Source already ingesting refuses a second start, so two tabs cannot run it twice
- [x] Polling stops when the job ends and does not hold the process awake afterwards
- [x] A completed ingest appears as a usable Module without a reload

## Blocked by

- ISSUE-0033 — the bytes must be durable before the Source can outlive its ingest

## `ready` has to imply *composed*

The subtle one, and it was a real bug before it was a rule. `ready` is what the
Library shows as examinable, so it must not become true before the served Corpus
contains the Module — otherwise a Candidate who starts a Session the moment the
progress bar fills is told their Module holds no examinable Topic.

So an ingest writes its material, then rebuilds whatever the caller has to
rebuild, then marks the Source ready. `mark_ready` is its own store method for
that reason and says so.

## Progress is measured before the work, not during it

Chunking is local and free, so the work *found* is counted at upload and stored
with the row. The readout therefore starts at `0 of 214` rather than at nothing
of nothing — which is the indeterminate spinner by another name.

Work *done* comes from wrapping the embedder rather than instrumenting the
pipeline: it is the one place that knows, and wrapping means the reading cannot
drift from the work because there is no second counter to keep in step.

## Two clocks are one clock

Elapsed time and time-since-progress are computed in Postgres, from the same
clock that wrote the timestamps. Subtracting one machine's clock from another's
is a duration nobody can defend — and it would also have put `datetime.now()` in
a route, which the architecture test refuses.

## What the split cost, and what it did not

Two existing tests changed their assertions rather than their expectations: a
refused or failed ingest now leaves the document **listed and marked failed**
instead of leaving nothing. That is the slice, stated: the upload outlives the
ingestion. What did not change is what those tests were really protecting — no
Module, no Topic, no chunk, no ledger entry.

## Not in this slice

Resuming a partial ingest. Re-embedding costs about two cents, and resuming
would mean chunks belonging to no Module — a class of partial state worth
considerably more than the two cents it saves.

A stall deadline. A worker that stalls inside a live process reports elapsed
time and time since last progress, and how long is too long is left to whoever
is reading it: it is unknown until real documents have been through this.
