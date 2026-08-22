# ISSUE-0033 — The document outlives its upload

Status: open
Type: AFK
Source: SPEC-0006 §Where the documents live; ADR-0017 §object store
Covers: source bytes in S3, and what that makes possible

## What to build

A PDF is currently read once and discarded. `notebook_source.text` keeps what
extraction produced and the original bytes are kept nowhere — so a re-ingest
cannot re-extract, a better extractor cannot be applied to old material, and a
citation cannot show the page it came from.

Uploaded bytes go to the object store `artifacts.py` already provides: the same
one holding figures, content-addressed, under the owner's prefix, deleted with
the Corpus in the same call path. Extraction, chunks, embeddings and dossiers
stay in Postgres.

**Stored before the row is written**, so a `source` row never points at an object
that is not there — the same ordering ADR-0017 already fixed for figures. Rows
without objects are citations pointing at nothing; objects without rows are
unreferenced bytes a sweep can find. One is a broken product, the other is a bill.

Content addressing means the same document uploaded twice is stored once, and it
is what lets a re-upload after a failed ingest cost nothing extra.

## Acceptance criteria

- [ ] Uploaded bytes are stored before the Source row is written
- [ ] The object key is the content hash, so the same document twice is stored once
- [ ] Deleting a Corpus deletes its objects in the same call path
- [ ] Re-ingest re-extracts from the stored object rather than from a text column
- [ ] A Source whose object is missing reports a named failure rather than a bare error
- [ ] Media type and byte length are recorded on the Source
- [ ] The existing figure path is untouched and still passes

## Blocked by

- None — can start immediately
