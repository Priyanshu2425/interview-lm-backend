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

Making it *safe* came first, because a thing that can silently lie must not ship
first and be fixed second. Making the state *visible* is ISSUE-0030 and is
`Staleness.reading()` below — deliberately in the same file as the gate it
explains, so that "the reading says stale" and "the gate serves nothing" cannot
drift apart into two opinions about one artifact.
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
        # The one field that is allowed to differ between two builds of the
        # same Corpus. Everything else describes content and must not, or the
        # artifact stops being reviewable in a diff.
        "built_at": index.built_at,
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
            built_at=str(body.get("built_at", "")),
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
    """What the index was built from, and whether that is still true.

    Deliberately not a boolean. A re-scrape that changed two Topics and a model
    swap are different problems with different fixes, and "stale" alone tells an
    operator neither — so the two are reported separately and named.
    """

    present: bool
    corpus_changed: bool = False
    model_changed: bool = False
    built_at: str = ""
    topic_count: int = 0
    index_fingerprint: str = ""
    corpus_fingerprint: str = ""
    index_model: str = ""
    running_model: str = ""

    @property
    def fresh(self) -> bool:
        return self.present and not self.corpus_changed and not self.model_changed

    @property
    def state(self) -> str:
        """`absent`, `fresh` or `stale` — three states, never two.

        Never built and gone out of date are different problems: one is a
        command nobody has run, the other is a command somebody needs to run
        again. Collapsing them would send an operator looking for a change that
        did not happen.
        """
        if not self.present:
            return "absent"
        return "fresh" if self.fresh else "stale"

    @property
    def changed(self) -> tuple[str, ...]:
        """Which of the two inputs moved. Empty when neither did."""
        out = []
        if self.corpus_changed:
            out.append("corpus")
        if self.model_changed:
            out.append("model")
        return tuple(out)

    @property
    def serving(self) -> bool:
        """Whether neighbours are actually being served.

        Not the same question as `fresh`, and the gap is intentional: a model
        mismatch is reported and still serves, because nothing embeds at request
        time. Reported here so that a console showing "stale" can also show
        whether the feature is still working, rather than leaving the reader to
        infer one from the other and get it wrong.
        """
        return self.present and not self.corpus_changed

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

    def reading(self) -> dict:
        """The whole state, as an operator console renders it.

        A state rather than a failure: the Corpus is fully examinable with no
        index at all, so nothing here is an error and nothing raises.
        """
        return {
            "state": self.state,
            "changed": list(self.changed),
            "serving": self.serving,
            "reason": self.reason,
            "built_at": self.built_at,
            "topic_count": self.topic_count,
            "index_fingerprint": self.index_fingerprint,
            "corpus_fingerprint": self.corpus_fingerprint,
            "index_model": self.index_model,
            "running_model": self.running_model,
            "rebuild_with": REBUILD_COMMAND,
        }


#: Where an operator is sent when the reading says stale. Named once, here, so
#: the console, the script's own help and `data/README.md` cannot disagree.
REBUILD_COMMAND = "python scripts/embed_corpus.py --provider siglip"


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
        current = fingerprint(corpus)
        if index is None:
            self._index = None
            self._staleness = Staleness(
                present=False,
                corpus_fingerprint=current,
                running_model=embedding_model or "",
            )
            return

        corpus_changed = index.fingerprint != current
        model_changed = bool(
            embedding_model and index.embedding_model != embedding_model
        )
        self._staleness = Staleness(
            present=True,
            corpus_changed=corpus_changed,
            model_changed=model_changed,
            built_at=index.built_at,
            topic_count=index.topic_count,
            index_fingerprint=index.fingerprint,
            corpus_fingerprint=current,
            index_model=index.embedding_model,
            running_model=embedding_model or "",
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
