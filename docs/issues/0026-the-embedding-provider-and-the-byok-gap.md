# ISSUE-0026 — The embedding provider, and the BYOK gap

Status: resolved — a local provider fills the port, and the BYOK gap closed itself (ADR-0019)
Type: **HITL**
Source: SPEC 2026-08-21 Notebook Adapter; ADR-0008, ADR-0014, PRD-0005
Covers: spec §Decisions/Ingest cost; §Failure modes (provider failure, model change, insufficient balance)

## Why this one needs a human

ADR-0008 says BYOK accepts **OpenRouter keys only**, and OpenRouter is a chat
completions gateway. A BYOK Candidate whose key cannot embed is a product
decision with three defensible answers — refuse notebooks for BYOK Candidates,
run ingest on the pool while Sessions stay on their key, or accept a second key
type and amend ADR-0008 — and an agent should not pick one alone.

Everything below is buildable in either direction; only the BYOK branch waits.

## What to build

Replace ISSUE-0021's stub embedder with a real provider behind the same port, and
put ingest on the ledger the rest of the product already uses.

Embedding and labelling calls are metered exactly like Session calls: our own
token counts, our own cost arithmetic, provider recorded (ADR-0014). Ingest spend
appears in the existing cost readout.

**No quote and no confirmation gate.** Ingest begins when sources are added.

**An insufficient balance is a refusal, not a quote.** Ingest stops before the
first embedding call and names the shortfall. Nothing is half-ingested.

**Ingest is atomic per source.** A Module appears only after extract, embed,
cluster, label, freeze, dossier build and validate all succeed. A provider failure
mid-run leaves no partial Module. Resume is idempotent: chunks are keyed by
content hash, and an already-embedded chunk is neither re-embedded nor re-billed.

A BYOK Candidate is shown the provider and the token count and **never a Credit
message** (Principle 3), whichever way the BYOK decision lands.

## Acceptance criteria

- [x] Ingest is metered on the existing ledger, idempotent on the Source
- [x] Ingest cost appears in the response and is never quoted before it is spent
- [x] An insufficient balance refuses ingest before the first embedding call and names the shortfall
- [x] A refused ingest leaves no Module, no chunks and no ledger entry
- [x] A provider failure mid-source leaves no partial Module and no orphaned chunks
- [x] Resuming an ingest re-embeds no chunk whose content hash is already stored, verified by call count
- [x] `embedding_model` is recorded on the notebook
- [x] A BYOK Candidate sees provider and token count and no Credit figure anywhere in the ingest path
- [x] The BYOK decision is recorded as an ADR — **ADR-0016, proposed, awaiting a signature**
- [x] Swapping the provider touches only the port implementation
- [x] A real embedding provider fills the port — `google/siglip2-base-patch16-224`
      behind `BaseEmbedder` (ADR-0017)

## How the BYOK block was cleared without deciding it

The blocker was never "which provider" but "who pays". A provider that bills
forces the question; one that does not, does not.

The model ships locally, so `credits_per_1k_tokens` is `0.0` and ingest charges
nobody — which is correct under all three of ADR-0016's answers rather than a
quiet vote for one of them. A provider that *would* bill is refused at boot
unless `EMBEDDING_ALLOW_PAID=1`, and the refusal names the ADR. The decision is
still owed; it is now owed at the moment someone wants a commercial model, which
is the moment they will read it.

## Blocked by

- ISSUE-0021 — the port it fills is defined there
