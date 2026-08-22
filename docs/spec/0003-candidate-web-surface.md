# SPEC-0003 — Candidate web surface

Implements: the Text Surface of PRD-0003, composing readings from PRD-0002 and PRD-0005
Governed by: ADR-0011 (turn transport), ADR-0009 (the surface holds no invariant)
Design source: `design-system/` — screens 01–08, `design-system/DESIGN.md`, `PRODUCT.md`
Stack: see §1a — deviates from SPEC-0000's Astro, deliberately

The prototype in `design-system/` is the specification of appearance and behaviour.
This document says what becomes real, what state exists, and which call backs
each screen. Where the two disagree, the prototype wins on look and wording and
this document wins on data.

---

## 1a. Stack, and a deviation from SPEC-0000

SPEC-0000 names Astro + TypeScript. The surface is being built instead as
**vanilla ES modules served as static files by the FastAPI app**, and that is a
deviation worth recording rather than discovering later.

**Why.** Every screen here reads from `/v1` and renders; only five islands hold
state at all (SPEC-0003 §3). A build step, a second toolchain and a second
deployable buy nothing at that size, and ADR-0009's whole argument for letting
the surface be a separate language was that it *holds no invariant* — which
cuts both ways: it also means it needs no framework to be correct. Serving it
from the same origin as the API removes the CORS and cookie decision SPEC-0000
§7 left open, at least until auth lands.

**What would reverse it.** Server-side rendering for first paint, routing that
outgrows a handful of pages, or a component count where hand-rolled state stops
being cheaper than a framework. None of those are true yet. The token layer and
the API client are framework-agnostic, so this is a contained change.

**What does not change.** The component inventory, the island boundaries, the
screen-to-API map and the turn loop in §5 are all stack-independent, and the
rules in §1 hold regardless.

## 1. The surface holds no invariant

ADR-0009 makes this the reason the surface may be a different language: it
supplies an **Answer Turn** and renders what it is given. Three consequences,
and every one of them is a thing a frontend would otherwise do by habit:

- **It never computes a score, a band, or a posterior.** `Coverage`, `Mastery`,
  the **Evidence Floor** band and the credible interval arrive from the API
  already decided. The prototype's `readTopic()` is a *drawing* function in
  production: it receives `(alpha, beta, band, label)` and renders a curve.
- **It never decides what to ask next.** Topic selection is Thompson sampling
  inside the graph (PRD-0002).
- **It never holds an Answer Key.** There is no client route that can request one.

## 2. Component inventory

Extracted from `design-system/assets/app.css`, which becomes the token layer.

**Primitives** — `Button` (primary/quiet/ghost/on-ink/future, 6 states),
`Chip`, `Tag`, `Panel` (light/ink), `Notice` (info/warn/danger/ok/future),
`Field`, `Option` (single/multi), `Segmented`, `Table` + `ScrollAffordance`,
`Sheet`/`Overlay`, `SyntheticMarker`.

**Domain components** — these carry product rules and are the reason the
inventory is not just a UI kit:

| Component | Rule it enforces |
|---|---|
| `PosteriorRidge` | Draws `(α, β)`. Renders **no number** when `band === 'untested'` |
| `BandToken` | Word first, colour second. Never colour alone |
| `ReadingPair` | Takes Coverage and Mastery as two props. **Has no combined output** |
| `ProvenanceChip` | Grader, provider, rubric version. Non-optional prop |
| `CostChip` | Renders `—` when `route !== 'credits'`, never `0` |
| `GradingModeChip` | Ground-Truth / Text-grounded / Model judgment |
| `TurnThread` | Opening question, probes, hints — resolving to one score |
| `Composer` | Emits the Answer Turn. The only component that can |

`ReadingPair` having no combined output is the pattern to copy: the product
rules are expressed as *absent APIs*, not as review comments.

## 3. Islands

Astro, server-rendered by default. Interactive islands only where state lives:

| Island | Screen | Why it must be client-side |
|---|---|---|
| `SessionSetup` | 01 | Scope selection drives the readout and gates Start |
| `Exchange` | 02 | The turn loop, SSE text, park handling |
| `PosteriorRidge` | 03, 04 | Canvas/SVG draw, and the one authored animation |
| `SpendSheet` | 02, 05 | Pull-up sheet, focus containment |
| `KeyAttach` | 05 | Live validation round-trip |

Everything else — the summary table, the ledger, the whole operator console —
is static HTML from server data. This is what keeps the mobile examination
screen as light as it looks.

## 4. Screen → API map

| Screen | Reads | Writes |
|---|---|---|
| 01 Session setup | `GET /v1/corpus/modules`, `GET /v1/candidates/me/credits` | `POST /v1/sessions` |
| 02 Topic Visit | `GET /v1/sessions/{id}`, `GET .../stream` | `POST .../turns`, `POST .../end` |
| 03 Topic scored | response of the closing turn | — |
| 04 Session summary | `GET /v1/sessions/{id}/summary`, `GET /v1/candidates/me/confidence` | — |
| 05 Credits & keys | `GET /v1/candidates/me/credits` | `POST/DELETE .../byok` |
| 08 Operator | operator endpoints, separate auth | — |

Screens 06 and 07 are **future surfaces** and have no endpoints. They stay in
`design-system/` and are not built.

`GET /v1/corpus/modules` returns real Topic and Answer Key counts per Module —
the prototype hard-codes 5/7/7/5/11 and 4/5/5/3/0, which are correct today and
must come from the Corpus so they stay correct.

## 5. The turn loop

The only complicated thing on the surface, and it follows ADR-0011 exactly.

```
submit → POST /turns  {answer, idempotency_key}   [long-running]
              │
              ├─ 200 {kind:"follow_up"|"hint"}  → append to thread, reopen composer
              ├─ 200 {kind:"visit_closed"}      → score, provenance, cost, ridge (03)
              ├─ 200 {kind:"session_ended"}     → summary (04)
              ├─ 409 {code:"CREDITS_EXHAUSTED_MID_VISIT"} → notice, Visit completed
              ├─ 4xx {code:"BYOK_KEY_*"}        → provider named, Credits never mentioned
              └─ timeout / network              → GET /v1/sessions/{id}, resume from state
```

**The idempotency key is generated once per composed answer and reused on every
retry.** A user mashing submit, a flaky network, and a browser refresh all
converge on one Answer Turn. This is the surface's single most important
behaviour, because the thing on the other side is a permanent write.

**The composer is disabled while a turn is in flight** and shows the request is
running. It is never disabled by a timer.

**Timeout is a park, not an error.** The recovery path is the same one an
interrupted Session already uses (PRD-0003), so the surface has one code path
for "we lost the thread" rather than two.

## 6. What the design already settled

Carried from `design-system/DESIGN.md` — do not relitigate at build time:

- Ink is the examination; light is everything else. Crossing between them is the
  system's one authored transition (cross-document view transitions).
- Violet marks designed-but-unbuilt surfaces and appears nowhere in shipped UI.
- Mobile is the exchange and nothing else; secondary readings live in a sheet.
- Both rails share the exchange's ground.
- Semantic colour is darker than Scaler's brand palette so the Evidence Floor
  bands clear 4.5:1. The brand values are kept at full brightness on ink.
- Dense tables keep their columns on small screens and gain a scroll affordance.
- Two authored motions only: the crossing, and the posterior deforming from its
  prior. Everything else is 160–220ms state feedback.

## 7. Content that must not be faked

Every number in `design-system/` is labelled synthetic and must be replaced by real
data, with one exception: the Module names, Topic names and the attention
Assignment/Answer Key are real Corpus content and can stay as fixtures.

The `SyntheticMarker` component ships to production and is used in exactly one
place — the empty state for a Candidate with no Sessions yet, where the example
readings shown are illustrative. Anywhere else it appears is a bug.

## 8. Open decisions

1. **Whether 03 is a route or a state of 02.** The prototype makes it a separate
   screen, which the view transition handles well. As a route it needs the
   closing turn's response persisted somewhere re-fetchable.
2. **Offline/flaky behaviour beyond the turn.** The turn is safe by idempotency;
   whether a composed-but-unsent answer survives a refresh is undecided.
3. **The operator console's auth.** Separate from Candidate auth (ADR-0012
   covers Candidates only).
