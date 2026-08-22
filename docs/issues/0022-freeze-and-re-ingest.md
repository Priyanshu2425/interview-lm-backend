# ISSUE-0022 — Freeze and re-ingest: ids survive, drift is logged

Status: resolved
Type: AFK
Source: SPEC 2026-08-21 Notebook Adapter; ADR-0015, ADR-0007; PRD-0001
Covers: ADR-0015 "cluster once, then freeze"; spec §Failure modes (dedupe, changed source)

## What to build

The promise ISSUE-0021 made and did not test: **a notebook Topic means next month
what it means today, or the record says otherwise.**

Re-ingesting a source **never re-clusters**. Its new chunks are matched against
the frozen centroids of that source's Topics. A chunk above the similarity floor
joins the Topic that owns that centroid and the `topic_id` is untouched. Chunks
that match nothing form a new Topic, mint a new id, and write a **Corpus
Version** event naming the source, the Topics that survived, and the Topic that
appeared.

The Corpus Version event lives in the **permanent** schema, not the content
schema. It outlives the notebook whose change it describes — that is its whole
purpose.

Uploading a byte-identical source is not a change. Content hashes match, the
existing Module is returned, and nothing is re-embedded or re-billed.

Centroids are stored data. A Topic's centroid is not recomputed when chunks join
it, because a centroid that drifts with every upload is a boundary that moves
without saying so.

`embedding_model` is recorded on the notebook. A change of model re-embeds chunks
and re-derives centroids in the new space, and **Topic membership is carried
across unchanged** — membership is stored, never recomputed. That re-derivation
is itself a Corpus Version event.

## Acceptance criteria

- [ ] Re-ingesting a byte-identical source returns the existing Module, mints no ids, and makes no embedding call
- [ ] Appending a paragraph to a source mints no new Topic and changes no existing `topic_id`
- [ ] Replacing half a source mints a new Topic **and** writes exactly one Corpus Version event
- [ ] Deleting material from a source retires no Topic and rewrites no id; the shrunk dossier is recorded as a Corpus Version event
- [ ] A Corpus Version event names the source, the surviving Topic ids and the new Topic ids
- [ ] Corpus Version events are written to the permanent schema and survive deletion of the notebook
- [ ] No code path re-runs the clusterer against an already-frozen source, enforced by test
- [ ] Topic Confidence accumulated before a re-ingest still reads against the same `topic_id` afterwards
- [ ] Changing `embedding_model` re-embeds, re-derives centroids, preserves every Topic membership, and logs one Corpus Version event
- [ ] The similarity floor is a named constant with a stated rationale, not a literal buried in the matcher

## Blocked by

- ISSUE-0021 — there is nothing to re-ingest until a first ingest freezes ids
