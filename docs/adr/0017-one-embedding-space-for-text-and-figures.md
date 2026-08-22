# One embedding space for text and figures

ISSUE-0026 asked for a real embedder behind the port ISSUE-0021 defined. The
model chosen is **`google/siglip2-base-patch16-224`**: 768 dimensions,
Apache-2.0, and a dual encoder — a text tower and an image tower trained against
each other, so a paragraph and the diagram it describes land near each other in
one space.

Four decisions follow from that, and each of them could reasonably have gone the
other way.

## Window pooling, because the text tower holds 64 tokens

SigLIP 2 was trained on captions. Its text tower accepts 64 tokens; a chunk is
500–800. Handing a chunk over whole would keep its first tenth and discard the
rest — and every number derived from it afterwards, the cluster it joins, the
Topic it becomes, the span a citation points at, would be computed from that
tenth. Plausibly, and without any error.

Two ways out were rejected. Truncation is the silent failure above. Shrinking
chunks to fit would break ISSUE-0021's 500–800-token contract, multiply chunk
counts by roughly twelve, and make a Topic mean something different.

So a chunk is tokenised, cut into consecutive ≤64-token windows, every window is
embedded, and the windows are mean-pooled and re-normalised. The whole chunk
reaches the model; `chunk_id`, locators and dossier bytes are untouched. It costs
about twelve forward passes per chunk instead of one, which is affordable because
the tower is small and ingest happens once.

`test_window_pooling.py` holds this open with a stubbed tower: two chunks
identical in their first 64 tokens and different after **must** produce different
vectors. If pooling is ever simplified back into `truncation=True`, that test is
what fails.

**The caveat, on the record.** A caption-trained tower is not a retrieval
encoder. Expect it to beat the lexical stub clearly and to sit below a dedicated
retrieval model on prose clustering. `EMBEDDING_PROVIDER=http` and `re_embed()`
are what make that reversible, and they exist before the problem does.

## A Protocol for the port, an abstract class for the providers

`Embedder` stays a structural Protocol in `corpus/adapters/notebook/`. It has to:
two things satisfy it without being providers — `HashingEmbedder`, which must
keep zero dependencies so the test suite never loads a model, and
`ReusingEmbedder`, which wraps an embedder and could not inherit from one
without inheriting its weights too.

`BaseEmbedder` is the other half, in `embeddings/`, and it is where the
machinery lives: batching that preserves input order, retries that distinguish
this moment from this request, deadlines, width and non-finite validation,
unconditional L2 normalisation, usage accounting, warm-up and a lock. A new
provider writes `_encode_texts` and inherits the rest.

The division is the point. Without the ABC every provider re-implements nine
things and gets one of them subtly wrong. Without the Protocol the stub and the
decorator would have to inherit from a class that loads models.

## A figure is a chunk with a modality, not a second table

Because both towers share one 768-dimensional space, a figure and a paragraph
are directly comparable — so the citation lookup should be one query over one
HNSW index rather than two indexes unioned. `notebook_chunk` therefore gains
`modality` (`text | image`) and `object_key`, and a figure is a row in it.

Two consequences have to be enforced rather than remembered:

- **Dossier build filters `modality = 'text'`.** ISSUE-0021 requires dossier text
  be byte-identical to its source spans concatenated. An image row carries no
  characters, so one joining that concatenation corrupts it silently.
  `test_dossier_excludes_images.py` is the guard.
- **The payload invariant is the database's.** `CHECK ((modality = 'image') =
  (object_key IS NOT NULL))`, so no code path can write a figure with nowhere to
  fetch its bytes, or prose that claims to have some.

**Prose stays in Postgres; only pixels leave.** The split is by size and by what
`CASCADE` can honestly promise. Text is already in the table the dossier reads
and gains nothing from a round trip to a bucket. Images are large, are served to
a browser, and are worth the one real cost of moving them: `CASCADE` empties the
schema and has never heard of the bucket, so `delete_notebook` deletes the
`notebooks/{id}/` prefix in the same call path. Rows go first and objects after —
rows without objects are citations pointing at nothing, objects without rows are
unreferenced bytes a sweep can find. One is a broken product; the other is a bill.

## A figure never redraws a Topic

ADR-0015 froze Topic boundaries and made them text's business. The shared space
makes attaching figures *by similarity* possible, and that is exactly the
temptation this clause refuses: similarity moves when the model moves, and a
Topic boundary that drifts with the embedder is the drift ADR-0015 exists to
prevent.

Attachment is positional. A figure joins the Topic of the text chunk at its
position on its own page; failing that, the earliest chunk on the nearest page,
ties resolving backwards because a figure is introduced by the text before it far
more often than the text after it. A Source with no prose at all attaches
nothing. A figure never mints a `topic_id` and never enters a centroid
calculation.

## Relationship to ADR-0005 and ADR-0016

ADR-0005's amendment already permits an ingest-time and citation-time index; the
image lane is more of that same case, and no query is embedded at question time.

ADR-0016 stays unsigned and stays unblocked. The model runs locally and bills
nothing, so no Candidate — pool or BYOK — is charged for ingest and no Credit
message can reach a BYOK Candidate. A provider that *would* bill is refused at
boot unless `EMBEDDING_ALLOW_PAID=1`, and the refusal names the ADR. The decision
becomes real the moment somebody wants a commercial model, which is the moment
somebody will read it.

## Consequence

The width is a deployment-wide constant. `EMBEDDING_DIM` must match
`content.notebook_chunk.embedding`, and a mismatch refuses to start rather than
writing a second geometry into one column: fixable while visible, close to
undiagnosable once written. Changing model is `re_embed()`, which carries every
Topic membership across as stored data — the boundaries do not move because the
embedder did.
