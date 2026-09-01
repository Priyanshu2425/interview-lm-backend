"""The stored notebook, read back as a Corpus.

This is the module that keeps ADR-0015's promise. The Adapter clusters **once**,
at ingest; everything afterwards reads Topics out of `content` exactly as they
were frozen. Nothing here re-clusters, and nothing here can: it has no embedder
and no clusterer, only rows.
"""

from __future__ import annotations

from interviewer.model.corpus import (
    Corpus, CorpusProvenance, Leaf, LeafKind, Module, Topic, Track,
)

#: The stored kind, read back as the contract's. A key whose prompt did not
#: survive into the same Topic reads as ordinary content rather than as an
#: authoritative answer to a question nobody can see.
_KINDS = {
    "content": LeafKind.CONTENT,
    "prompt": LeafKind.PROMPT,
    "ground_truth": LeafKind.GROUND_TRUTH,
}

from ...repository.notebooks import NotebookRecord, NotebookStore

ADAPTER_NAME = "notebook"


def corpus_for(store: NotebookStore, record: NotebookRecord) -> Corpus | None:
    """Rebuild one notebook's Corpus from what was frozen at ingest."""
    topics_by_source: dict[str, list[Topic]] = {}
    frozen = store.frozen_topics(record.notebook_id)
    # Text only, deliberately. A Leaf is something a Candidate can be asked to
    # explain and a dossier is prose that must reassemble its source byte for
    # byte; an image chunk is neither, and it is stored beside them rather than
    # among them (ADR-0017).
    chunks = store.chunks_of(record.notebook_id, modality="text")
    by_topic: dict[str, list[dict]] = {}
    for chunk in chunks:
        by_topic.setdefault(chunk["topic_id"], []).append(chunk)

    orders = _topic_orders(store, record.notebook_id)
    for topic_id, ft in frozen.items():
        rows = sorted(by_topic.get(topic_id, []), key=lambda r: r["char_start"])
        if not rows:
            continue
        topics_by_source.setdefault(ft.source_id, []).append(
            Topic(
                id=topic_id,
                order=orders[topic_id],
                title=ft.title,
                leaves=tuple(_leaf(r, i, rows) for i, r in enumerate(rows, 1)),
            )
        )

    # Grouped by Track, because a Track is part of the structure a source can
    # arrive with (ISSUE-0034). An upload has none and every Module lands in the
    # notebook's own Track, which is what every notebook did before imports
    # existed; an import keeps the Tracks it was authored with, so a Corpus that
    # went into Postgres comes back out as the same Corpus.
    by_track: dict[tuple[str, str], list[Module]] = {}
    for source in record.sources:
        topics = sorted(
            topics_by_source.get(source.source_id, []), key=lambda t: t.order
        )
        if not topics:
            # A stub Module carries no Topic and is not examinable (ISSUE-0023).
            continue
        key = source.track_key or track_key(record.notebook_id)
        title = source.track_title or record.title
        by_track.setdefault((key, title), []).append(
            Module(
                id=source.module_id,
                order=source.order,
                title=source.title,
                description="",
                topics=tuple(_renumber(topics)),
            )
        )
    if not by_track:
        return None

    return Corpus(
        provenance=_provenance(record),
        tracks=tuple(
            Track(
                key=key,
                title=title,
                modules=tuple(sorted(modules, key=lambda m: m.order)),
            )
            for (key, title), modules in sorted(by_track.items())
        ),
    )


def _provenance(record: NotebookRecord) -> CorpusProvenance:
    """Which extract this Library is.

    An imported Corpus keeps the provenance it arrived with, because PRD-0001
    §13 asks what a Session ran against and "the notebook adapter" is not that
    answer — the material came from somewhere, and the import is a transport
    rather than a source. A Candidate's own upload has no other source, so the
    adapter genuinely is the extract.
    """
    stored = record.provenance or {}
    if stored.get("source"):
        return CorpusProvenance(
            source=stored["source"],
            extracted_at=stored.get("extracted_at", ""),
            adapter=stored.get("adapter", ADAPTER_NAME),
            adapter_version=str(stored.get("adapter_version", "1")),
        )
    return CorpusProvenance(
        source=f"notebook:{record.notebook_id}",
        extracted_at="",
        adapter=ADAPTER_NAME,
        adapter_version="1",
    )


def track_key(notebook_id: str) -> str:
    return f"nb-{notebook_id}"


#: What a deployment holding no Corpus at all serves. Empty rather than absent,
#: so everything downstream keeps its shape: the picker lists no Modules instead
#: of failing, and the first upload composes onto nothing exactly as the second
#: composes onto something.
EMPTY = Corpus(
    provenance=CorpusProvenance(
        source="none", extracted_at="", adapter="none", adapter_version="1",
    ),
    tracks=(),
)


def merge(corpora: list[Corpus]) -> Corpus:
    """Every Library this deployment serves, as one Corpus.

    The backbone was always Corpus-agnostic (ADR-0007); it was never
    multi-Corpus. A Candidate examining themselves on a shared course *and* on
    their own notes needs both in one picker, and `topic_id` was required to be
    globally unique precisely so that this is a merge rather than a namespace
    problem.

    It lives here, in the package the Corpora come from, because after
    ISSUE-0037 there is no base to compose onto — every Corpus is somebody's,
    and they all come out of `content`.
    """
    present = [c for c in corpora if c is not None]
    if not present:
        return EMPTY
    if len(present) == 1:
        return present[0]
    return Corpus(
        provenance=CorpusProvenance(
            source=" + ".join(c.provenance.source for c in present),
            extracted_at=max(c.provenance.extracted_at for c in present),
            adapter=" + ".join(sorted({c.provenance.adapter for c in present})),
            adapter_version=" + ".join(
                sorted({c.provenance.adapter_version for c in present})
            ),
        ),
        tracks=tuple(t for c in present for t in c.tracks),
    )


def _topic_orders(store: NotebookStore, notebook_id: str) -> dict[str, int]:
    """Asked of the store rather than read out of its engine.

    That indirection is the whole reason the async side can reuse `corpus_for`:
    a rebuild needs three readings, and none of them has to be a connection.
    """
    return store.topic_orders(notebook_id)


def _renumber(topics: list[Topic]) -> list[Topic]:
    """Order is contiguous within a Module even after a Topic is removed."""
    return [
        Topic(id=t.id, order=i, title=t.title, leaves=t.leaves)
        for i, t in enumerate(topics, 1)
    ]


def _leaf(row: dict, order: int, siblings: list[dict]) -> Leaf:
    kind = _KINDS.get(row.get("leaf_kind") or "content", LeafKind.CONTENT)
    answers = row.get("answers_chunk_id")
    reachable = answers in {r["chunk_id"] for r in siblings}
    if kind is LeafKind.GROUND_TRUTH and not reachable:
        kind, answers = LeafKind.CONTENT, None
    return Leaf(
        id=row["chunk_id"],
        order=order,
        title=_leaf_title(row),
        kind=kind,
        text=row["text"],
        source_ref=f"{row['source_id']}#p{row['page']}",
        answers_leaf_id=answers if kind is LeafKind.GROUND_TRUTH else None,
    )


def _leaf_title(row: dict) -> str:
    if row["anchor"]:
        return row["anchor"][:80]
    for line in row["text"].splitlines():
        if line.strip():
            return line.strip()[:80]
    return "Passage"
