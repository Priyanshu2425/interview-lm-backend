"""The stored notebook, read back as a Corpus.

This is the module that keeps ADR-0015's promise. The Adapter clusters **once**,
at ingest; everything afterwards reads Topics out of `content` exactly as they
were frozen. Nothing here re-clusters, and nothing here can: it has no embedder
and no clusterer, only rows.
"""

from __future__ import annotations

from interviewer.corpus.contract import (
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

from .store import NotebookRecord, NotebookStore

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

    modules = []
    for source in record.sources:
        topics = sorted(
            topics_by_source.get(source.source_id, []), key=lambda t: t.order
        )
        if not topics:
            # A stub Module carries no Topic and is not examinable (ISSUE-0023).
            continue
        modules.append(
            Module(
                id=source.module_id,
                order=source.order,
                title=source.title,
                description="",
                topics=tuple(_renumber(topics)),
            )
        )
    if not modules:
        return None

    return Corpus(
        provenance=CorpusProvenance(
            source=f"notebook:{record.notebook_id}",
            extracted_at="",
            adapter=ADAPTER_NAME,
            adapter_version="1",
        ),
        tracks=(
            Track(
                key=track_key(record.notebook_id),
                title=record.title,
                modules=tuple(sorted(modules, key=lambda m: m.order)),
            ),
        ),
    )


def track_key(notebook_id: str) -> str:
    return f"nb-{notebook_id}"


def _topic_orders(store: NotebookStore, notebook_id: str) -> dict[str, int]:
    from interviewer.db.content import notebook_topic
    import sqlalchemy as sa

    with store._engine.begin() as c:  # noqa: SLF001 — same package, same table
        rows = c.execute(
            sa.select(notebook_topic.c.topic_id, notebook_topic.c.topic_order).where(
                notebook_topic.c.notebook_id == notebook_id
            )
        ).all()
    return {tid: order for tid, order in rows}


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
