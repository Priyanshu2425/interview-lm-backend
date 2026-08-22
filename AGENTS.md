# AGENTS.md

Cortex Interviewer. A Python graph (`backend/`) examines a Candidate on a
Corpus; a React surface (`frontend/`) renders what it decides.

## Where truth lives

| Question | File |
|---|---|
| What the product refuses to say | `PRODUCT.md` |
| What a word means | `CONTEXT.md` — authoritative on vocabulary |
| What the surface looks like, and why | `DESIGN.md` |
| Why a thing is built the way it is | `docs/adr/` |
| What the Corpus is *about*, topic by topic | `data/corpus-index.json` — derived, rebuildable, never hand-edited |
| What a screen is for | `docs/prd/`, `docs/issues/` |
| How the surface is laid out | `frontend/README.md` |

The design files the surface was built from live outside the repo at
`~/Documents/cortex-interviewer`. They ship markup only — their stylesheets
were never in the folder, and `DESIGN.md` records what was reconstructed from
the markup and what was derived. `design-system/` in this repo is the retired
predecessor; nothing is built from it.

## The refusals

Every one of these is a number that would be easy and natural to produce, which
is why each is enforced as an **absent API** — a call that does not exist, so it
cannot be made by accident. When you add a convenience, check that you have not
re-opened one.

- **Coverage and Mastery are two readings, never one figure.** No function
  returns a combined percentage and no screen renders one.
- **Untested is not zero.** Below the Evidence Floor a Topic reads *Untested*
  and shows no number. `Reading` renders the word even when a mastery figure is
  passed in beside an untested band, and that is under test.
- **A Credit is one US cent of provider cost.** Off the Credits route every
  figure is an em dash — a zero reads as "it was free" rather than "this ledger
  does not apply to you".
- **Difficulty is not a property of the Corpus.** Cortex records none and none
  is derived. No screen calls a question easy or hard.
- **A Session's cost is not knowable in advance.** It is metered per graded call
  and reported after each Topic.
- **Say Coverage.** Cortex owns the word *Progress* and means "classes opened";
  where its own number is meant, say *Cortex Progress*.

## The surface holds no invariant

Bands, Mastery, Coverage and Grading Modes arrive already decided by the server
(ADR-0009); the client draws them. A second implementation of the Evidence Floor
drifts from the first, so `bandClass` maps rather than inspects and `BetaCurve`
cannot render without a band.

Two consequences worth stating outright:

- **Ship controls that reach something.** The design files draw an Evidence
  Floor slider and a "request a hint" button. `POST /sessions` accepts neither
  field, and the graph owns the hint move. State the rule in force instead.
- **Render failure copy from the API's own `code` and `message`.** Composing it
  on the client is how a Credit message reaches a BYOK Candidate.

## Conventions the config does not carry

- `INTERVIEWER_FAKE_MODEL=1` runs the whole loop against a scripted provider:
  deterministic, no network, real metering. Every examiner turn comes back as
  `SCORE: 0.8 WHY: fine.` — that is the stub, not a bug.
- `EMBEDDING_PROVIDER` picks what turns a notebook into vectors: `hashing` (the
  default — a lexical stand-in with no dependencies, and what the suite runs on),
  `siglip`, or `http`. An unknown name fails at boot rather than falling back,
  for the same reason the model flag above is explicit. The real model needs
  `pip install -e "backend[embeddings]"`, and `INTERVIEWER_MODEL_TESTS=1` runs
  the handful of tests that load it.
- Postgres must carry pgvector — the README's container is
  `pgvector/pgvector:pg16`. Embeddings are a `vector(768)` column, and the width
  is a deployment-wide constant: a mismatch between the model and the column
  refuses to start rather than writing a second geometry into one column.
  There is no alembic, so `create_content` applies the DDL on every boot,
  idempotently, the way `create_core` applies its triggers.
- Related Topics come from `data/corpus-index.json`, built offline by
  `scripts/embed_corpus.py` and read at runtime — a deployment needs no model to
  serve them, only to rebuild them. Re-scraping the Corpus makes the index
  stale, and a stale index serves **no** neighbours rather than wrong ones
  (ADR-0018). Rebuild with `--force` after changing how the index is built, not
  only after changing the Corpus.
- A figure is a chunk with `modality='image'` and its bytes in an object store
  (ADR-0017). Anything rebuilding prose — a dossier, a Leaf, a token budget —
  must filter to text, and `store.chunks_of` takes the argument for it.
- Environment: `backend/.env.example` is the full set, and every one has a
  working default. Nothing calls `load_dotenv`, so a `.env` is read only via
  `uvicorn --env-file`. The surface reads none — the API is same-origin, so
  there is no build-time URL to configure.
- The API mounts `frontend/dist` at `/`, so a surface change is invisible until
  `npm run build`. `SURFACE_DIR` points the mount elsewhere.
- A feature is reached through its `index.ts`; ESLint enforces it.
- Evidence outlives the material. Deleting a notebook retires its Topics and
  keeps every row they produced. `CASCADE` empties the schema and has never
  heard of the bucket, so deleting figure bytes is an explicit step in the same
  call path.
- A timeout is a **park**, not an error: recovery reads the Session and resumes,
  the same path an interruption uses.
- One idempotency key per composed answer, advanced only when a turn lands — a
  retry after a dropped connection must converge on the same Answer Turn.

## Verifying

`frontend/package.json` carries the scripts. Two things it cannot tell you:

- `npm run verify` needs nothing running. `test:e2e` and `audit` drive a real
  browser against a real API on port 8000.
- `npm run audit` measures rather than asserts — real contrast against real
  backdrops, targets on both pointer types, accessible names, across five
  variations and every route. Treat a finding as a defect, not a threshold.

Backend: `.venv/bin/python -m pytest backend/tests -q` (660 tests, plus eight
skipped until `INTERVIEWER_MODEL_TESTS=1` loads real weights — those eight
include the quality floor for Related Topics, which is the only check that
would notice the embedding space collapsing).
