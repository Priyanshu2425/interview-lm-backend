# InterviewLM

A Python graph examines a Candidate on a Corpus and keeps an honest record of
what they can actually explain. A React surface renders what it decides.

Reading is not preparation; the examination is the product. Success is a
Candidate who knows which Topics they were tested on, which look weak, and —
critically — which they have never been asked about at all.

Two things follow from that, and both run all the way down to the schema:

- **Untested and weak are different facts.** Topic Confidence is a Beta
  distribution (`α`, `β`) per Candidate per Topic. Mastery is its mean,
  Coverage its evidence count, Confidence its spread. They are never fused into
  one percentage — not in a response field, not on a screen. A product storing
  a single score cannot tell an unasked Topic from a failed one, which is
  exactly what choosing the next question requires.
- **The grader never held the conversation.** The Judge is a separate, blind
  call: it sees the question, the answer and the grounding, and has no memory
  of the Candidate having been articulate or likeable. Sycophancy here is not a
  prompt defect, it is conversational context working as intended.

`PRODUCT.md` is the full statement, and `AGENTS.md` lists the rest of the
refusals — each one enforced as an **absent API**, a call that does not exist
so it cannot be made by accident.

## What is in this repository

| | |
|---|---|
| `backend/` | the API, the graph, the Judge, metering — all of the Python |
| `docs/` | 26 ADRs, 5 PRDs, 5 specs, 37 implementation slices |
| `scripts/` | Corpus import, scraping, embedding maintenance, dev auth |
| `design-system/` | the retired predecessor. Nothing is built from it |

Two things are deliberately **not** here:

- **The surface.** `frontend/` is its own git repository
  ([interview-lm-frontend](https://github.com/Priyanshu2425/interview-lm-frontend)),
  ignored by this one and not a submodule — it talks to the backend over HTTP
  and shares nothing else, and tying the histories together would imply a
  coupling that does not exist (ADR-0009). A clone of this repo has no surface,
  which is why the Docker image builds an API and nothing else.
- **The Corpus.** `data/` holds InterviewLM course material, which is theirs
  rather than ours. Every Corpus belongs to somebody and lives in Postgres
  (SPEC-0006), so a clean clone has no missing Corpus — there is no shipped
  Corpus to miss. `data/README.md` says what belongs there and how to produce
  it.

## Setting it up

Python 3.12 or newer, Docker, and about two minutes.

```bash
git clone https://github.com/Priyanshu2425/interview-lm-backend.git
cd interview-lm-backend

python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt   # runtime, pinned + pytest
.venv/bin/pip install -e backend                        # the package itself

docker run -d --name cortex-pg \
  -e POSTGRES_USER=cortex -e POSTGRES_PASSWORD=cortex -e POSTGRES_DB=cortex \
  -p 55432:5432 pgvector/pgvector:pg16
```

`requirements.txt` is the runtime set the image installs, pinned to the
versions the suite passes against; `requirements-dev.txt` is that plus pytest.
Install the latter — `pip install -e backend` alone declares only what the
Notebook Adapter cannot work without, and leaves you without an API to import
or a runner to import it with.

The container is local scratch. Drop it and re-create it whenever: the suite
builds every schema it needs, and there are no migrations to replay —
`create_core` and `create_content` apply their DDL idempotently on every boot.

Then:

```bash
.venv/bin/python -m pytest backend/tests -q            # 840 tests, ~100s
.venv/bin/uvicorn interviewer.api.app:app --port 8000  # the API
```

**No configuration is required for any of that.** With nothing set, the
database is the container above, and the model provider is a deterministic
stand-in — so the whole interview loop runs offline, with real metering, and
every examiner turn comes back as `SCORE: 0.8 WHY: fine.` That is the stub, not
a bug. `cp .env.example .env` when you want to change it; the file documents
every variable and what it costs you to set.

Nothing loads `.env` on its own. It reaches a process through
`uvicorn --env-file .env` or an explicit `set -a; . ./.env; set +a`, and that
is deliberate — see **the trap**, below.

### Running the surface too

```bash
git clone https://github.com/Priyanshu2425/interview-lm-frontend.git frontend
cd frontend && npm install && ./../scripts/dev-auth-setup.sh && npm run dev
```

`dev-auth-setup.sh` is idempotent and is needed once per machine. Sign-in is
Gatehouse's (ADR-0026) and its refresh cookie is `Secure` — served from plain
`localhost`, sign-in appears to work and the session is gone by the next
reload, with nothing logged anywhere. `frontend/README.md` explains what the
script sets up and why.

### The trap

Setting `DATABASE_URL` — or uncommenting the line in `.env` and sourcing it —
redirects **every local run that reads it** at the shared Neon database. This
is not hypothetical: a neighbouring app's suite did exactly this, creating
schemas and inserting rows on the shared instance before anyone noticed.

The test suite is pinned to local Postgres in `backend/tests/conftest.py` and
cannot be redirected by it. `uvicorn --env-file` and everything in `scripts/`
can, and will. To check where you are pointed:

```bash
.venv/bin/python -c "import sys;sys.path.insert(0,'backend/src');\
import sqlalchemy as sa;from interviewer.db.engine import dsn;\
print(sa.engine.make_url(dsn()).host)"
```

`127.0.0.1` is local. Anything ending `.aws.neon.tech` is shared.
`backend/README.md` has the rest of it, including the three schemas and why
they have opposite lifecycles (ADR-0010).

## Deploying

`render.yaml` is the blueprint and its comments are the reference — every
variable there says why it exists and what breaks without it. The shape:

- **API** — the Docker image, one worker, on Render. The checkpointer and the
  connection pool are per-process, and a free tier has neither the memory nor
  the traffic to want more.
- **Database** — Neon, declared nowhere in `render.yaml` on purpose. It holds
  Evidence, Evidence outlives any one deployment (ADR-0003), and a database
  declared in the same file as its service is a database that can be destroyed
  by editing that file. The registry is at `~/Desktop/buildspace/neon`.
- **Surface** — Cloudflare Pages, cross-origin, which is what `ALLOWED_ORIGINS`
  is for (ADR-0020).
- **Documents** — Cloudflare R2. Render's filesystem is ephemeral and the
  stored document is the only copy of what a Candidate handed over
  (ISSUE-0033).

Health is `/v1/health/live` — liveness, not readiness, deliberately.
`/v1/health` reads a row, and a check on a timer that reads a row holds Neon's
compute awake for a database nobody is using. Whether the database is reachable
is still asked hourly, by the keepalive Worker in the gatehouse repository.

## Where truth lives

`AGENTS.md` is the routing table and is worth reading before changing
anything. In short:

| Question | File |
|---|---|
| What the product refuses to say | `PRODUCT.md` |
| What a word means | `CONTEXT.md` — authoritative on vocabulary |
| What the surface looks like, and why | `DESIGN.md` |
| Why a thing is built the way it is | `docs/adr/` |
| What a screen is for | `docs/prd/`, `docs/issues/` |
| How the backend is laid out | `backend/README.md` |
| How the surface is laid out | `frontend/README.md` |

Most of the guarantees above are constraints and static checks rather than
conventions: one Visit yields one Evidence row by unique index, Evidence is
append-only because no UPDATE reaches it, a Session cannot advance past an
unresolved Visit because of a partial unique index, and the build fails if
anything outside `metering/` imports an HTTP client. `backend/README.md` lists
them. `docs/STORY-COVERAGE.md` maps all 191 user stories to a module and a
test, and `test_story_coverage.py` verifies that map on every run — so the
claim fails loudly if a PRD gains a story nothing implements.
