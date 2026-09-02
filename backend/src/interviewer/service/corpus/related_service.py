"""Related Topics — "what else relates to this?", answered from rows.

ADR-0005 refused a vector store in the interview loop and named the one case it
would permit alongside: *"If something needs cross-Topic similarity — sideways
exploration, cross-Module connections — that genuinely is a vector problem."*
This module is that case and nothing wider.

Two rules hold it there, and one of them changed shape in ISSUE-0037.

**Nothing is embedded at question time.** A Topic's neighbours are its stored
centroid against the other stored centroids of the same Corpus. Every vector was
written at ingest; none is produced to answer this. ADR-0005's "there is no
query to embed" stays literally true of the running system.

**A neighbour is only ever within one Corpus.** Two Libraries embedded by
different models are two geometries, and a cosine across them is a number with
no meaning. `notebook.embedding_model` is per Corpus, so staying inside one is
what makes the comparison well founded — and it is why the staleness machinery
ADR-0018 needed for a precomputed artifact is simply gone: rows cannot be stale
against the Topics they were written with.

ADR-0018 built a file because the Corpus was a file. Once the Corpus is rows,
the reason is gone and so is the file (ADR-0021).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

#: Neighbours kept per Topic. Enough to answer "what else relates to this?"
#: without becoming a wall of links the reader has to triage.
TOP_K = 5

#: Below this, two Topics are not related in any way worth showing. Anisotropy
#: (see `centre`) makes raw cosines cluster near 1.0 and centred ones spread out
#: around 0, so this threshold belongs to the centred space and nowhere else.
MIN_SCORE = 0.05


@dataclass(frozen=True, slots=True)
class Neighbour:
    """One edge, carrying enough for a consumer to decide what to show.

    `module_id` is reported rather than filtered on, because same-Module and
    cross-Module neighbours mean different things — one is "what leads into
    this", the other is the sideways connection this work was for — and which to
    show is a decision for the surface, not for this module.
    """

    topic_id: str
    title: str
    module_id: str
    same_module: bool
    score: float


def rank(
    topic_id: str,
    *,
    centroids: dict[str, Sequence[float]],
    titles: dict[str, str],
    module_of: dict[str, str],
    top_k: int = TOP_K,
) -> tuple[Neighbour, ...]:
    """The nearest Topics to one Topic, measured from the Corpus's own centre.

    Pure, and given everything it needs. The centring is the whole quality of
    this feature (see `centre`), and it needs the mean of the set being compared
    — which is why the set is passed in whole rather than queried one row at a
    time with an ORDER BY.
    """
    if topic_id not in centroids or len(centroids) < 2:
        return ()
    mean = _mean(list(centroids.values()))
    centred = {tid: centre(vector, mean) for tid, vector in centroids.items()}
    scored = [
        (_cosine(centred[topic_id], centred[other]), other)
        for other in centroids
        if other != topic_id
    ]
    # Sorted by score, then by id: two Topics at an identical distance must not
    # swap places between two reads of the same rows.
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return tuple(
        Neighbour(
            topic_id=other,
            title=titles.get(other, ""),
            module_id=module_of.get(other, ""),
            same_module=module_of.get(other) == module_of.get(topic_id),
            score=round(score, 6),
        )
        for score, other in scored[:top_k]
        if score >= MIN_SCORE
    )


def centre(vector: Sequence[float], mean: Sequence[float]) -> tuple[float, ...]:
    """Move a vector to be measured from the Corpus's centre, then re-normalise.

    Without this the ranking is unusable, and it took a measurement to see it. A
    caption-trained text tower (ADR-0017) maps long technical prose into a very
    narrow cone: every pair of Topics in the Scaler Corpus scored between 0.974
    and 0.998, so the ranking was noise wearing the clothes of a similarity
    score — "NumPy" came back nearest to "CNN Fundamentals", and "Sorting
    Algorithms" nearest to "Attention Mechanisms".

    Subtracting the mean puts the spread back: the same pairs then range from
    -0.705 to 0.820. Measured against whether a Topic's five neighbours come
    from its own Track — DSA and AIML are different subjects, so a cross-Track
    neighbour is almost always wrong — this moves accuracy from 86% to **94%**,
    against 68% for picking at random. Scoring the top few chunk pairs instead
    of the centroids was also tried and was worse, at 85%.

    It is a property of the embedding space rather than of the Corpus, so any
    comparison of these vectors has to do it.
    """
    if not mean:
        return tuple(vector)
    return _normalise([value - m for value, m in zip(vector, mean)])


class RelatedTopics:
    """Neighbours for a Topic, from the Corpus that Topic belongs to.

    Constructed against the notebook store rather than a file. Centroids are
    read once per Corpus and held, because they change only when that Corpus is
    ingested into — and the same call that rebuilds the served Corpus clears
    this.
    """

    __slots__ = ("_store", "_cache")

    def __init__(self, store) -> None:
        self._store = store
        self._cache: dict[str, dict] = {}

    def clear(self) -> None:
        self._cache.clear()

    def for_topic(self, topic_id: str) -> list[dict]:
        """Neighbours as the surface reads them, or an empty list.

        Empty means two different things — a Topic this deployment does not
        hold, and a Topic that genuinely has no neighbour above the floor — and
        deliberately looks the same from here. The surface renders nothing in
        both cases, which is honest in both cases.
        """
        notebook_id = self._store.notebook_of_topic(topic_id)
        if notebook_id is None:
            return []
        frozen = self._frozen(notebook_id)
        return [
            {
                "topic_id": n.topic_id,
                "title": n.title,
                "module_id": n.module_id,
                "same_module": n.same_module,
                "score": n.score,
            }
            for n in rank(
                topic_id,
                centroids={
                    tid: ft.centroid for tid, ft in frozen.items() if ft.centroid
                },
                titles={tid: ft.title for tid, ft in frozen.items()},
                module_of={tid: ft.module_id for tid, ft in frozen.items()},
            )
        ]

    def _frozen(self, notebook_id: str) -> dict:
        if notebook_id not in self._cache:
            self._cache[notebook_id] = self._store.frozen_topics(notebook_id)
        return self._cache[notebook_id]


def _mean(vectors: Sequence[Sequence[float]]) -> tuple[float, ...]:
    width = len(vectors[0])
    return tuple(
        sum(vector[i] for vector in vectors) / len(vectors) for i in range(width)
    )


def _normalise(values: Sequence[float]) -> tuple[float, ...]:
    norm = sum(value * value for value in values) ** 0.5
    if norm == 0.0:
        return tuple(values)
    return tuple(value / norm for value in values)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


@dataclass(frozen=True, slots=True)
class TouchedModule:
    """A Module the chosen scope shares material with.

    The reading the Module picker draws (ADR-0023). It is a claim about the
    **material** — these Modules are near each other in the embedding space —
    and carries nothing about the Candidate: no score, no Coverage, no Mastery,
    and no ordering that could be read as what to study.

    `in_scope` is what makes same-Module and cross-Module neighbours
    distinguishable at this placement: a neighbour inside the chosen scope is
    material already covered, and one outside it is the sideways connection.
    """

    module_id: str
    title: str
    in_scope: bool
    #: How many Topic-to-Topic edges reach this Module from the chosen scope.
    #: A count of connections, not a strength of recommendation.
    edges: int
    #: The closest single edge, so the server can order without the client
    #: inventing a threshold (ADR-0009).
    score: float


def modules_touched(
    topic_ids: list[str],
    *,
    neighbours_of,
    module_of: dict[str, str],
    titles: dict[str, str],
    in_scope: set[str],
) -> list[TouchedModule]:
    """Which Modules the chosen Topics reach, ranked by the closest edge.

    Aggregated here rather than on the client for the reason ADR-0009 gives:
    summing edges and ordering the result is deciding something, and the surface
    decides nothing. `neighbours_of` is passed in so this stays pure and so the
    caller chooses whether the edges come from rows or from a fixture.
    """
    best: dict[str, tuple[int, float]] = {}
    for topic_id in topic_ids:
        for row in neighbours_of(topic_id):
            module_id = row.get("module_id") or module_of.get(row["topic_id"], "")
            if not module_id:
                continue
            edges, score = best.get(module_id, (0, 0.0))
            best[module_id] = (edges + 1, max(score, float(row.get("score", 0.0))))
    out = [
        TouchedModule(
            module_id=module_id,
            title=titles.get(module_id, ""),
            in_scope=module_id in in_scope,
            edges=edges,
            score=round(score, 6),
        )
        for module_id, (edges, score) in best.items()
    ]
    # Closest edge first, then by id: two Modules at the same distance must not
    # swap places between two reads of the same rows.
    out.sort(key=lambda m: (-m.score, m.module_id))
    return out
