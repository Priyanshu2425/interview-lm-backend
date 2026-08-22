# ISSUE-0030 — A stale Corpus index is visible, not silent

Status: open
Type: AFK
Source: ADR-0005 §"Embeddings are a liability against a re-scraped Corpus";
ADR-0015 §Amendment; ISSUE-0029
Covers: the third objection ADR-0005 raised, answered rather than dismissed

## What to build

ADR-0005 gave three reasons to refuse a vector store. Two of them ISSUE-0029
sidesteps outright: there is still no query to embed, and the dossier still
loads whole. The third it only makes safe:

> **Embeddings are a liability against a re-scraped Corpus.** Every re-run of
> `scripts/scrape.mjs` would require re-embedding to stay consistent.

ISSUE-0029 makes a stale index harmless — the neighbours simply stop appearing.
This slice makes it **legible**, so that "the Related Topics went away" is a
sentence somebody can act on rather than a mystery.

ADR-0015 answered the same objection for notebooks by recording
`embedding_model` and re-embedding on a change. This is that answer applied to
material nobody owns: the index states what it was built from, the system states
whether that still matches, and rebuilding is one command.

Three things land:

**The index says what it was built from.** Corpus fingerprint, embedding model
identity, when it was built, how many Topics it covers. Readable without running
anything.

**The system says whether that is still true, and how it differs.** Not a
boolean. A re-scrape that changed two Topics and a model swap are different
problems with different fixes, and "stale" alone tells an operator neither. The
operator console reads this alongside the other readings it already shows, and a
stale index reads as a state rather than an error — the Corpus is still fully
examinable without it.

**Rebuilding is one documented command**, and re-running it against an unchanged
Corpus is a no-op that says so rather than a several-minute job that looks like
work.

The scrape script gains a closing line naming the rebuild as the next step,
because the moment the index goes stale is the moment somebody is standing in
front of a terminal having just re-scraped.

## Acceptance criteria

- [ ] The artifact records corpus fingerprint, embedding model identity, build time and Topic count
- [ ] A reading is available that reports fresh or stale and, when stale, whether the Corpus changed, the model changed, or both
- [ ] A changed Corpus is detected by content rather than by timestamp — touching a file changes nothing, editing one does
- [ ] The operator console shows index freshness beside its existing readings
- [ ] A stale index reads as a state, never as a failure: no route 500s, no Session is affected, the Corpus stays examinable
- [ ] The rebuild command is documented where an operator will find it, and is a no-op with a clear message on an unchanged Corpus
- [ ] `scripts/scrape.mjs` names the rebuild as the next step when it finishes
- [ ] Deleting the artifact and rebuilding it reproduces it byte-for-byte
- [ ] A stale index still serves no neighbours, and a test proves the two behaviours agree — visibility must not accidentally re-enable serving

## Blocked by

- ISSUE-0029 — it writes the fingerprint this slice reads
