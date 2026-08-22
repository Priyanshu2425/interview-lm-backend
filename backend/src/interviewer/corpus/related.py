"""Reading the Corpus index back, and refusing to serve it when it is wrong.

The artifact is data, produced offline and read at runtime — the same shape as
`corpus.json` itself: one build, read many times, never written by the API. A
deployment therefore needs no model to *use* Related Topics, only to rebuild
them.

Everything here is arranged around one rule: **an index that does not match the
Corpus being served produces no neighbours, never different ones.** A wrong
neighbour is a claim about the material that nobody can trace, and this product
would rather say nothing — the same instinct that makes an untested Topic read
*Untested* instead of zero.

Making that state *visible* is ISSUE-0030. Making it *safe* is here, because a
thing that can silently lie must not ship first and be fixed second.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .contract import Corpus
from .index import FORMAT_VERSION, CorpusIndex, Neighbour, fingerprint

log = logging.getLogger(__name__)

#: Written with enough precision to reproduce a cosine to six places and no
#: more: an artifact that is reviewed in a diff should not be full of noise.
_PRECISION = 6


def save(index: CorpusIndex, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "format_version": index.format_version,
        "fingerprint": index.fingerprint,
        "embedding_model": index.embedding_model,
        "topic_count": index.topic_count,
        # Kept alongside the edges rather than discarded with them. They are
        # what lets a later question — which shipped Topics does a Candidate's
        # own material correspond to? — be answered by comparison, on a machine
        # that has no model (ADR-0017 put both corpora in one space).
        # The origin the edges were measured from (see index.centre). Stored
        # because centroids without it cannot be compared to anything later.
        "mean": [round(v, _PRECISION) for v in index.mean],
        "centroids": {
            topic_id: [round(v, _PRECISION) for v in vector]
            for topic_id, vector in sorted(index.centroids.items())
        },
        "related": {
            topic_id: [
                {
                    "topic_id": n.topic_id,
                    "title": n.title,
                    "module_id": n.module_id,
                    "same_module": n.same_module,
                    "score": n.score,
                }
                for n in neighbours
            ]
            for topic_id, neighbours in sorted(index.related.items())
        },
    }
    # Deterministic on disk: same Corpus, same model, byte-identical file.
    path.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")


def load(path: Path) -> CorpusIndex | None:
    """The artifact as written, or None when it is absent or unreadable.

    A malformed index is treated exactly like a missing one. It is derived data
    that a single command rebuilds, so there is nothing here worth failing a
    boot over.
    """
    if not path.exists():
        return None
    try:
        body = json.loads(path.read_text())
        if int(body.get("format_version", 0)) != FORMAT_VERSION:
            log.warning(
                "corpus index at %s is format %s, this build reads %s",
                path, body.get("format_version"), FORMAT_VERSION,
            )
            return None
        return CorpusIndex(
            fingerprint=body["fingerprint"],
            embedding_model=body["embedding_model"],
            format_version=int(body["format_version"]),
            topic_count=int(body.get("topic_count", 0)),
            mean=tuple(float(v) for v in (body.get("mean") or ())),
            centroids={
                topic_id: tuple(float(v) for v in vector)
                for topic_id, vector in (body.get("centroids") or {}).items()
            },
            related={
                topic_id: tuple(
                    Neighbour(
                        topic_id=n["topic_id"],
                        title=n.get("title", ""),
                        module_id=n.get("module_id", ""),
                        same_module=bool(n.get("same_module")),
                        score=float(n.get("score", 0.0)),
                    )
                    for n in neighbours
                )
                for topic_id, neighbours in (body.get("related") or {}).items()
            },
        )
    except Exception:
        log.warning("corpus index at %s could not be read", path, exc_info=True)
        return None


@dataclass(frozen=True, slots=True)
class Staleness:
    """Why an index is not being served. Read by ISSUE-0030, acted on here."""

    present: bool
    corpus_changed: bool = False
    model_changed: bool = False

    @property
    def fresh(self) -> bool:
        return self.present and not self.corpus_changed and not self.model_changed

    @property
    def reason(self) -> str | None:
        if not self.present:
            return "no index has been built"
        if self.corpus_changed and self.model_changed:
            return "the Corpus and the embedding model have both changed"
        if self.corpus_changed:
            return "the Corpus has changed since the index was built"
        if self.model_changed:
            return "the embedding model has changed since the index was built"
        return None


class RelatedTopics:
    """Neighbours for a Topic, or nothing at all.

    Constructed against the Corpus it will be asked about, so the check happens
    once at wiring rather than on every request.
    """

    __slots__ = ("_index", "_staleness")

    def __init__(
        self,
        index: CorpusIndex | None,
        corpus: Corpus,
        *,
        embedding_model: str | None = None,
    ) -> None:
        if index is None:
            self._index, self._staleness = None, Staleness(present=False)
            return

        corpus_changed = index.fingerprint != fingerprint(corpus)
        model_changed = bool(
            embedding_model and index.embedding_model != embedding_model
        )
        self._staleness = Staleness(
            present=True,
            corpus_changed=corpus_changed,
            model_changed=model_changed,
        )
        # Serving is gated on the **Corpus** alone, and deliberately not on the
        # model. Nothing embeds at request time: the edges were decided when the
        # index was built and describe the Corpus as that model saw it, so they
        # stay internally consistent however the deployment is configured
        # afterwards. Gating on the model would mean the shipped artifact — built
        # with the real encoder — served nothing on a deployment running the
        # lexical stand-in, which is the default one.
        #
        # A model mismatch still matters, and is still reported: anyone
        # comparing a *new* vector against these centroids must be in the same
        # space to get an answer worth having. That is the notebook-alignment
        # case, and it reads `staleness`.
        self._index = None if corpus_changed else index
        if corpus_changed:
            log.warning("Related Topics disabled: %s", self._staleness.reason)
        elif model_changed:
            log.info(
                "Corpus index was built by %s and %s is running; edges still "
                "serve, comparisons against these centroids will not",
                index.embedding_model, embedding_model,
            )

    @property
    def staleness(self) -> Staleness:
        return self._staleness

    @property
    def available(self) -> bool:
        return self._index is not None

    def for_topic(self, topic_id: str) -> list[dict]:
        """Neighbours as the surface reads them, or an empty list.

        Empty means three different things — no index, a stale one, or a Topic
        that genuinely has no neighbours — and deliberately looks the same from
        here. The surface renders nothing in all three cases, which is honest in
        all three cases.
        """
        if self._index is None:
            return []
        return [
            {
                "topic_id": n.topic_id,
                "title": n.title,
                "module_id": n.module_id,
                "same_module": n.same_module,
                "score": n.score,
            }
            for n in self._index.neighbours(topic_id)
        ]
