# Issues — tracer-bullet slices

Each issue is a thin vertical slice cutting through every layer — Corpus, graph,
Judge, store, API, surface, tests — rather than a horizontal slice of one layer.
A completed slice is demoable on its own.

`AFK` slices can be implemented and merged without human interaction. `HITL`
slices need a human decision or review, and say why in their body.

| # | Slice | Type | Blocked by |
|---|---|---|---|
| 0001 | Corpus ingest and the Module picker | AFK | — |
| 0002 | Walking skeleton: one graded Topic Visit | AFK | 0001 |
| 0003 | The Judge: blind, versioned, mode-recorded | AFK | 0002 |
| 0004 | Confidence math and the Evidence Floor | AFK | 0003 |
| 0005 | Session config and Topic selection | AFK | 0004 |
| 0006 | The agentic region: probe, hint, close | **HITL** | 0005 |
| 0007 | Resumption and replay determinism | AFK | 0006 |
| 0008 | Metered Model Client and the real provider | AFK | 0007 |
| 0009 | Credits: ledger, headroom gate and refunds | AFK | 0008 |
| 0010 | BYOK: key vault and failure classifier | **HITL** | 0009 |
| 0011 | Auth and Candidate identity | **HITL** | 0002 |
| 0012 | MCP Mode server | AFK | 0007 |
| 0013 | Operator console | AFK | 0009 |

### Frontend — `frontend/`, built from `design-system/`

| # | Slice | Type | Blocked by | State |
|---|---|---|---|---|
| 0014 | Surface shell and the Session setup screen | AFK | — | ✅ resolved |
| 0015 | The live exchange | AFK | 0014 | ✅ resolved |
| 0016 | Topic scored, and the posterior it moved | AFK | 0015 | ✅ resolved |
| 0017 | Session summary and the Candidate's record | AFK | 0016 | ✅ resolved |
| 0018 | Credits and BYOK on the surface | AFK | 0014 | ✅ resolved |
| 0019 | Operator console on the surface | AFK | 0014 | ✅ resolved |
| 0020 | Surface fidelity and accessibility pass | **HITL** | 0017–0019 | machine half done |

### Notebook Adapter — a Corpus the Candidate brought

Sources: SPEC `2026-08-21-notebook-adapter-design`, ADR-0015, ADR-0005 (amended).

| # | Slice | Type | Blocked by | State |
|---|---|---|---|---|
| 0021 | Notebook ingest: one source becomes a conformant Corpus | AFK | — | ✅ resolved |
| 0022 | Freeze and re-ingest: ids survive, drift is logged | AFK | 0021 | ✅ resolved |
| 0023 | PDF and URL sources, and the stub Module | AFK | 0021 | ✅ resolved |
| 0024 | Ground Truth mined from the notebook | AFK | 0021 | ✅ resolved |
| 0025 | Citation: the span that grounded the question | **HITL** | 0021 | machine half done |
| 0026 | The embedding provider, and the BYOK gap | **HITL** | 0021 | machine half done |
| 0027 | Notebook lifecycle: upload, delete, retire | AFK | 0025 | ✅ resolved |
| 0028 | Image-only sources become Modules | **HITL** | 0026 | open |

### Related Topics — the shipped Corpus, embedded

Sources: ADR-0005 (§"When this should be revisited", amended twice), ADR-0017,
FUTURE-PIPELINE §Cross-Topic similarity.

| # | Slice | Type | Blocked by | State |
|---|---|---|---|---|
| 0029 | The shipped Corpus, embedded, and Related Topics served | AFK | — | ✅ resolved |
| 0030 | A stale Corpus index is visible, not silent | AFK | 0029 | ✅ resolved |
| 0031 | Related Topics on the surface | **HITL** | 0030 | open |

### A Corpus is assembled, not shipped

Source: SPEC-0006. Turns the Corpus from a build artifact into something a
Candidate assembles: documents in, chunked and embedded into Postgres, added to
over time.

| # | Slice | Type | Blocked by | State |
|---|---|---|---|---|
| 0032 | A Corpus has an owner, and a shared one cannot be deleted | AFK | — | ✅ resolved |
| 0033 | The document outlives its upload | AFK | — | ✅ resolved |
| 0034 | A structured import keeps the Topics it arrived with | AFK | 0032 | open |
| 0035 | Ingest runs behind a progress bar, and dies cleanly | AFK | 0033 | open |
| 0036 | Where you stand on a Topic | **HITL** | 0034 | open |
| 0037 | Retire the disk path | AFK | 0034, 0036 | open |

## Shape of the graph

The spine is `0001 → 0002 → 0003 → 0004 → 0005 → 0006 → 0007`, and it is a spine
on purpose: the deterministic skeleton exists before the agentic region grows, so
the seam between them stays visible.

After 0007 the work fans out. `0008 → 0009 → 0010` is the metering chain,
`0012` is MCP Mode, and `0011` branches off 0002 — none of the three touch each
other, so they can run in parallel.

`0013` waits on 0009 because every reading it shows is derived from those ledgers.

The frontend has its own spine, `0014 → 0015 → 0016 → 0017`, following the
Candidate through one Session: choose scope, be examined, see the score, read the
record. `0018` and `0019` branch off the shell and touch neither the exchange nor
each other, so all three can run in parallel. `0020` is the only frontend slice
that needs a human, and it waits for the screens to exist.

The frontend slices depend on backend routes that are **already built and
tested**, so `0014` can start immediately — it is blocked by nothing.

## Three repositories

`backend/` holds the Python implementation. `frontend/` is **its own git
repository**, holding the surface built from `design-system/` and talking to the
backend over HTTP only — which is what ADR-0009 means by the surface holding no
invariant. The prototype in `design-system/` stays as the design's source of truth
and is not deleted when the surface lands — it is what `0020` compares against.

## Not in this set

Screens 06 (code editor) and 07 (voice) in `design-system/` are **future surfaces**.
SPEC-0003 gives them no endpoints, and they are deliberately absent here so
nobody builds them by momentum. The code editor would arrive as an additive
fourth Grading Mode rather than a rewrite; voice needs the Answer Turn boundary
problem solved first.

Payment processing is out of scope throughout. PRD-0005's boundary is a
*payment cleared* event in, a grant out.

## Shape of the notebook set

`0021` is a spine of one. It has to be: extract, chunk, embed, cluster, freeze and
dossier build divide into horizontal layers that demo nothing, so they land
together or not at all. Everything after it fans out.

`0022`, `0023`, `0024`, `0025` and `0026` each depend on `0021` and on nothing
else, and touch none of each other's ground — re-ingest, source types, Ground
Truth, citation and metering are five independent extensions of one pipeline.

`0027` waits on `0025` alone, because the snapshots it must keep alive after a
deletion are the citation columns `0025` writes.

`0028` arrived with ADR-0017: once figures and prose share one embedding space,
a source that extracts no text stops being necessarily a stub. It is HITL
because what an examiner *asks* about a Topic made of pictures, and which
Grading Mode that Topic could honestly claim, are product questions rather than
implementation ones.

Two are HITL for the same reason the existing HITL slices are: `0025` would have
to invent a screen `design-system/` never drew, and `0026` runs into ADR-0008
accepting OpenRouter keys only — a BYOK Candidate whose key cannot embed is a
product decision, not an implementation detail.

## Shape of the Related Topics set

`0029` is thick for the same reason `0021` was, and the reason is worth stating
rather than assuming: chunk, embed, pool and edge-build divide into horizontal
layers that demo nothing on their own. A slice that ends at "there is now a file
on disk" cannot be judged.

The ordering is a safety property rather than a preference. `0029` makes a stale
index **harmless** — no neighbours rather than wrong ones — and `0030` makes it
**legible**. That way round, never the other: a thing that can silently lie must
not ship first and be fixed second. `0031` waits on `0030` because a surface
that can render a stale reading before staleness is detectable is a surface that
renders a wrong one.

`0029` reverses a recorded decision. FUTURE-PIPELINE says of cross-Topic
similarity, in as many words, "Do not pre-build it." That instruction was right
when there was no consumer; ADR-0018 records what changed and why, because a
reversal nobody wrote down is indistinguishable from a rule nobody read.

What none of the three touch: Topic selection is still Thompson sampling over
ids, a dossier is still loaded whole by `topic_id`, and no query is embedded at
question time by anything. Related Topics is centroid against centroid, computed
once, offline — so ADR-0005's "there is no query to embed" stays literally true
of the running system rather than approximately true.

`0031` is HITL twice over. It would have to invent a screen `design-system/`
never drew, which is the trap `0025` stopped in front of; and underneath that
sits a product question — a list of related Topics next to a score reads as
"study these next", which is Topic recommendation, which does not exist and is
deferred for want of calibration data. Related Topics is a claim about the
material, not about the Candidate.

## Shape of the SPEC-0006 set

`0032` and `0033` start immediately and touch none of each other's ground —
ownership is a schema question, source storage is an object-store question.
Everything else waits on one of them.

The ordering is a safety property twice over. `0032` comes first because the
delete guard is what stops a Candidate retiring Topic ids that other
Candidates' Evidence is keyed on, and that guard should exist before there is
anything shared to delete. `0037` comes last because the disk path is the
working system until the database path has been proven by the five slices in
front of it — removing it earlier would mean debugging the replacement with no
fallback.

`0036` is HITL for the reason `0025` and `0031` are: the reading is mechanical,
the placement is not. A rank shown beside a score reads as "study these next",
which is Topic recommendation — deferred for want of calibration data, and a
claim about a person the measurement cannot support.

`0037` is where the repository becomes honest. It is the slice after which a
clean clone has no missing Corpus, because there is no shipped Corpus to miss.

Both HITL slices are built up to their decision and no further. `0025` records
citations on Evidence, resolves them to spans with locators, and serves them in
the Session summary; where a citation *appears in the exchange* is undrawn and
unbuilt. `0026` meters, gates, charges and resumes ingest through an embedder
port; which provider fills that port, and who pays for a BYOK Candidate's
notebook, is ADR-0016 — written, recommended, unsigned.

