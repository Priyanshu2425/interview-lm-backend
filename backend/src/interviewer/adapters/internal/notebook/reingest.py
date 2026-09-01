"""Matching a changed Source against Topics that were frozen at first ingest.

ADR-0015's first rule, implemented: **cluster once, then freeze.** A re-ingest
never re-clusters what already exists. Its chunks are matched against the frozen
centroids, and only the material that matches nothing is clustered at all.

The alternative — re-clustering and re-minting — has no error state. It produces
Beta posteriors that quietly stop referring to what they referred to last week,
which is the failure this module exists to make impossible.

MATCH_FLOOR is the whole judgement call here, so it is named, tested and stated
rather than buried in the matcher.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..adapter import FrozenTopic
from ..chunking import Chunk
from ..clustering import cluster_chunks
from ..embedding import cosine

#: How alike a chunk must be to a frozen centroid to join the Topic it belongs
#: to. Deliberately below the clusterer's own floor: joining an established
#: Topic is a weaker claim than forming one, and the alternative to joining is
#: minting an id that Evidence will be keyed on for months.
MATCH_FLOOR = 0.20


@dataclass(slots=True)
class Match:
    """What a re-ingest did, in terms of the ids that outlive it."""

    surviving: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)
    vanished: list[str] = field(default_factory=list)
    matched_chunks: int = 0
    unmatched_chunks: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.new or self.vanished)


def match_to_frozen(
    chunks: list[Chunk],
    frozen: dict[str, FrozenTopic],
    *,
    mint: callable,
) -> Match:
    """Assign chunks to frozen Topics; cluster only what fits nowhere.

    `mint` names a Topic that did not exist before. It is passed in rather than
    computed here so that id derivation stays in one place — the Adapter's.
    """
    result = Match()
    if not frozen:
        for cluster in cluster_chunks(chunks):
            topic_id = mint(cluster)
            for chunk in cluster.chunks:
                chunk.topic_id = topic_id
            result.new.append(topic_id)
        result.unmatched_chunks = len(chunks)
        return result

    by_hash = {h: tid for tid, ft in frozen.items() for h in ft.chunk_hashes}
    unmatched: list[Chunk] = []

    for chunk in chunks:
        # An unchanged chunk needs no similarity judgement at all.
        topic_id = by_hash.get(chunk.content_hash)
        if topic_id is None:
            topic_id = _nearest(chunk, frozen)
        if topic_id is None:
            unmatched.append(chunk)
        else:
            chunk.topic_id = topic_id
            result.matched_chunks += 1

    if unmatched:
        result.unmatched_chunks = len(unmatched)
        for cluster in cluster_chunks(unmatched):
            topic_id = mint(cluster)
            for chunk in cluster.chunks:
                chunk.topic_id = topic_id
            result.new.append(topic_id)

    landed = {c.topic_id for c in chunks}
    result.surviving = sorted(tid for tid in frozen if tid in landed)
    result.vanished = sorted(tid for tid in frozen if tid not in landed)
    return result


def _nearest(chunk: Chunk, frozen: dict[str, FrozenTopic]) -> str | None:
    best_id, best_similarity = None, MATCH_FLOOR
    for topic_id, topic in sorted(frozen.items()):
        if not topic.centroid:
            continue
        similarity = cosine(chunk.embedding, topic.centroid)
        if similarity >= best_similarity:
            best_id, best_similarity = topic_id, similarity
    return best_id
