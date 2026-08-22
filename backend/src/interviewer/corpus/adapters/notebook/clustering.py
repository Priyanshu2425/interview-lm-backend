"""Clustering chunks into Topics, and the arithmetic that keeps them in budget.

The clusterer proposes; the budget disposes. Merging stops at the dossier target
and a Topic over the hard budget is split at a chunk boundary — both by
arithmetic, because ADR-0007 will not have the backbone inventing load units,
and will not have a model deciding how much material fits in a question either.

Bottom-up and deterministic: every chunk starts alone, the most similar
admissible pair merges, and merging stops when the next pair is no longer alike
enough or the result would breach the target. Nothing here is seeded randomly —
an id that lives for months may not depend on a random draw or on dictionary
order.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .chunking import Chunk
from .embedding import centroid_of

#: A Topic aims for what Cortex's own Topics measured: ~5k tokens at the median.
TARGET_TOPIC_TOKENS = 5_000
#: ADR-0005 assumes a whole Topic fits in context. 9k leaves headroom under 10k.
MAX_TOPIC_TOKENS = 9_000
#: Below this a Topic is too thin to examine; it joins its nearest neighbour.
MIN_TOPIC_TOKENS = 400
#: Two chunks belong together when they are this similar. Passages of one
#: subject share distinctive vocabulary well above this floor, and passages of
#: different subjects fall well below it once the terms common to the whole
#: source have been discounted.
SIMILARITY_FLOOR = 0.30
#: The weaker floor used only to bring a thin Topic up toward target size. A
#: Topic may absorb a merely-related neighbour; it may not absorb an unrelated
#: one just because it had room.
RELATEDNESS_FLOOR = 0.15


@dataclass(slots=True)
class Cluster:
    chunks: list[Chunk]
    centroid: tuple[float, ...]

    @property
    def tokens(self) -> int:
        return sum(c.approx_tokens for c in self.chunks)

    @property
    def earliest(self) -> int:
        return min(c.char_start for c in self.chunks)

    def recentre(self) -> None:
        self.centroid = centroid_of([c.embedding for c in self.chunks])


def cluster_chunks(chunks: list[Chunk]) -> list[Cluster]:
    """Cluster one Source's chunks, then size them against the budget."""
    if not chunks:
        return []
    ordered = sorted(chunks, key=lambda c: c.char_start)
    clusters = [Cluster([c], c.embedding) for c in ordered]
    clusters = _agglomerate(clusters, SIMILARITY_FLOOR, TARGET_TOPIC_TOKENS)
    clusters = _agglomerate(
        clusters, RELATEDNESS_FLOOR, TARGET_TOPIC_TOKENS,
        only_under=TARGET_TOPIC_TOKENS,
    )
    clusters = _merge_undersized(clusters)
    clusters = _split_oversized(clusters)
    clusters.sort(key=lambda c: c.earliest)
    for cluster in clusters:
        cluster.chunks.sort(key=lambda ch: ch.char_start)
    return clusters


def _agglomerate(
    clusters: list[Cluster],
    floor: float,
    ceiling: int,
    *,
    only_under: int | None = None,
) -> list[Cluster]:
    """Merge the most similar admissible pair until none is left.

    Indices are assigned in source order and never reused, so ties resolve to
    the earliest pair and the same Source always produces the same Topics.
    """
    n = len(clusters)
    if n < 2:
        return clusters

    centroids = np.array([c.centroid for c in clusters], dtype=float)
    tokens = np.array([float(c.tokens) for c in clusters])
    alive = np.ones(n, dtype=bool)
    members = [list(c.chunks) for c in clusters]

    similarity = centroids @ centroids.T
    np.fill_diagonal(similarity, -np.inf)

    while alive.sum() > 1:
        admissible = (
            (similarity >= floor)
            & alive[:, None]
            & alive[None, :]
            & ((tokens[:, None] + tokens[None, :]) <= ceiling)
        )
        if only_under is not None:
            admissible &= np.minimum(tokens[:, None], tokens[None, :]) < only_under
        if not admissible.any():
            break

        flat = int(np.argmax(np.where(admissible, similarity, -np.inf)))
        i, j = divmod(flat, n)
        if i > j:
            i, j = j, i

        members[i].extend(members[j])
        tokens[i] += tokens[j]
        alive[j] = False
        centroids[i] = np.array(centroid_of([c.embedding for c in members[i]]))
        row = centroids @ centroids[i]
        similarity[i, :] = row
        similarity[:, i] = row
        similarity[i, i] = -np.inf
        similarity[j, :] = -np.inf
        similarity[:, j] = -np.inf

    return [
        Cluster(members[i], tuple(centroids[i]))
        for i in range(n)
        if alive[i]
    ]


def _merge_undersized(clusters: list[Cluster]) -> list[Cluster]:
    """A Topic too thin to examine joins its nearest neighbour, or stands alone."""
    if len(clusters) < 2:
        return clusters
    return _agglomerate(
        sorted(clusters, key=lambda c: c.earliest),
        -1.0,
        MAX_TOPIC_TOKENS,
        only_under=MIN_TOPIC_TOKENS,
    )


def _split_oversized(clusters: list[Cluster]) -> list[Cluster]:
    """Split at a chunk boundary nearest the median. No chunk is ever divided."""
    out: list[Cluster] = []
    queue = list(clusters)
    while queue:
        cluster = queue.pop(0)
        if cluster.tokens <= MAX_TOPIC_TOKENS or len(cluster.chunks) < 2:
            out.append(cluster)
            continue
        ordered = sorted(cluster.chunks, key=lambda c: c.char_start)
        half, running, cut = cluster.tokens / 2, 0, 1
        for i, chunk in enumerate(ordered[:-1], 1):
            running += chunk.approx_tokens
            cut = i
            if running >= half:
                break
        for part in (ordered[cut:], ordered[:cut]):
            queue.insert(0, Cluster(part, centroid_of([c.embedding for c in part])))
    return out
