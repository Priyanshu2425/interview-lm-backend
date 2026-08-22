# ISSUE-0033 — The document outlives its upload

Status: resolved
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

- [x] Uploaded bytes are stored before the Source row is written
- [x] The object key is the content hash, so the same document twice is stored once
- [x] Deleting a Corpus deletes its objects in the same call path
- [x] Re-ingest re-extracts from the stored object rather than from a text column
- [x] A Source whose object is missing reports a named failure rather than a bare error
- [x] Media type and byte length are recorded on the Source
- [x] The existing figure path is untouched and still passes

## Blocked by

- None — can start immediately

## What arrived is what is kept

The rule is deliberately not "PDFs are kept". A note pasted into a box is a
document too, and if only uploads were stored then `text` would still be the
only copy for half the Sources and the guarantee would be half a guarantee. So
the payload is stored whatever shape it arrived in, and `re_extract` reads the
same place for every Source.

## Two absences, one exception

`SourceBytesMissing` carries which: a Source ingested before this slice never
had an object, and a Source whose object has gone missing had one. Both mean
"cannot re-extract", and neither is a bare error from inside a bucket client.

## Storage is an addition, not a precondition

A deployment with no object store keeps no document, records a null key, and
ingests exactly as it did before. An upload must not start failing because a
bucket was not configured.

## Not in this slice

Sweeping unreferenced objects. Deleting one Source leaves its bytes behind, and
that is the *bill* half of the ordering rather than the *broken product* half —
a list a sweep can compute, rather than a citation pointing at nothing.
