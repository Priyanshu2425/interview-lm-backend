# Domain Docs

How the engineering skills should consume this repo's domain documentation when
exploring the codebase.

This repo is **single-context**: one `CONTEXT.md` and one `docs/adr/` at the root,
covering both halves (`backend/`, `frontend/`). There is no `CONTEXT-MAP.md` and no
per-package glossary.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — the glossary, and **authoritative on
  vocabulary**.
- **`docs/adr/`** — read the ADRs that touch the area you're about to work in.
  There are 26 of them and they are short; the filename says what each decides
  (`0002-the-judge-is-blind-to-the-conversation.md`).
- **`AGENTS.md`** at the root — the "Where truth lives" table points at everything
  else, and **The refusals** section lists what the product will not do. Those are
  enforced as absent APIs. Adding a convenience that re-opens one is a defect even
  when every test passes.
- **`PRODUCT.md`** for what the product refuses to say, **`DESIGN.md`** for what the
  surface looks like and why.

If any of these files don't exist, **proceed silently**. Don't flag their absence;
don't suggest creating them upfront. The `/domain-modeling` skill (reached via
`/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when
terms or decisions actually get resolved.

## File structure

```
/
├── AGENTS.md                          ← where truth lives, and the refusals
├── CONTEXT.md                         ← the glossary
├── PRODUCT.md
├── DESIGN.md
├── docs/
│   ├── adr/0001-….md … 0026-….md      ← why a thing is built the way it is
│   ├── spec/                          ← a change argued in full
│   ├── prd/                           ← what a product area is for
│   ├── issues/                        ← the tracker (see issue-tracker.md)
│   └── qa/                            ← what a review found
├── backend/                           ← the Python graph
└── frontend/                          ← the React surface
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a
hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to
synonyms the glossary explicitly avoids.

This repo is unusually strict about it, and the strictness is the design: *Corpus*
not "context", *Coverage* not "progress", *Candidate* not "user", *Untested* rather
than a zero. `CONTEXT.md` and the refusals in `AGENTS.md` say which word loses and
why. Getting the word wrong here is not a style nit — several of the refusals exist
precisely because the wrong word invites the wrong number.

If the concept you need isn't in the glossary yet, that's a signal — either you're
inventing language the project doesn't use (reconsider) or there's a real gap (note
it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than
silently overriding:

> _Contradicts ADR-0007 (the Interviewer is Corpus-agnostic behind a strict adapter
> contract) — but worth reopening because…_

An ADR here may be amended by later work rather than replaced; ADR-0005 has been
amended twice and says so in its own body. A reversal that nobody writes down is
indistinguishable from a rule that nobody read, so the amendment is part of the
change, not follow-up.
