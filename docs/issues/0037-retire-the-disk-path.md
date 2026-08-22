# ISSUE-0037 — Retire the disk path

Status: open
Type: AFK
Source: SPEC-0006 §What retires; ADR-0005; ADR-0018
Covers: removing the shipped Corpus once its replacement is proven

## What to build

Nothing here is removed until the five slices in front of it have proven the
database path. That ordering is the whole reason this is sixth: the disk path is
the working system until it is not.

What goes:

- **`get_base_corpus()` and `compose()`.** There is no base to compose onto once
  every Corpus belongs to somebody.
- **`data/corpus-index.json`, entirely**, with its fingerprint, its staleness
  rules and its build script. This is a simplification rather than a deletion:
  ADR-0018 built a precomputed artifact because the Corpus was a file, and once
  chunk vectors are rows, neighbours are a `<=>` query over the Candidate's own
  Topic centroids. The reason for the artifact is gone, so the artifact goes.
- **`CORPUS_PATH` as a mount.** It becomes an import source instead.

ADR-0005 keeps its central claim and loses one clause. No query is embedded at
question time, Topic selection is still Thompson sampling over ids, and a
dossier is still loaded whole by `topic_id` — it is simply loaded from rows.
Amend it rather than superseding it, and say which sentence changed.

The 17 tests that currently fail on a clean clone are expected to pass at the
end of this slice, because there is no longer a shipped Corpus for them to miss.

## Acceptance criteria

- [ ] Related Topics is a query over stored centroids, with no artifact involved
- [ ] The artifact, its fingerprint, its staleness reading and its build script are gone
- [ ] `get_base_corpus` and `compose` are gone, and nothing imports them
- [ ] A dossier is loaded whole by `topic_id`, from rows, and the loader's contract is unchanged
- [ ] Nothing embeds at question time, verified the way `test_the_route_embeds_nothing` already does
- [ ] The full suite passes on a clean clone with no `data/` directory at all
- [ ] The image builds and boots with no Corpus in the context
- [ ] ADR-0005 is amended, naming the clause that changed and the ones that did not
- [ ] ADR-0018 is marked superseded, with the reason its artifact stopped being needed

## Blocked by

- ISSUE-0034 — the import must work before the shipped Corpus is removed
- ISSUE-0036 — Related Topics must answer from rows before the artifact is deleted
