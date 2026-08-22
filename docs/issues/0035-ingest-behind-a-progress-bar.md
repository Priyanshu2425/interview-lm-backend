# ISSUE-0035 — Ingest runs behind a progress bar, and dies cleanly

Status: open
Type: AFK
Source: SPEC-0006 §The open problem; SPEC-0000 §refusals; ISSUE-0026
Covers: a forty-second import that nobody has to stare through

## What to build

Embedding a 200-page PDF takes roughly forty seconds, and SPEC-0000 refuses
Redis and a message queue outright. So the work runs in-process and the surface
polls.

`POST` a Source and it returns immediately with a job id. A background worker
extracts, chunks and embeds. The surface polls for progress and shows how far in
it is — sections done of sections found, not a spinner, because forty seconds of
spinner is indistinguishable from a hang.

**The poll is doing two jobs.** An idle host spins down, and any inbound request
resets that timer, so the progress poll keeps the server alive while somebody is
watching. That is a side effect of a request we need anyway rather than a
keep-alive built for its own sake — which matters, because the free tier allows
roughly one instance running full time and holding it awake deliberately would
spend the whole allowance on nothing.

**Nothing is resumed.** Ingest is already atomic per Source (ISSUE-0026): a
Module appears only after extract, embed, cluster, label, freeze, dossier build
and validate all succeed, so a killed run leaves no Module, no chunks and no
ledger entry. There is nothing half-finished to recover — the Candidate uploads
again, and the second attempt is a first attempt. Re-embedding a 200-page PDF
costs about two cents; resume machinery that must stay correct forever to avoid
that is not worth having.

A job that stops making progress must be distinguishable from one that is slow.
How long is too long is unknown until real documents have been through it, so
report elapsed time and last progress rather than guessing at a timeout.

## Acceptance criteria

- [ ] Adding a Source returns at once with a job id and does not block
- [ ] Progress reports work done against work found, not an indeterminate state
- [ ] A finished job names the Module it produced
- [ ] A failed job names why, in a code the surface can render
- [ ] A killed worker leaves no Module, no chunks, no objects and no ledger entry
- [ ] Re-uploading after a failure succeeds and is charged as a first attempt
- [ ] Polling stops when the job ends, and does not hold the process awake afterwards
- [ ] Two tabs polling one job do not start it twice
- [ ] The surface shows progress and a completed Library entry without a reload

## Blocked by

- ISSUE-0033 — the bytes must land before the work is moved off the request
