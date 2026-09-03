  # backend

The Python implementation (ADR-0009), built from the slices in `docs/issues/`.
Every module names the ADR or PRD that decides its shape.

**This directory is the root of the backend, not a package inside one.** The
image, the tooling, the pinned dependencies and the environment files are all
here, and the Docker build context is this directory:

```
backend/
  src/interviewer/     the packages, listed under Layout below
  tests/               1,087, run from the repository root
  scripts/             the tooling — see below
  knowledge/           notes kept where they were written: the schema, and
                       what serving the surface from here would take
  deploy.sh            the whole deployment — setup, update, start, status, logs
  create_example_env.sh  puts the right example env file in place before setup
  Dockerfile           built as `docker build backend/`
  .dockerignore        what to keep out of the context
  pyproject.toml       what the Notebook Adapter cannot work without
  requirements.txt     the runtime set the image installs, pinned
  requirements-dev.txt  that plus pytest and pillow
  .env.example         every variable the code reads, all fifty
  .env.prod.example    the eleven a deployment decides
  package.json         playwright, for the Node scrapers at the repository root
```

Everything in `scripts/` is run **from the repository root**, not from here —
the tooling addresses `data/`, `backend/.env` and `.auth/` relative to the
working directory:

| `backend/scripts/` | |
|---|---|
| `import_corpus.py` | **deprecated** — a conformant Corpus into Postgres. Resumable, no-op per Module on a re-run. Create and populate a shared Skill through the admin dashboard instead; this script still backs bulk structured loads via `POST /v1/operator/skills/{id}/import` |
| `pin_requirements.py` | regenerates `requirements.txt` from the environment the suite passes in |
| `reset_core.py` | drops and rebuilds the `core` schema. It destroys Evidence, so it asks twice — `INTERVIEWER_ALLOW_DESTRUCTIVE_RESET=1` and `--confirm-host`, the host read off the DSN rather than from memory |
| `reset_embeddings.py` | re-embeds every notebook with the configured provider |
| `publish_model.py` | a Hugging Face checkpoint to the bucket, so a boot needs no hub |
| `dev-auth-setup.sh` | makes a machine able to sign in against Gatehouse locally |

The Node scrapers are **at the repository root**, not under `backend/`, because
they are not the backend: they produce `data/`, and the image's build context
does not reach them (ADR-0007, ADR-0009). `backend/package.json` carries their
one dependency.

| repository root | |
|---|---|
| `scrape.mjs` | the InterviewLM Corpus Adapter (ADR-0007). Node, and not ported (ADR-0009) |
| `login.mjs`, `recon.mjs`, `api-probe.mjs`, `verify.mjs` | the scraper's supporting tools |
| `ingest-transcripts.mjs` | fills stub Classes from `data/pending-transcripts.json` |

`deploy.sh` (this directory) handles everything: deployment via systemd
(`setup`, `update`) and local container management (`build`, `start`, `stop`,
`status`, `logs`). It embeds the systemd unit and the logrotate config, so no
other directory is needed and there is nothing to keep in step with it.

The env file is named by the mode and the service is installed against that
name, so a `--local` service and a `--prod` service on one box do not read each
other's file:

| | env file | from |
|---|---|---|
| `deploy.sh setup --prod` | `backend/.env` | `.env.prod.example` — the eleven a deployment decides |
| `deploy.sh setup --local` | `backend/.env.local` | `.env.example` — every variable, with its default |

`create_example_env.sh --prod` and `--local` copy the matching example into
place. It copies rather than generating its own template: a third listing of
the variables is a third listing to keep true, and the two examples are the
ones the code is read against.

## Running it locally

Local only. The deployment is a VPS talking to Neon — `.env.prod.example` in
this directory is that set, and `deploy.sh` is what runs it.

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt
backend/.venv/bin/pip install -e backend
docker run -d --name cortex-pg -e POSTGRES_PASSWORD=cortex -e POSTGRES_USER=cortex \
  -e POSTGRES_DB=cortex -p 55432:5432 pgvector/pgvector:pg16
docker exec cortex-pg createdb -U cortex cortex_test        # the suite's own

backend/.venv/bin/python -m pytest backend/tests -q         # 1,087 tests
backend/.venv/bin/uvicorn interviewer.app:app --port 8000   # the API
```

**Two databases on the one container, and the second is not optional.** The
suite runs against `cortex_test` and every fixture truncates — so pointing it
at `cortex` empties the development database a developer is signed into in
another window, and the damage reads later as "why am I being asked to onboard
again". `INTERVIEW_LM_TEST_DATABASE_URL` names a different one if you want it
elsewhere.

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

Setting `DATABASE_URL` — or uncommenting the line in `backend/.env` and
sourcing it — redirects **every local run** at the shared database. It is not
hypothetical: the `cltv` app's suite did exactly this, inserting rows and
creating schemas on the shared instance before anyone noticed.

What guards you, and what does not:

- **The test suite is pinned, and it is pinned by redirection.**
  `backend/tests/conftest.py` drops `GRAPH_DATABASE_URL` and
  `INTERVIEW_LM_DATABASE_URL` and *sets* `DATABASE_URL` to `cortex_test`, before
  anything imports the engine. Merely clearing it was half a guard: it stopped
  the tests reaching Neon and then let them fall through to the development
  database, which the fixtures then truncated.
  `INTERVIEW_LM_TEST_ALLOW_REMOTE_DB=1` is the deliberate way past it.
- **Nothing reads `.env` on its own.** No `load_dotenv` anywhere. It reaches a
  process through `uvicorn --env-file` or `docker run --env-file`, and through
  nothing else.
- **`set -a; . ./backend/.env` does not work, and fails quietly.** A hosted
  Postgres URL carries query parameters, so it contains `&` — which a shell
  reads as "run the preceding command in the background". `zsh` answers
  `parse error near '&'`, the assignment never happens, `DATABASE_URL` stays
  unset, and the next command connects to **local Postgres** while looking like
  it was configured. Do not fix it by quoting the value either: `--env-file`
  takes everything after `=` literally, so the quotes become part of the URL.
  Use `--env-file`, or pull one variable out on its own:

  ```bash
  DATABASE_URL="$(grep '^DATABASE_URL=' backend/.env | cut -d= -f2-)" \
    backend/.venv/bin/python backend/scripts/import_corpus.py ...
  ```

  The prefix form matters: it exports for that one command. A bare assignment
  on its own line sets a shell variable the command never sees, and the symptom
  is again local Postgres.
- **Nothing guards the app server or the scripts.** `uvicorn --env-file` and
  everything in `backend/scripts/` will go wherever you point them.

### Which database am I on?

```bash
backend/.venv/bin/python -c "import sys;sys.path.insert(0,'backend/src');\
import sqlalchemy as sa;from interviewer.db.engine import dsn;\
print(sa.engine.make_url(dsn()).host)"
```

`127.0.0.1` is local. Anything ending `.aws.neon.tech` is the shared database.

### Migrations

There are none, and no alembic. `create_core` and `create_content` apply their
DDL idempotently on every boot, and `create_content` also installs pgvector and
the HNSW index (ADR-0017). `create_graph` is separate and runs against the
direct endpoint, so `interview_lm_graph` stays empty until the first Session —
an absent graph schema on a fresh deployment is expected, not a fault. The role may `CREATE EXTENSION vector`; it has been
installed on the shared project already.

Importing the shipped Corpus is a separate, resumable step, and a no-op per
Module on a re-run. **This script is deprecated** — the admin dashboard's "New
Skill" plus drag-and-drop upload is the documented way to create and populate a
shared Skill going forward; this remains the way to bulk-load pre-structured
material (it drives the same `POST /operator/skills/{id}/import` route):

```bash
DATABASE_URL="$(grep '^INTERVIEW_LM_DATABASE_URL=' backend/.env | cut -d= -f2-)" \
  backend/.venv/bin/python backend/scripts/import_corpus.py --title "InterviewLM"
```

One variable, for one command, and never exported — which is the whole point.
`grep | cut` rather than sourcing because the file cannot be sourced, and
because promoting the parked name to `DATABASE_URL` for the length of a single
invocation is what keeps it from applying to the next one.

## Layout

`src/interviewer/` is layered, and the layer is the directory (ADR-0027). A
name says which layer a file is in before it says what it does, so the import
direction is readable from the path alone: routes call services, services call
repositories, repositories are the only things that touch a table, and
`adapters/` is where every foreign system is spoken to.

| Directory | Owns |
|---|---|
| `app.py`, `wiring.py`, `deps.py`, `deps_async.py` | the composition root — the app, and what is handed to what |
| `config/` | every environment variable, read once, defaults in code |
| `routes/v1/` | the HTTP surface: skills, sessions, candidate, notebooks, operator, health |
| `model/` | the request and response shapes, one file per subject |
| `service/` | the business logic, listed below |
| `repository/` | data access. `async_*` is the request path; `core/` is the sync one the graph runs on |
| `db/` | the schemas themselves, and the engines — `core`, `content`, and the graph checkpointer's |
| `adapters/` | the foreign systems, one file each: `openrouter.py`, `gatehouse.py`, `s3.py` (ADR-0027) |
| `middleware/` | rate limiting, request logging, security headers |
| `security/` | token verification, and who the caller is |
| `mcp/` | the tool surface and the invariants that survive it (PRD-0004, ADR-0006) |
| `exception/`, `util/` | the failure vocabulary, and the small shared functions |
| `ingest_worker.py` | ingest, in a thread, in this process — SPEC-0000 refuses a queue |

And the packages under `service/`, which are where the product actually lives:

| Package | Owns | Decided by |
|---|---|---|
| `corpus/` | the Adapter contract, the Dossier Loader, conformance, the Notebook sources | PRD-0001, ADR-0005, ADR-0007 |
| `confidence/` | Beta math, the Evidence Floor, selection | PRD-0002, ADR-0003, ADR-0004 |
| `graph/` | the state machine, ports, the Session runner | PRD-0003, ADR-0001, ADR-0011 |
| `judge/` | the blind Judge, the Question Writer, the agentic region, re-judging | ADR-0002 |
| `metering/` | the chokepoint, credits, key custody, the operator readings | PRD-0005, ADR-0008, ADR-0013, ADR-0014 |
| `notebooks/` | a Candidate's own material: upload, ingest, reading, citations | ADR-0017, ISSUE-0033 |
| `embeddings/` | the provider registry — `hashing`, `siglip`, `http`, `openrouter` | ADR-0019 |
| `identity/` | Candidates, and the indirection to an IdP | ADR-0012, ADR-0026 |
| `ending_service.py` | the one reading a Session ends with | ISSUE-0045 |

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
  anything outside `service/metering/` constructs a provider client.
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
