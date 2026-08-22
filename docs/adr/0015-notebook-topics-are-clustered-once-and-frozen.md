# Notebook Topics are clustered once and frozen; chunks are the citation unit

ADR-0007 gives the Adapter the job of dividing a Source into **Topics**, and
forbids the backbone from inferring load units at runtime. The **Notebook
Adapter** honours that division of labour and then does something ADR-0007 did
not anticipate: it divides by clustering embedded chunks, because its Source
arrives with no divisions at all.

Two rules make that safe.

**Cluster once, then freeze.** The first ingest of a source clusters its chunks
and mints `topic_id`s, which are persisted with the cluster centroid and the set
of chunk hashes that formed it. Later ingests never re-cluster. New chunks attach
to a frozen centroid above a similarity floor; material that matches nothing
mints a new Topic and writes a **Corpus Version** event.

**Order comes from position.** A clusterer produces no ordering, and the contract
requires one. Module order is upload index, Topic order is the offset of the
earliest chunk in the cluster, chunk order is locator order. All three are
deterministic and all three put introductory material first, which is what the
Session opener — exempt from Thompson sampling — needs to stand on.

## Why clustering, when hashing was cheaper

A structural Adapter that split on headings and matched re-ingests by content
hash would have been simpler, free to run, and perfectly reproducible.

It cannot answer the question the product will be asked next: *where in my
sources does this come from?* Citation is a span-level attribution problem. It
needs chunks, embeddings and locators regardless of how Topics are drawn — so
once that layer exists, deriving Topics from it costs one clustering pass rather
than a second parallel representation of the same material.

Heading structure is also a claim about the author's layout, not about concepts,
and it is absent exactly where notebooks are weakest: PDFs and pasted pages.

## Why Module equals source

Clustering runs inside a single source. Adding a source therefore adds a Module
and cannot move a boundary in any existing one. The only case requiring centroid
matching is a re-upload of a source already ingested.

Thematic Modules spanning several sources were rejected: their membership shifts
whenever a source is added, which is the drift this ADR exists to prevent.

## Relationship to ADR-0005

ADR-0005 refuses a vector store *in the interview loop*, and its closing clause
permits one alongside. This is that case. Topic selection is still Thompson
sampling over ids, a dossier is still loaded whole by `topic_id`, and no
follow-up is ever answered out of a top-k result. The index serves attribution
and ingest-time clustering only.

## Consequence

Mastery on a notebook Topic means what it meant last month, or the record says
plainly that the Topic changed. That is the whole point: the Adapter may guess at
structure, but it may not revise its guess in silence.
