# ISSUE-0050 — Spoken reaches the record, and the clock starts when the interview does

Status: resolved
Type: AFK
Source: ISSUE-0049
Covers: the API and the schema learning that an answer can be spoken, and the
Session deadline no longer running while the Candidate waits to begin

Blocked by: — · Blocks: 0052, 0053, 0054

> First, because AGENTS.md refuses controls that reach nothing. A microphone
> that sets a flag no endpoint accepts is exactly that. No UI lands here.

## What to build

### 1. An Answer Turn records whether it was spoken

`POST /v1/sessions/{session_id}/turns` takes one new field:

```
{ "answer": "...", "spoken": true }
```

Absent means typed, which is what every client before voice meant.

Grading is done on the text, and the text is now a machine's reading of a voice.
A low Mastery on a Topic answered aloud and one answered by typing are not the
same evidence, and an audit that cannot tell them apart cannot find a
transcription problem. It is **recorded and reported; nothing weights on it** —
putting it into `w` would conflate trust-in-Grading-Mode with mode-of-input.

`spoken` is true even when the Candidate edited the transcript before sending.
It is still a machine's reading of a voice, which is the question the field
exists to answer.

The column goes on `interview_lm_core.message`, not on `topic_visit`: a Visit can
hold several Answer Turns, some spoken and some typed after a microphone failed.
`message` is append-only, enforced by `trg_message_append_only`, so `spoken` is
written at insert and never corrected. Nothing backfills, because every existing
row is a typed answer — `false` is the fact, not a guess.

Files, in the order the value travels:

- `db/schema.py` — `Column("spoken", Boolean, nullable=False, server_default=sa.false())` on `message`. `Boolean` is not currently imported there.
- `db/engine.py` — one entry in `_CORE_ADDED_COLUMNS` (line 179). There is no Alembic; that tuple is the migration.
- `model/transcript_models.py` — `Turn` gains `spoken: bool = False`, trailing.
- `service/graph/machine_service.py` — `answer_turn` (~293) reads it off the interrupt payload into the exchange dict; `record_exchange` (~325) carries it into `Turn(...)`. An interviewer turn never sets it. The node's docstring already says *"which is why voice or a code editor changes who calls resume rather than changing the loop"* — extend that sentence rather than rewriting it, because this is it coming true.
- `service/graph/transcript.py` — `spoken=t.spoken` in the insert.
- `service/graph/runner_service.py` — `submit(self, session_id, answer, spoken=False)`. **Keyword with a default is mandatory**: there are ~50 positional `r.submit(sid, "…")` call sites in the tests.
- `routes/v1/sessions_router.py` — `TurnIn.spoken: bool = False`, passed through.
- `repository/async_core/sessions.py` (~182) — `transcript()` reports it.

### 2. The clock starts when the Candidate begins

Today `runner_service.py:55` stamps `started_at = clock.now()` at Session create,
and `machine_service.py:372` ends the Session on
`clock.now() - started_at >= duration_seconds`. So the seconds a Candidate spends
getting set up come out of their examination — and ISSUE-0053 is about to make
that wait longer and more visible.

Add **`POST /v1/sessions/{session_id}/begin`**. It stamps a new nullable
`core.session.clock_started_at` if unset, and returns it. Idempotent: a second
call returns the first stamp. The graph reads `started_at` from that column,
falling back to `clock.now()` while it is null — so before Begin, elapsed is
approximately zero and the deadline cannot bite.

- `db/schema.py` + `db/engine.py` — the column and its migration entry.
- `runner_service.start()` (:55) and `_continue_from_boundary()` (:165) seed `started_at` from the row.
- `sessions_router.py` — the route, plus `clock_started_at` on `GET /sessions/{id}` and on the `/sessions` listing, so the surface's timer survives a refresh.

Two things to state in the code rather than leave to be discovered:

- A Session abandoned before Begin has a null `clock_started_at` and never runs
  down. It was never sat.
- `_continue_from_boundary` re-stamps on every resume, so a parked Session gets
  its full duration back. That is pre-existing and defensible — Credits running
  out is not the Candidate's fault. This slice does not change it; say so.

### 3. The CSP stops refusing to run this

`middleware/security_headers.py:66` sets `default-src 'self'` on every response.
Under it `WebAssembly.compile` is refused outright, and the model blobs (which
redirect to `cdn-lfs*.hf.co`) never load. The surface half of this is ISSUE-0052,
but the header is served from here, so it lands here:

```
default-src 'self'; script-src 'self' 'wasm-unsafe-eval';
connect-src 'self' https://huggingface.co https://*.hf.co
```

`'wasm-unsafe-eval'` and nothing broader. The ONNX runtime binary is self-hosted
from `/ort/` (ISSUE-0052) rather than widening `script-src` to a CDN.

**No COOP/COEP.** Without them `SharedArrayBuffer` is undefined and the runtime
falls back to single-threaded wasm — slower, and it works. With them the Google
Fonts stylesheet stops loading and `window.opener` is severed, which breaks the
Gatehouse sign-in popup.

### 4. The surface's types follow

Frontend, no UI: `TranscriptMessage.spoken`, `sessionService.submitTurn(…, spoken = false)`,
and `useExamination.submit(answer, spoken = false)`. The defaults keep
`Composer.tsx` and every existing test untouched.

## Acceptance criteria

- [ ] A turn submitted with `spoken: true` is reported as spoken by `GET /v1/sessions/{id}/transcript`
- [ ] A turn submitted with no `spoken` key still works and reports `false`
- [ ] An interviewer's question is never spoken
- [ ] The append-only trigger still refuses an `UPDATE` of `spoken` — no correction path exists, and that is tested rather than asserted in a comment
- [ ] A database created before this slice gains the columns on boot, without Alembic
- [ ] `POST /v1/sessions/{id}/begin` stamps once and is idempotent
- [ ] A Session that is created and never begun does not run down, however long it sits
- [ ] A Session begun after a long wait gets its full duration
- [ ] `GET /sessions/{id}` and the `/sessions` listing report `clock_started_at`
- [ ] The CSP permits `'wasm-unsafe-eval'` and does not permit bare `'unsafe-eval'`, and that is tested
- [ ] `spoken` reaches no scoring path — grep proves it touches the record and nothing else
- [ ] `npm run verify` and `pytest -q` green
