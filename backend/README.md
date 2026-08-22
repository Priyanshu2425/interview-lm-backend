# backend

The Python implementation (ADR-0009), built from the thirteen slices in
`docs/issues/`. Every module names the ADR or PRD that decides its shape.

## Running it

```bash
python3 -m venv .venv && .venv/bin/pip install -e backend
docker run -d --name cortex-pg -e POSTGRES_PASSWORD=cortex -e POSTGRES_USER=cortex \
  -e POSTGRES_DB=cortex -p 55432:5432 pgvector/pgvector:pg16

.venv/bin/python -m pytest backend/tests -q          # 462 tests
.venv/bin/uvicorn interviewer.api.app:app --port 8000 # the API
```

Without `OPENROUTER_API_KEY` the provider transport is a deterministic
stand-in, so everything runs offline. With it, real calls are metered.

Validate a Corpus on its own:

```bash
.venv/bin/python -m interviewer.corpus.cli data/corpus.json
```

## Layout

| Package | Owns | Decided by |
|---|---|---|
| `corpus/` | the Adapter contract, the Dossier Loader, conformance | PRD-0001, ADR-0005, ADR-0007 |
| `confidence/` | Beta math, the Evidence Floor, the stores, selection | PRD-0002, ADR-0003, ADR-0004 |
| `graph/` | the state machine, ports, the Session runner | PRD-0003, ADR-0001, ADR-0011 |
| `judge/` | the blind Judge, the Question Writer, the agentic region, re-judging | ADR-0002 |
| `metering/` | the chokepoint, credits, key custody, the operator readings | PRD-0005, ADR-0008, ADR-0013, ADR-0014 |
| `mcp/` | the tool surface and the invariants that survive it | PRD-0004, ADR-0006 |
| `identity/` | Candidates, and the indirection to an IdP | ADR-0012 |
| `db/` | the `core` schema; `graph` belongs to the checkpointer | ADR-0010, SPEC-0002 |

## Where the design is enforced rather than described

Most of the guarantees are constraints and static checks, not conventions:

- **One Visit, one Evidence row** — `UNIQUE(evidence.topic_visit_id)`, and the
  closing write is one transaction, so a repeated grade aborts rather than
  half-applies.
- **A Session will not advance while a Visit is unresolved** — a partial unique
  index on `topic_visit(session_id) WHERE state IN ('open','answered')`. This is
  what survives an MCP host that ignores every prompt.
- **Scope and duration are immutable** — a database trigger, because it must
  survive a careless service method.
- **Evidence is append-only** — no UPDATE or DELETE reaches it.
- **A posterior cannot fall below the prior** — `CHECK (alpha >= 1 AND beta >= 1)`.
- **An unmetered call is impossible** — `test_architecture.py` fails the build if
  anything outside `metering/` imports an HTTP client.
- **Coverage and Mastery never fuse** — there is no function or response field
  that returns them combined. The rule is an absent API.
- **No Credit message can reach a BYOK Candidate** — checked exhaustively over
  the whole input space, not by example.
- **Nothing reaches for the clock or randomness** outside `ports.py` and the
  composition root, so a Session replays exactly.

## Story coverage

`docs/STORY-COVERAGE.md` maps all 191 user stories to a module and a test.
`test_story_coverage.py` verifies that map on every run, so the claim fails
loudly if a PRD gains a story nothing implements.
