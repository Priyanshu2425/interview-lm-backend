# ISSUE-0037 — Retire the disk path

Status: resolved
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

- [x] Related Topics is a query over stored centroids, with no artifact involved
- [x] The artifact, its fingerprint, its staleness reading and its build script are gone
- [x] `get_base_corpus` and `compose` are gone, and nothing imports them
- [x] A dossier is loaded whole by `topic_id`, from rows, and the loader's contract is unchanged
- [x] Nothing embeds at question time, verified the way `test_the_route_embeds_nothing` already does
- [x] The full suite passes on a clean clone with no `data/` directory at all
- [x] The image builds and boots with no Corpus in the context
- [x] ADR-0005 is amended, naming the clause that changed and the ones that did not
- [x] ADR-0018 is marked superseded, with the reason its artifact stopped being needed

## Blocked by

- ISSUE-0034 — the import must work before the shipped Corpus is removed
- ISSUE-0036 — Related Topics must answer from rows before the artifact is deleted

## Measured on a clean clone

    604 passed, 155 skipped

No failures. The 17 that used to fail were tests reaching the shipped Corpus
through the API's dependency graph rather than through the skipping fixture;
there is no such path any more.

## Three things had to travel that the plan did not name

Removing the disk path meant that anything the shipped Corpus carried and a
notebook did not would be silently lost on the way into Postgres. Three were:

**Tracks.** The picker filters on `track_key`, and the Scaler material has two
Tracks. `notebook_source` carries a Track now; empty means the notebook's own,
which is what every existing Source was.

**Provenance.** PRD-0001 §13 asks which extract a Session ran against, and "the
notebook adapter" is not an answer — the import is a transport, not a source. A
Library keeps the provenance it was imported with.

**Module ids.** Session scope is keyed on `module_id`, so ISSUE-0034 already had
the import keep the source's own. Without it, every existing Session's scope
would have named a Module that no longer existed.

## `compose` did not survive, and did not need to

`compose(base, *notebooks)` was base-first by construction. The merge it did is
still needed — several Libraries in one picker — so it moved into
`notebooks/corpus_view.merge`, where the Corpora come from. What is gone is the
idea that one of them is a base the others are composed onto.

## What replaced the staleness machinery

Nothing, and that is the point. ISSUE-0029 made a stale index harmless and
ISSUE-0030 made it legible; both existed because a file derived from another
file can disagree with it. A centroid written in the same transaction as its
Topic cannot. ADR-0021 records the reasoning, and carries forward the three
findings that were about the *space* rather than the file — mean-centring, the
floor, and ties breaking by id.

One rule is stricter than the artifact's: a neighbour never crosses a Corpus,
because `embedding_model` is per Corpus and a cosine between two spaces is a
number with no meaning.

## What this cost

The suite went from about 40 seconds to about 70. Serving material through the
API now means importing it, and `served_corpus` pays an embed and eight hundred
inserts — once per session, into a template schema, and copied per test. That
copy is the thing to look at if it starts dominating again.
