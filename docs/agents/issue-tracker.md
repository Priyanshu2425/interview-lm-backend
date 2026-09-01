# Issue tracker: `docs/issues/`

Issues for this repo live as markdown files in `docs/issues/`, committed alongside
the code they describe. The GitHub repository has an Issues tab and a handful of
issues on it; it is **not** the tracker. Where the two disagree, the file wins.

An issue here is a **tracer-bullet slice** — a thin vertical cut through every
layer (Corpus, graph, Judge, store, API, surface, tests) rather than a horizontal
slice of one layer. A completed slice is demoable on its own. `docs/issues/README.md`
says this in its own words and is the authority on it.

## Conventions

- One file per issue: `docs/issues/NNNN-<slug>.md`, four digits, sequential across
  the whole repo — not per set. The next number is one past the highest file present.
- The body opens with a `# ISSUE-NNNN — Title` heading, then a short header block of
  `Key: value` lines, then `## What to build`. The header block carries at least:
  - `Status:` — `open` or `resolved` (see `triage-labels.md` for the role vocabulary)
  - `Type:` — `AFK` or `**HITL**`
  - `Source:` — the SPEC, ADR or set the slice comes from
  - `Covers:` — one line on what the slice is for
- `AFK` slices can be implemented and merged without human interaction. `**HITL**`
  slices need a human decision or review, **and say why in their body**. That
  sentence is load-bearing: an HITL slice with no stated reason is not triaged.
- Issues are grouped into **sets** (Interview Mode, SPEC-0006, Notebook Adapter, …).
  Each set has a table in `docs/issues/README.md` — `| # | Slice | Type | Blocked by | State |`
  — and a prose `## Shape of the … set` section explaining the ordering. Dependencies
  live in the table's `Blocked by` column, not in the issue files.
- Titles are sentences in the project's own voice ("The document outlives its
  upload", "A scope suggests a time"), using the vocabulary `CONTEXT.md` defines.

## When a skill says "publish to the issue tracker"

Write `docs/issues/NNNN-<slug>.md` with the header block above, **and** add a row to
the right set's table in `docs/issues/README.md`. A file with no row is invisible;
neither half is optional. If the work opens a new set, add the table and write the
`## Shape of the … set` paragraph — the ordering rationale is the point of it.

## When a skill says "fetch the relevant ticket"

Read `docs/issues/NNNN-<slug>.md`. The user will normally pass the number. Read the
set's table and shape section too — what a slice is blocked by, and why it sits
where it does, are recorded there rather than in the file.

## Neighbouring records

Issues are the smallest of five kinds of record and cite the others by id:

| Record | Lives in | Is |
|---|---|---|
| PRD | `docs/prd/NNNN-<slug>.md` | what a product area is for |
| SPEC | `docs/spec/NNNN-<slug>.md` | a change argued in full, before slicing |
| ISSUE | `docs/issues/NNNN-<slug>.md` | one slice of a SPEC, buildable |
| ADR | `docs/adr/NNNN-<slug>.md` | why a thing is built the way it is |
| QA pass | `docs/qa/<date>-<slug>.md` | what a review found, and what was justified |

A slice that reverses a recorded decision amends or writes an ADR — a reversal
nobody wrote down is indistinguishable from a rule nobody read.

## PRs as a request surface

**Off.** Pull requests are not part of the triage queue.

## Wayfinding operations

Used by `/wayfinder`. Wayfinding efforts are **exploration**, not the durable record,
so they stay out of `docs/issues/` and live under `.scratch/` (untracked). A finding
that survives the exploration graduates into an ISSUE, SPEC or ADR by the rules above.

- **Map**: `.scratch/<effort>/map.md` — the Notes / Decisions-so-far / Fog body.
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`, with
  the question in the body. A `Type:` line records the ticket type
  (`research`/`prototype`/`grilling`/`task`); a `Status:` line records
  `claimed`/`resolved`.
- **Blocking**: a `Blocked by: NN, NN` line near the top. A ticket is unblocked when
  every file it lists is `resolved`.
- **Frontier**: scan `.scratch/<effort>/issues/` for files that are open, unblocked
  and unclaimed; first by number wins.
- **Claim**: set `Status: claimed` and save before any work.
- **Resolve**: append the answer under an `## Answer` heading, set `Status: resolved`,
  then append a context pointer (gist + link) to the map's Decisions-so-far in `map.md`.
