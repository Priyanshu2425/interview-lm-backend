# SPEC-0000 — Stack, project structure and contracts

Cross-cutting. Governed by ADR-0009 through ADR-0013.
Read this before any other spec; every other document assumes what is settled here.

---

> **Note (2026-08-27).** `design-system/` was removed from this repository. The
> surface is built from the design files outside it — see `DESIGN.md` and
> `AGENTS.md`. Paths naming `design-system/` below are kept as written: they
> record what this was built against at the time, and they resolve in git
> history rather than in the working tree.

## 1. The stack

| Layer | Choice | Why this and not the obvious alternative |
|---|---|---|
| Backbone runtime | **Python 3.12** | ADR-0009: park/resume/replay maturity is the whole reason |
| Graph | **LangGraph** + `AsyncPostgresSaver` | ADR-0001, ADR-0003 |
| API | **FastAPI** + Uvicorn | Async throughout; the turn endpoint is long-running and IO-bound |
| Validation | **Pydantic v2** | The Adapter contract (PRD-0001) is validated at ingest, so a schema library is load-bearing, not decoration |
| Store | **Postgres 16**, managed | ADR-0010; partial unique indexes carry the idempotency invariants |
| DB access | **SQLAlchemy 2.0 Core** + Alembic | Core, not the ORM: the writes that matter are explicit `alpha = alpha + $1` statements, and an ORM's identity map is the wrong shape for that |
| Math | **NumPy + SciPy** | `scipy.stats.beta` gives the posterior interval the **Evidence Floor** bands read off |
| Provider | **OpenRouter** over `httpx` | ADR-0008. No vendor SDKs — one route or the metering chokepoint is a fiction |
| MCP | **`mcp` Python SDK** | ADR-0009: same process family as the stores it must protect |
| Secrets | **Managed KMS** (envelope) | ADR-0013 |
| Tests | **pytest** + `pytest-asyncio` + **testcontainers** | Real Postgres, because every invariant here is a constraint |
| Surface | **Astro + TypeScript**, islands only where state lives | SPEC-0003 |

**Deliberately absent.** No vector store (ADR-0005). No Redis. No message
queue. No ORM identity map on the write path. No provider SDKs. Each is a thing
a reader will assume was forgotten; each is refused above.

## 2. Repository layout

```
interview-lm/
  backend/                      # Python. ADR-0009.
    src/interviewer/
      corpus/                   # PRD-0001 — Corpus Contract, Dossier Loader
      confidence/               # PRD-0002 — Confidence Math (pure), stores
      graph/                    # PRD-0003 — nodes, edges, Session Config
      judge/                    # PRD-0002/0003 — blind grading, versioned rubrics
      metering/                 # PRD-0005 — Metered Model Client, ledgers, keys
      mcp/                      # PRD-0004 — MCP server
      api/                      # FastAPI app; §4 contracts
      db/                       # SQLAlchemy Core tables, Alembic under core/ and graph/
    tests/
  frontend/                     # SPEC-0003.
  adapters/
    cortex/scrape.mjs           # Node, build-time. ADR-0007, ADR-0009.
  design-system/                # tokens + the prototype these are built from
  docs/{adr,prd,spec}/
```

**`confidence/` has no imports from `graph/` or `db/`.** PRD-0002 calls
Confidence Math "the deepest module in the system and the one everything else
depends on being right" — pure functions over `(α, β)` with no storage, clock or
randomness it does not receive. An import-linter contract enforces the direction,
because this is the boundary that erodes first.

`metering/` is the only package permitted to import `httpx` or hold KMS decrypt
permission (SPEC-0005, ADR-0013). Also an enforced contract, not a convention.

## 3. Determinism

PRD-0003 makes replay a requirement, not a nicety: it is the only way to know
whether grading is any good. Three inputs are injected, never called:

- **Randomness** — the Thompson sampler receives a `Generator`.
- **The clock** — the duration check receives a time source.
- **Model responses** — the Metered Model Client is an interface; the replay
  implementation reads recorded responses keyed by `topic_visit_id` and role.

A recorded Session re-run with the same three inputs must produce an identical
Visit sequence and identical scores. This is a test (PRD-0003), and it is the
reason none of these three may be reached for directly anywhere in `graph/`.

## 4. HTTP contract

Versioned under `/v1`. Every mutating call carries `Idempotency-Key`.

```
POST   /v1/sessions                    → 201 {session_id, first_question, topic_visit_id}
GET    /v1/sessions/{id}               → session state, visits, running cost
POST   /v1/sessions/{id}/turns         → the Answer Turn (ADR-0011). Long-running.
                                         Returns when the graph next parks:
                                         {kind: "follow_up"|"hint"|"visit_closed"|"session_ended", ...}
POST   /v1/sessions/{id}/end           → soft end; completes the current Visit
GET    /v1/sessions/{id}/stream        → SSE. Question and rationale text only.
                                         Never advances the graph.
GET    /v1/candidates/me/confidence    → Coverage and Mastery, as separate readings
GET    /v1/candidates/me/credits       → balance, per-Visit ledger
POST   /v1/candidates/me/byok          → attach a key; validated live (SPEC-0005)
DELETE /v1/candidates/me/byok/{key_id}
```

Three rules the contract enforces rather than documents:

1. **No endpoint returns a fused Coverage-and-Mastery figure.** The response
   model has no such field, so it cannot be added by accident (PRD-0002).
2. **No endpoint returns an Answer Key for an ungraded Visit.** Grading material
   is reachable only by the Judge, against a `topic_visit_id` (ADR-0006).
3. **`POST /turns` is idempotent on its key.** A retry returns the original
   result rather than submitting twice — the mechanism ADR-0011 chose a request
   for in the first place.

**Errors** are the taxonomy in SPEC-0005 §5, serialized as
`{code, message, route, recoverable}`. `code` is one of the enumerated events;
`route` is present so the BYOK/Credits separation is checkable at the boundary
as well as in the message.

## 5. Deployment

Two deployables from the backbone, one image:

- **api** — FastAPI, N replicas, stateless. Holds KMS decrypt permission.
- **mcp** — the MCP server, same code, different entrypoint.

Plus **surface**, static + light SSR, and **adapters/cortex** which runs
manually and produces `corpus.json` as a build artifact.

The Corpus ships **with the image**, not in the database (ADR-0005: a dossier is
a file read). Re-scraping is a deploy, which is correct — the Corpus is
read-only source material.

**Migrations:** two Alembic trees. `core/` runs on deploy. `graph/` runs only in
a window when no Session is resumable, and the application role holds no DDL on
`core` so a graph migration cannot reach permanent data (ADR-0010).

## 6. Test strategy

Per PRD guidance: assert what a Candidate, auditor or operator would observe.
Never which node ran, how many model calls happened, or what a prompt contained.

| Layer | How |
|---|---|
| Confidence Math | Pure unit tests, no harness. Property tests: repeated identical Evidence narrows the interval while holding the mean |
| Stores | Real Postgres via testcontainers. The constraints *are* the invariants, so an in-memory fake would test nothing |
| Graph | Scripted Sessions with stubbed model responses, injected clock and RNG |
| Judge | Assert on what the Judge *received* — no conversation history, exactly one Answer Key |
| Metering | Static check that no module outside `metering/` constructs a provider client |
| Migrations | Apply every `graph/` migration to a database holding `core` rows; assert those rows are byte-identical |

One test earns its own line: **the classifier may not produce a Credit event on
a BYOK Session**, checked exhaustively over the input space rather than by
example (SPEC-0005).

## 7. What this spec does not decide

1. **Hosting provider.** Nothing above needs a specific cloud; the KMS and
   managed Postgres are the only two managed dependencies.
2. **The identity provider.** ADR-0012 makes this swappable on purpose.
3. **The payment processor.** PRD-0005's boundary is a *payment cleared* event
   in, a grant out.
4. **Observability stack.** Structured logs and per-Visit tracing are assumed;
   the vendor is not chosen.
5. **Whether `surface` and `api` share a domain.** A cookie/CORS decision that
   should be made when auth is implemented, not before.

## Amendment — 2026-08-22, the surface may live elsewhere

§7 closed the CORS question by making it not exist: one origin, so
nothing to configure. ADR-0020 reopens it for deployments that host
the surface on a CDN. `ALLOWED_ORIGINS` and `VITE_API_URL` are both
empty by default, and empty is exactly the arrangement described
above — the single-origin path is still the default and still tested.
