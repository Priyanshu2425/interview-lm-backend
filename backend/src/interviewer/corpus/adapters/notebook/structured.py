"""Importing material that arrived with its own divisions.

The Notebook Adapter *mints* `topic_id`s by clustering, because a Candidate's
file arrives with no divisions at all. Authored material arrives with its own —
the Scaler course has 71 Topics — and running the clusterer over it would
produce a different 71 and mean something different by every one.

So exactly one stage differs, and it is the stage in the middle:

    extract -> chunk -> embed -> [cluster | given] -> freeze -> dossier -> validate

This module is the right-hand branch. It imports no clusterer and no id-minter,
which is a stronger statement than not calling them: there is no import here
that could be reached by a later edit, and the test that proves it counts calls
rather than reading the code.

**Nothing is derived.** Topic ids, titles, order and leaf kinds come from the
source. What the pipeline still does is chunk and embed, because a dossier is
assembled from chunks and a centroid is what a re-ingest matches against —
neither is a claim about structure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from ...conformance import validate
from ...contract import (
    Corpus, CorpusProvenance, Leaf, LeafKind, Module, Topic, Track,
)
from .adapter import ADAPTER_NAME, ADAPTER_VERSION, FrozenTopic, Ingested, IngestReport
from .chunking import Chunk, chunk_source, leaf_title
from .embedding import Embedder, HashingEmbedder

_LEAF_KINDS = {
    "content": LeafKind.CONTENT,
    "prompt": LeafKind.PROMPT,
    "ground_truth": LeafKind.GROUND_TRUTH,
}


@dataclass(frozen=True, slots=True)
class GivenLeaf:
    """One authored passage, as its source already describes it.

    `kind` travels because Ground Truth is what decides a Module's Grading Mode
    ceiling. An import that dropped it would silently downgrade every imported
    Module to model judgment, and nothing would report the loss.
    """

    leaf_id: str
    title: str
    text: str
    kind: str = "content"
    answers_leaf_id: str | None = None


@dataclass(frozen=True, slots=True)
class GivenTopic:
    """A Topic the source already drew, with the id Evidence is keyed on."""

    topic_id: str
    title: str
    order: int
    leaves: tuple[GivenLeaf, ...] = field(default_factory=tuple)

    @property
    def text(self) -> str:
        return "\n\n".join(leaf.text for leaf in self.leaves if leaf.text)


def ingest_given(
    *,
    notebook_id: str,
    notebook_title: str,
    source_id: str,
    source_title: str,
    module_id: str,
    module_order: int,
    topics: Sequence[GivenTopic],
    embedder: Embedder | None = None,
    extracted_at: str = "1970-01-01T00:00:00Z",
) -> Ingested:
    """Chunk and embed authored material without re-deriving a single division."""
    embedder = embedder or HashingEmbedder()
    chunks: list[Chunk] = []
    built: list[Topic] = []
    frozen: dict[str, FrozenTopic] = {}

    for topic in sorted(topics, key=lambda t: (t.order, t.topic_id)):
        topic_chunks = _chunks_of(topic, source_id)
        if not topic_chunks:
            # A Topic of pure references has nothing to embed. It is dropped
            # rather than stored empty: a Topic with no leaf is not examinable,
            # and the contract says so.
            continue
        for chunk, vector in zip(
            topic_chunks, embedder.embed([c.text for c in topic_chunks])
        ):
            chunk.embedding = vector
            chunk.topic_id = topic.topic_id
        chunks.extend(topic_chunks)
        built.append(
            Topic(
                id=topic.topic_id,
                order=topic.order,
                title=topic.title,
                leaves=tuple(
                    Leaf(
                        id=chunk.chunk_id,
                        order=i,
                        title=leaf_title(chunk.text),
                        kind=_LEAF_KINDS.get(chunk.leaf_kind, LeafKind.CONTENT),
                        text=chunk.text,
                        source_ref=f"{source_id}#p{chunk.page}",
                        answers_leaf_id=chunk.answers_chunk_id,
                    )
                    for i, chunk in enumerate(topic_chunks, 1)
                ),
            )
        )
        frozen[topic.topic_id] = FrozenTopic(
            topic_id=topic.topic_id,
            module_id=module_id,
            source_id=source_id,
            title=topic.title,
            centroid=_centroid(topic_chunks),
            chunk_hashes=tuple(c.content_hash for c in topic_chunks),
        )

    module = Module(
        id=module_id,
        order=module_order,
        title=source_title,
        description="",
        topics=tuple(built),
    )
    corpus = Corpus(
        provenance=CorpusProvenance(
            source=f"notebook:{notebook_id}",
            extracted_at=extracted_at,
            adapter=ADAPTER_NAME,
            adapter_version=ADAPTER_VERSION,
        ),
        tracks=(
            Track(key=f"nb-{notebook_id}", title=notebook_title, modules=(module,)),
        ),
    )
    report = IngestReport(
        chunks=len(chunks),
        topics=len(built),
        modules=1,
        embedded_chunks=len(chunks),
    )
    report.conformance = validate(corpus)
    report.dossier_tokens = report.conformance.dossier_tokens
    return Ingested(corpus=corpus, chunks=chunks, frozen=frozen, report=report)


def _chunks_of(topic: GivenTopic, source_id: str) -> list[Chunk]:
    """The Topic's prose, cut by the same chunker every other Source uses.

    A leaf is chunked on its own, for two reasons. Its kind travels with its
    spans — chunking the Topic whole would leave a prompt and its worked answer
    in one chunk, which is the boundary ISSUE-0024 exists to keep. And the chunk
    ids come from the leaf's own id, so re-importing the same material produces
    the same ids and therefore the same dossier, byte for byte.

    Offsets are rebased onto a cursor that runs across the whole Topic, because
    everything downstream reads a Topic's chunks in locator order and leaf-local
    offsets would interleave them.
    """
    out: list[Chunk] = []
    first_chunk_of: dict[str, str] = {}
    leaf_of: dict[str, str] = {}
    cursor = 0
    for leaf in topic.leaves:
        if not (leaf.text or "").strip():
            continue
        pieces = [c for c in chunk_source(leaf.leaf_id, leaf.text) if c.text.strip()]
        if pieces:
            first_chunk_of[leaf.leaf_id] = pieces[0].chunk_id
        for piece in pieces:
            piece.char_start += cursor
            piece.char_end += cursor
            # The chunk id stays the leaf's; only the owner changes, because a
            # chunk row belongs to the Source that was uploaded.
            piece.source_id = source_id
            piece.leaf_kind = leaf.kind if leaf.kind in _LEAF_KINDS else "content"
            leaf_of[piece.chunk_id] = leaf.leaf_id
            out.append(piece)
        cursor += len(leaf.text) + 2

    # A leaf that answers another one points at that leaf's first span. A
    # citation names a place to start reading, not every span of the answer.
    by_leaf = {leaf.leaf_id: leaf for leaf in topic.leaves}
    for chunk in out:
        leaf = by_leaf.get(leaf_of.get(chunk.chunk_id, ""))
        if leaf is None or not leaf.answers_leaf_id:
            continue
        chunk.answers_chunk_id = first_chunk_of.get(leaf.answers_leaf_id)
    return out


def _centroid(chunks: Sequence[Chunk]) -> tuple[float, ...]:
    from .embedding import centroid_of

    return centroid_of([c.embedding for c in chunks])
