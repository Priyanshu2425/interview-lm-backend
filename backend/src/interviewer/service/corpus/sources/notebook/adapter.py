"""The Notebook Adapter — a Corpus for material nobody divided.

InterviewLM hands us Modules, Topics, order and answer keys. A Candidate's own PDF
hands us none of them, and something has to manufacture the structure the
contract requires. That something is here, in an Adapter, exactly where ADR-0007
says the mess belongs.

    extract -> chunk -> embed -> cluster -> label -> freeze -> dossier -> validate

One uploaded Source is one Module (ADR-0015), so clustering runs inside a Source
and cannot move a boundary in a Source it is not looking at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from interviewer.service.corpus.conformance import Report, validate
from interviewer.model.corpus_models import (
    Corpus, CorpusProvenance, Leaf, LeafKind, Module, Topic, Track,
)
from .chunking import Chunk, chunk_source, leaf_title
from .clustering import Cluster, cluster_chunks
from interviewer.service.embeddings.hashing import Embedder, HashingEmbedder
from .mining import answered_by, classify
from .documents.extract import Extracted
from .documents.sources import Notebook, Source, digest

ADAPTER_NAME = "notebook"

#: Mining's vocabulary, mapped onto the contract's. The Adapter is the only
#: place that knows a notebook's own words for these things (ADR-0007).
_LEAF_KINDS = {
    "content": LeafKind.CONTENT,
    "prompt": LeafKind.PROMPT,
    "ground_truth": LeafKind.GROUND_TRUTH,
}
ADAPTER_VERSION = "1"

#: Texts in, one Topic title out. Failure is survivable and must be.
Labeller = Callable[[Sequence[str]], str]


@dataclass(frozen=True, slots=True)
class FrozenTopic:
    """What ISSUE-0022 matches a re-ingest against.

    The centroid and the chunk hashes are stored, never recomputed from whatever
    the Source says today — a centroid that drifts with every upload is a Topic
    boundary that moves without saying so.
    """

    topic_id: str
    module_id: str
    source_id: str
    title: str
    centroid: tuple[float, ...]
    chunk_hashes: tuple[str, ...]


@dataclass(slots=True)
class IngestReport:
    """What ingest observed, for a human to read before shipping."""

    chunks: int = 0
    topics: int = 0
    modules: int = 0
    stub_sources: list[str] = field(default_factory=list)
    dossier_tokens: dict[str, int] = field(default_factory=dict)
    labels_fell_back: bool = False
    embedded_chunks: int = 0
    conformance: Report | None = None

    def render(self) -> str:
        lines = [
            f"modules={self.modules} topics={self.topics} chunks={self.chunks}",
            f"dossier tokens={self.dossier_tokens}",
            f"stub sources={self.stub_sources}",
            f"labels fell back={self.labels_fell_back}",
        ]
        if self.conformance:
            lines.append(self.conformance.render())
        return "\n".join(lines)


@dataclass(slots=True)
class Ingested:
    """Everything one ingest produced. The Corpus is what the backbone sees."""

    corpus: Corpus
    chunks: list[Chunk]
    frozen: dict[str, FrozenTopic]
    report: IngestReport


def module_id_for(notebook_id: str, source_id: str) -> str:
    return "nbm_" + digest(notebook_id, source_id)[:16]


def topic_id_for(notebook_id: str, source_id: str, hashes: Sequence[str]) -> str:
    """Derived once, from the membership that formed the Topic.

    Derived rather than random so that re-ingesting an unchanged Source is
    provably the same Corpus; frozen rather than re-derived so that a Source
    which *did* change keeps the ids its Evidence is keyed on (ISSUE-0022).
    """
    return "nbt_" + digest(notebook_id, source_id, *sorted(hashes))[:24]


def ingest_notebook(
    notebook: Notebook,
    *,
    embedder: Embedder | None = None,
    labeller: Labeller | None = None,
    frozen: Mapping[str, FrozenTopic] | None = None,
    extracted_at: str = "1970-01-01T00:00:00Z",
) -> Ingested:
    """Turn a Candidate's sources into a Corpus the backbone can examine."""
    embedder = embedder or HashingEmbedder()
    report = IngestReport()
    chunks: list[Chunk] = []
    modules: list[Module] = []
    frozen_out: dict[str, FrozenTopic] = dict(frozen or {})

    for order, source in enumerate(notebook.sources, 1):
        if source.is_stub:
            report.stub_sources.append(source.source_id)
            continue
        module, source_chunks, topics_frozen, fell_back = _ingest_source(
            notebook, source, order, embedder, labeller, frozen_out
        )
        modules.append(module)
        chunks.extend(source_chunks)
        frozen_out.update(topics_frozen)
        report.labels_fell_back = report.labels_fell_back or fell_back
        report.embedded_chunks += len(source_chunks)

    corpus = Corpus(
        provenance=CorpusProvenance(
            source=f"notebook:{notebook.notebook_id}",
            extracted_at=extracted_at,
            adapter=ADAPTER_NAME,
            adapter_version=ADAPTER_VERSION,
        ),
        tracks=(
            Track(
                key=f"nb-{notebook.notebook_id}",
                title=notebook.title,
                modules=tuple(modules),
            ),
        ),
    )

    report.chunks = len(chunks)
    report.modules = len(corpus.modules)
    report.topics = len(corpus.topics)
    report.conformance = validate(corpus)
    report.dossier_tokens = report.conformance.dossier_tokens
    return Ingested(corpus=corpus, chunks=chunks, frozen=frozen_out, report=report)


def _ingest_source(
    notebook: Notebook,
    source: Source,
    order: int,
    embedder: Embedder,
    labeller: Labeller | None,
    frozen: Mapping[str, FrozenTopic],
) -> tuple[Module, list[Chunk], dict[str, FrozenTopic], bool]:
    chunks = chunk_source(
        source.source_id,
        source.text,
        extracted=Extracted(source.text, source.pages) if source.pages else None,
    )
    for chunk, vector in zip(chunks, embedder.embed([c.text for c in chunks])):
        chunk.embedding = vector

    clusters = cluster_chunks(chunks)
    topics: list[Topic] = []
    frozen_out: dict[str, FrozenTopic] = {}
    fell_back = False

    for topic_order, cluster in enumerate(clusters, 1):
        hashes = tuple(c.content_hash for c in cluster.chunks)
        topic_id = topic_id_for(notebook.notebook_id, source.source_id, hashes)
        title, used_fallback = _title_for(cluster, labeller)
        fell_back = fell_back or used_fallback
        for chunk in cluster.chunks:
            chunk.topic_id = topic_id
        kinds = classify(cluster.chunks)
        answers = answered_by(cluster.chunks, kinds)
        for chunk in cluster.chunks:
            chunk.leaf_kind = kinds.get(chunk.chunk_id, "content")
            chunk.answers_chunk_id = answers.get(chunk.chunk_id)
        topics.append(
            Topic(
                id=topic_id,
                order=topic_order,
                title=title,
                leaves=tuple(
                    Leaf(
                        id=chunk.chunk_id,
                        order=i,
                        title=leaf_title(chunk.text),
                        kind=_LEAF_KINDS[kinds.get(chunk.chunk_id, "content")],
                        text=chunk.text,
                        source_ref=f"{source.source_id}#p{chunk.page}",
                        answers_leaf_id=answers.get(chunk.chunk_id),
                    )
                    for i, chunk in enumerate(cluster.chunks, 1)
                ),
            )
        )
        frozen_out[topic_id] = FrozenTopic(
            topic_id=topic_id,
            module_id=module_id_for(notebook.notebook_id, source.source_id),
            source_id=source.source_id,
            title=title,
            centroid=cluster.centroid,
            chunk_hashes=hashes,
        )

    module = Module(
        id=module_id_for(notebook.notebook_id, source.source_id),
        order=order,
        title=source.title,
        description="",
        topics=tuple(topics),
    )
    return module, chunks, frozen_out, fell_back


def _title_for(cluster: Cluster, labeller: Labeller | None) -> tuple[str, bool]:
    """A Topic title always exists. Labelling never blocks ingest."""
    if labeller is not None:
        try:
            title = (labeller([c.text for c in cluster.chunks]) or "").strip()
            if title:
                return title[:120], False
        except Exception:
            pass
        return _fallback_title(cluster), True
    return _fallback_title(cluster), False


def _fallback_title(cluster: Cluster) -> str:
    first = min(cluster.chunks, key=lambda c: c.char_start)
    return first.anchor[:120] or leaf_title(first.text)
