# AGENTS.md

InterviewLM. A Python graph (`backend/`) examines a Candidate on a
Corpus; a React surface (`frontend/`) renders what it decides.

## Where truth lives

| Question | File |
|---|---|
| What the product refuses to say | `PRODUCT.md` |
| What a word means | `CONTEXT.md` — authoritative on vocabulary |
| What the surface looks like, and why | `DESIGN.md` |
| Why a thing is built the way it is | `docs/adr/` |
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
- **Difficulty is not a property of the Corpus.** InterviewLM records none and none
  is derived. No screen calls a question easy or hard.
- **A Session's cost is not knowable in advance.** It is metered per graded call
  and reported after each Topic.
- **Say Coverage.** InterviewLM owns the word *Progress* and means "classes opened";
  where its own number is meant, say *InterviewLM Progress*.
- **Pictures alone are not examinable.** A Source that extracts no text stays a
  stub; no Topic is minted from figures and no caption model turns them into
  prose (ADR-0024). A figure may *support* a question grounded in text — that is
  what ADR-0017's shared space is for — and may not *be* what a question is
  grounded in.
- **A Candidate is compared inside a Topic, never ranked.** A rank needs one
  figure per person, and the only figures available are Coverage and Mastery —
  so a leaderboard is the fused percentage under another name. Comparison is a
  percentile within one Topic, over Candidates the Evidence Floor admits, above
  a Cohort Floor (SPEC-0006). No function returns a Candidate's position.

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
- **There is no Corpus on disk.** Every Corpus belongs to somebody and lives in
  `content` (SPEC-0006, ISSUE-0037): a shared one an operator imported, or a
  Candidate's own uploads. `CORPUS_PATH` is where `scripts/import_corpus.py`
  reads from and is not read by the API; a clean clone has no missing Corpus
  because there is no shipped Corpus to miss.
- Related Topics is the stored Topic centroids of **one** Corpus compared
  against each other, mean-centred (the centring is the whole quality of it —
  `related.centre` carries the measurement). No artifact, no fingerprint, no
  staleness: the vectors were written with the Topics they describe (ADR-0021).
  A neighbour never crosses a Corpus, because `embedding_model` is per Corpus
  and a cosine across two spaces means nothing.
- A figure is a chunk with `modality='image'` and its bytes in an object store
  (ADR-0017). Anything rebuilding prose — a dossier, a Leaf, a token budget —
  must filter to text, and `store.chunks_of` takes the argument for it.
- Environment: `backend/.env.example` is the full set, and every one has a
  working default. Nothing calls `load_dotenv`, so a `.env` is read only via
  `uvicorn --env-file`. The surface reads none — the API is same-origin, so
  there is no build-time URL to configure.
- The API mounts `frontend/dist` at `/`, so a surface change is invisible until
  `npm run build`. `SURFACE_DIR` points the mount elsewhere.
- Same-origin is the default and `ALLOWED_ORIGINS` is what reverses it
  (ADR-0020). Set it and the surface must be **built** with a matching
  `VITE_API_URL`: the two deploys have to agree, and when they do not the first
  request fails in the browser with a CORS message that names neither usefully.
- `Dockerfile` builds both halves and pins the runtime from
  `backend/requirements.txt`; regenerate it with `scripts/pin_requirements.py`
  after changing a dependency. The `embeddings` extra is deliberately not in the
  image, and no Corpus is copied into it — material arrives by import.
- Structure is given or derived, and the Source says which (ISSUE-0034). Derived
  is the existing path — a Candidate's file arrives with no divisions and the
  clusterer mints them. Given is a structured import: Topic ids, order, titles,
  leaf kinds and the Module id come from the source, and
  `adapters/notebook/structured.py` imports no clusterer at all so a later edit
  cannot quietly reach one. `scripts/import_corpus.py` is how the shipped
  Corpus gets in, one Source per Module, resumable.
- A feature is reached through its `index.ts`; ESLint enforces it.
- Evidence outlives the material. Deleting a notebook retires its Topics and
  keeps every row they produced. `CASCADE` empties the schema and has never
  heard of the bucket, so deleting the bytes — figures **and** the uploaded
  documents themselves — is an explicit step in the same call path.
- The document outlives its upload (ISSUE-0033), which makes the object store
  part of the runtime rather than an extra: `boto3` is in
  `backend/requirements.txt`, and a deployment on an ephemeral filesystem that
  sets no `CONTENT_BUCKET` keeps documents only until its next restart. A bucket
  that is configured and unreachable **refuses the upload**
  (`document_store_unavailable`) rather than half-keeping it somewhere the row
  cannot point at. Bytes go under `…/sources/<sha256>`, content-addressed and
  written **before** the Source row, so a row never points at an object that is
  not there.
  `notebook_source.text` is what one extractor made of them and is a cache;
  `re_extract` re-reads the document itself. A Source with no `object_key`
  predates the column and says so rather than pointing at bytes nobody kept.
- The object store is Cloudflare R2 and nothing about it is AWS. boto3 is the
  client because R2 serves the S3 API and SigV4 is the only way in, and that is
  the whole of the connection: `_client` reads `R2_ENDPOINT_URL`,
  `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` and passes them explicitly, so a
  host with AWS keys in its environment does not quietly become the store.
  There is no region variable — R2 signs everything `auto`, so `R2_REGION` is a
  constant rather than a setting with one legal value. A bucket configured with
  no endpoint is refused rather than resolved to AWS. Uploads ask for a checksum
  only `when_required`: boto3 1.36 began adding a CRC32 trailer by default,
  which is `aws-chunked` on the wire and the one place a store serving the S3
  API is least likely to agree with S3. Every object here is keyed by the sha256
  of its own bytes, so integrity is claimed where it is checked.
  `scripts/publish_model.py` builds no client of its own for the same reason.
- The upload outlives the ingestion (ISSUE-0035). `POST /notebooks/{id}/sources`
  stores the bytes, writes the row and returns; the embedding runs in a thread
  and the surface polls `GET /notebooks/{id}`. States are `uploaded → ingesting
  → ready`, with `failed` beside them and `stub` unchanged, and only `ready` is
  selectable. `ready` implies *composed*: an ingest rebuilds the served Corpus
  **before** marking the Source ready, or a Session started the moment the
  progress bar fills is refused. No worker survives a restart, so rows left
  `ingesting` are reset to `failed` at boot rather than timed out.
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
  variations and every route, at 320, 390, 768 and 1440. Treat a finding as a
  defect, not a threshold.
- `npm run a11y` reads the accessibility tree over CDP: what a screen reader
  would announce, rather than what the markup looks like. `npm run fidelity`
  diffs each prototype screen's inventory against its built counterpart at three
  widths and prints what the design says that the build does not — every entry
  is fixed or justified in `docs/qa/2026-08-22-issue-0020-pass.md`. Both need a
  real API on port 8000, or `BASE` pointing at one.

Backend: `.venv/bin/python -m pytest backend/tests -q` (751 tests in about 70
seconds, plus eight skipped until `INTERVIEWER_MODEL_TESTS=1` loads real weights
— those eight include the quality floor for Related Topics, which is the only
check that would notice the embedding space collapsing).

Roughly half the runtime is one fixture. `served_corpus` gives a test an API
serving imported material, which after ISSUE-0037 means an embed and eight
hundred inserts; it is done once per session and copied out of a template schema
per test. If it starts dominating again, that copy is the thing to look at.
