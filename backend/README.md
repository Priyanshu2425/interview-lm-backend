# backend

The Python implementation (ADR-0009), built from the slices in
`docs/issues/`. Every module names the ADR or PRD that decides its shape.

## Running it locally

Local only. The deployment is a VPS talking to Neon — `.env.prod.example` at
the repository root is that set, and `deploy/` is what runs it.

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
.venv/bin/pip install -e backend
docker run -d --name cortex-pg -e POSTGRES_PASSWORD=cortex -e POSTGRES_USER=cortex \
  -e POSTGRES_DB=cortex -p 55432:5432 pgvector/pgvector:pg16

.venv/bin/python -m pytest backend/tests -q           # 840 tests, ~100s
.venv/bin/uvicorn interviewer.api.app:app --port 8000 # the API
```

The container keeps the name it was created with. It is local scratch: drop it
and re-create it whenever, the suite builds every schema it needs.

`pip install -e backend` on its own is not enough to run any of the above.
`pyproject.toml` declares only what the Notebook Adapter cannot work without
and leaves the rest of the runtime to the deployment — so it installs neither
the API you are importing nor the runner importing it.
`requirements-dev.txt` is the pinned runtime set plus pytest, and is the one
to install.

Without `OPENROUTER_API_KEY` the provider transport is a deterministic
stand-in, so everything runs offline. With it, real calls are metered.

Validate a Corpus on its own:

```bash
.venv/bin/python -m interviewer.corpus.cli data/corpus.json
```

## Database

**Local is the default and is what the test suite always uses.** `docker run`
above starts it on port 55432; with nothing set, the application connects there.
Nothing but a deployment should ever point at Neon.

**Shared.** The deployment runs on the shared Neon project, where this app owns
the schemas below and reaches them through the reduced-privilege
`interview_lm_app` role. The registry recording that is
`~/Desktop/buildspace/neon`.

Three schemas, because ADR-0010 splits them by lifecycle:

| Schema | Holds | Lifecycle |
|---|---|---|
| `interview_lm_core` | Evidence, Topic Confidence, Sessions, ledger, BYOK rows | permanent |
| `interview_lm_content` | the Corpus: notebooks, Topics, `vector(768)` chunks | rebuildable by re-import |
| `interview_lm_graph` | the LangGraph checkpointer | dropped outside the resumption window |

| Variable | Local default | Shared |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://cortex:cortex@127.0.0.1:55432/cortex` | the Neon pooled URL |
| `GRAPH_DATABASE_URL` | unset — derived by dropping `-pooler` | set only if the direct endpoint is named differently |

A URL without a driver (`postgresql://…`, which is what every dashboard hands
you) is read as psycopg2, which this project does not install. `with_driver`
names psycopg on the way past, so a pasted URL works.

### The trap

Setting `DATABASE_URL` — or uncommenting the line in the repo's `.env` and
sourcing it — redirects **every local run** at the shared database. It is not
hypothetical: the `cltv` app's suite did exactly this, inserting rows and
creating schemas on the shared instance before anyone noticed.

What guards you, and what does not:

- **The test suite is pinned.** `backend/tests/conftest.py` clears
  `DATABASE_URL`, `GRAPH_DATABASE_URL` and `INTERVIEW_LM_DATABASE_URL` before
  anything imports the engine. `INTERVIEW_LM_TEST_ALLOW_REMOTE_DB=1` is the
  deliberate way past it.
- **Nothing reads `.env` on its own.** No `load_dotenv` anywhere; only
  `uvicorn --env-file` and an explicit `set -a; . ./.env` do.
- **The line in `.env` is commented out**, and says why. Do not delete it — the
  password was generated at provisioning, written only there, and never printed.
- **Nothing guards the app server or the scripts.** `uvicorn --env-file` and
  everything in `backend/scripts/` will go wherever you point them.

### Which database am I on?

```bash
.venv/bin/python -c "import sys;sys.path.insert(0,'backend/src');\
import sqlalchemy as sa;from interviewer.db.engine import dsn;\
print(sa.engine.make_url(dsn()).host)"
```

`127.0.0.1` is local. Anything ending `.aws.neon.tech` is the shared database.

### Migrations

There are none, and no alembic. `create_core` and `create_content` apply their
DDL idempotently on every boot, and `create_content` also installs pgvector and
the HNSW index (ADR-0017). The role may `CREATE EXTENSION vector`; it has been
installed on the shared project already.

Importing the shipped Corpus is a separate, resumable step, and a no-op per
Module on a re-run:

```bash
set -a; . ./.env; set +a            # with the URL uncommented
DATABASE_URL="$INTERVIEW_LM_DATABASE_URL" \
  .venv/bin/python backend/scripts/import_corpus.py --title "InterviewLM"
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
