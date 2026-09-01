# `adapters/` holds foreign systems; the Adapter is still a Corpus Source

Two different things were called an adapter, and one directory held both.

**The word keeps its meaning.** An **Adapter** is what turns a **Corpus Source**
into a Corpus satisfying the backbone's contract (ADR-0007, CONTEXT.md). That
term is load-bearing in three ADRs and is not being renamed.

**The directory changes hands.** `adapters/` now holds code that talks to a
system we do not own — Gatehouse, OpenRouter, the object store. Nothing else.
The Adapters of ADR-0007 live in `service/corpus/sources/`, beside the contract
they satisfy.

## Why

The directory was answering a question nobody asks. `adapters/` held the
notebook ingest pipeline — extract, chunk, embed, cluster, label, freeze —
which is the deepest domain logic in the repository and has no system on the
other side of it. Meanwhile the three integrations that *do* reach off the box
were somewhere else entirely: OpenRouter under `service/metering/`, S3 under
`service/embeddings/`, and only Gatehouse in `adapters/` (misspelled).

So the one question a directory of adapters should answer at a glance — *what
does this system depend on that it does not control?* — could not be answered
from it, and the answer it did give was wrong in both directions.

Hexagonal architecture uses "adapter" for anything satisfying a port, which
makes both readings defensible and is how the two ended up together. We are
choosing the narrower rule for the **directory** because it is the one that
answers a question we ask often, and keeping the broader word in the **domain
language** because ADR-0007 built the corpus-agnostic backbone on it.

## Consequence

`adapters/internal/` was never an integration. It moves to
`service/corpus/sources/notebook/`, where being next to `interview_lm.py` and
`markdown_folder.py` makes the thing that is actually true of all three
visible: they are three implementations of one contract, and `conformance.py`
is the contract they are checked against.

Embedders stop being split. `HashingEmbedder` sat in `adapters/internal/` while
`SiglipEmbedder` sat in `service/embeddings/`, so the registry imported back out
of `adapters/` to build the default. They satisfy one port and now live in one
place.

The domain glossary is unchanged. A reader who meets "the InterviewLM Adapter"
in an ADR and then looks for `adapters/interview_lm.py` will not find it, so
CONTEXT.md's **Adapter** entry says where they live instead.

## Considered and rejected

**Rename the domain term** to Corpus Source or Importer, freeing "adapter" for
the directory. Consistent, and rejected on cost of the wrong kind: it edits a
decision rather than a description. ADR-0007 is a statement about what the
backbone refuses to guess, and its argument does not improve by being restated
in a new word.

**Leave it, on hexagonal's reading** — an adapter is anything at a port, so
`adapters/internal/` was already correct and only OpenRouter and the object
store were misplaced. This is a real position and it loses on the same ground
the choice was made: `adapters/` then means "anything with a port", which is
most of the system, and the directory answers nothing.
