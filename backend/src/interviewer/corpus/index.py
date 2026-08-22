"""The shipped Corpus, embedded once — and what that is allowed to be for.

ADR-0005 refused a vector store in the interview loop and named the one case it
would permit alongside: *"If something needs cross-Topic similarity — 'what else
relates to this?', sideways exploration, cross-Module connections — that
genuinely is a vector problem."* This module is that case and nothing wider.

Three rules hold it there.

**Structure is given, never derived.** The Notebook Adapter mints `topic_id`s by
clustering, because its source arrives with no divisions. This Corpus arrives
with Topics that are the join key for every row of Evidence and Topic Confidence
in `core`. So the build chunks, embeds, and stops: it never clusters, never
labels, never mints an id, and never moves a boundary. Chunk vectors are pooled
into the Topic they already belonged to.

**Nothing is embedded at question time.** A Topic's neighbours are its centroid
against every other centroid, computed here, offline. At runtime the answer is a
lookup in a file. ADR-0005's "there is no query to embed" stays literally true of
the running system rather than approximately true.

**The index states what it was built from.** Corpus fingerprint, embedding
model identity, build time and Topic count travel with the vectors, so a
re-scrape or a model change is detectable — ADR-0005's third objection answered
the way ADR-0015 answered it, rather than dismissed. Detecting it is ISSUE-0029;
reporting *which* of the two moved is ISSUE-0030, and lives in `related.py`
beside the gate it explains.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .chunking import chunk_source
from .contract import Corpus, Topic
from .digest import digest

#: Neighbours kept per Topic. Enough to answer "what else relates to this?"
#: without becoming a wall of links the reader has to triage.
TOP_K = 5

#: The artifact format. Bumped when the *shape* changes, which is separate from
#: the fingerprint changing: one means "this reader cannot parse it", the other
#: means "this content is out of date".
#:
#: 2 — carries `mean`, and edges are measured in the centred space (see `centre`).
#:     An index at version 1 ranked by raw cosine and its neighbours were noise,
#:     so it is not upgraded in place; it is refused and rebuilt.
FORMAT_VERSION = 2

#: Below this, two Topics are not related in any way worth showing. Anisotropy
#: (see `centre`) makes raw cosines cluster near 1.0 and centred ones spread out
#: around 0, so this threshold belongs to the centred space and nowhere else.
MIN_SCORE = 0.05


@dataclass(frozen=True, slots=True)
class Neighbour:
    """One edge, carrying enough for a consumer to decide what to show.

    `module_id` is stored rather than filtered on, because same-Module and
    cross-Module neighbours mean different things — one is "what leads into
    this", the other is the sideways connection this work was for — and which to
    show is a decision for the surface, not for the artifact.
    """

    topic_id: str
    title: str
    module_id: str
    same_module: bool
    score: float


@dataclass(frozen=True, slots=True)
class CorpusIndex:
    """Centroids and edges for one Corpus, at one model, at one fingerprint."""

    fingerprint: str
    embedding_model: str
    format_version: int = FORMAT_VERSION
    topic_count: int = 0
    #: When this artifact was built, ISO-8601 UTC — or empty when nothing
    #: stamped it. Injected by the caller rather than read here: the stamp is a
    #: fact about the *run*, and a function whose whole value is that the same
    #: inputs produce the same bytes must not reach for a clock.
    built_at: str = ""
    centroids: dict[str, tuple[float, ...]] = field(default_factory=dict)
    #: The mean of every Topic centroid, kept so that a vector produced later —
    #: a notebook's, say — can be centred against the same origin these edges
    #: were computed in. Without it the stored centroids are unusable for
    #: anything but display.
    mean: tuple[float, ...] = ()
    related: dict[str, tuple[Neighbour, ...]] = field(default_factory=dict)

    def neighbours(self, topic_id: str) -> tuple[Neighbour, ...]:
        return self.related.get(topic_id, ())


def fingerprint(corpus: Corpus) -> str:
    """What the index was built from, by content rather than by timestamp.

    Deliberately not `scrapedAt`: re-running the scraper and getting the same
    material back is not a change, and a fingerprint that said otherwise would
    cry stale every time somebody refreshed the Corpus for no reason. Topic ids
    are included as well as text, so a Topic that is renumbered or removed
    counts as a change even when every word survives.
    """
    parts: list[str] = []
    for topic in sorted(corpus.topics, key=lambda t: t.id):
        parts.append(topic.id)
        for leaf in sorted(topic.leaves, key=lambda leaf: leaf.id):
            parts.append(leaf.id)
            parts.append(leaf.text or "")
    return digest(*parts)


def _topic_chunks(topic: Topic) -> list[str]:
    """A Topic's prose, cut into spans the encoder can actually hold.

    Leaves are already the citation unit and already carry structure, so this
    manufactures none — it only divides what is too long to embed whole. A
    32,000-character Topic is about 8,000 tokens, and pooling that many windows
    into one vector averages a Topic into mush.
    """
    out: list[str] = []
    for leaf in topic.leaves:
        if not (leaf.text or "").strip():
            continue
        for chunk in chunk_source(leaf.id, leaf.text or ""):
            if chunk.text.strip():
                out.append(chunk.text)
    return out


def build(
    corpus: Corpus,
    embedder,
    *,
    top_k: int = TOP_K,
    built_at: str = "",
) -> CorpusIndex:
    """Embed every Topic and precompute its neighbours.

    Deterministic: the same Corpus and the same model produce the same artifact,
    which is what makes the fingerprint worth checking and the file worth
    reviewing in a diff.
    """
    module_of = {
        topic.id: module.id for module in corpus.modules for topic in module.topics
    }
    titles = {topic.id: topic.title for topic in corpus.topics}

    centroids: dict[str, tuple[float, ...]] = {}
    for topic in sorted(corpus.topics, key=lambda t: t.id):
        chunks = _topic_chunks(topic)
        if not chunks:
            # A Topic of pure references or prompts has nothing to embed. It
            # keeps its place in the Corpus and simply has no neighbours.
            continue
        vectors = embedder.embed(chunks)
        centroids[topic.id] = _centroid(vectors)

    # Similarity is measured from the centre of this Corpus, not from the
    # origin. See `centre` for why, and for what happens without it.
    mean = _mean(list(centroids.values())) if centroids else ()
    centred = {
        topic_id: centre(vector, mean) for topic_id, vector in centroids.items()
    }

    related: dict[str, tuple[Neighbour, ...]] = {}
    for topic_id in centroids:
        scored = [
            (
                _cosine(centred[topic_id], centred[other_id]),
                other_id,
            )
            for other_id in centroids
            if other_id != topic_id
        ]
        # Sorted by score, then by id: two Topics at an identical distance must
        # not swap places between builds, or the artifact stops being diffable.
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        related[topic_id] = tuple(
            Neighbour(
                topic_id=other_id,
                title=titles.get(other_id, ""),
                module_id=module_of.get(other_id, ""),
                same_module=module_of.get(other_id) == module_of.get(topic_id),
                score=round(score, 6),
            )
            for score, other_id in scored[:top_k]
            if score >= MIN_SCORE
        )

    return CorpusIndex(
        fingerprint=fingerprint(corpus),
        embedding_model=getattr(embedder, "model_name", "unknown"),
        topic_count=len(centroids),
        built_at=built_at,
        centroids=centroids,
        mean=mean,
        related=related,
    )


def centre(vector: Sequence[float], mean: Sequence[float]) -> tuple[float, ...]:
    """Move a vector to be measured from the Corpus's centre, then re-normalise.

    Without this the index is unusable, and it took a measurement to see it. A
    caption-trained text tower (ADR-0017) maps long technical prose into a very
    narrow cone: every pair of Topics in this Corpus scored between 0.974 and
    0.998, so the ranking was noise wearing the clothes of a similarity score —
    "NumPy" came back nearest to "CNN Fundamentals", and "Sorting Algorithms"
    nearest to "Attention Mechanisms".

    Subtracting the mean puts the spread back: the same pairs then range from
    -0.705 to 0.820. Measured against whether a Topic's five neighbours come
    from its own Track — DSA and AIML are different subjects, so a cross-Track
    neighbour is almost always wrong — this moves accuracy from 86% to **94%**,
    against 68% for picking at random. Scoring the top few chunk pairs instead
    of the centroids was also tried and was worse, at 85%.

    It is a property of the embedding space rather than of the Corpus, so the
    mean travels in the artifact and any later comparison must use it.
    """
    if not mean:
        return tuple(vector)
    return _normalise([value - m for value, m in zip(vector, mean)])


def _mean(vectors: Sequence[Sequence[float]]) -> tuple[float, ...]:
    width = len(vectors[0])
    return tuple(
        sum(vector[i] for vector in vectors) / len(vectors) for i in range(width)
    )


def _centroid(vectors: Sequence[Sequence[float]]) -> tuple[float, ...]:
    width = len(vectors[0])
    acc = [0.0] * width
    for vector in vectors:
        for i, value in enumerate(vector):
            acc[i] += value
    return _normalise([value / len(vectors) for value in acc])


def _normalise(values: Sequence[float]) -> tuple[float, ...]:
    norm = sum(value * value for value in values) ** 0.5
    if norm == 0.0:
        return tuple(values)
    return tuple(value / norm for value in values)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
