"""Dossier Loader — the only module that knows how Corpus content is stored.

Deep by construction: one method of consequence, an interface that should not
change when the storage does. There is no embedding model, no vector store and
no retriever (ADR-0005). Topic selection happens before any content is needed,
so there is no query to embed — the Interviewer says "give me this topic_id",
and that is a file read.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...model.corpus_models import Corpus, GradingMode, Leaf, Topic
from ...model.dossier_models import Dossier


class TopicNotFound(LookupError):
    """An unknown topic_id. Explicitly not the same as an empty dossier."""




class DossierLoader:
    """Loads a Topic dossier by id.

    Holds the Corpus in memory. The Corpus ships with the image and is read-only
    source material, so this is a dictionary lookup plus text already read from
    disk at ingest.
    """

    __slots__ = ("_corpus", "_by_topic")

    def __init__(self, corpus: Corpus) -> None:
        self._corpus = corpus
        self._by_topic: dict[str, tuple[Topic, str, str, int]] = {}
        self._index(corpus)

    def _index(self, corpus: Corpus) -> None:
        self._by_topic = {
            topic.id: (topic, module.id, module.title, module.order)
            for module in corpus.modules
            for topic in module.topics
        }

    def rebind(self, corpus: Corpus, retain: set[str] | None = None) -> None:
        """Point at a different Corpus without becoming a different object.

        A notebook is ingested or deleted while Sessions are in flight, and what
        is examinable changes underneath them. Rebuilding the object graph to
        pick that up would take the checkpointer with it and lose those
        Sessions, so the Corpus is swapped inside the loader instead.

        `retain` names Topics that must stay loadable even though they are no
        longer in the Corpus: a Visit already open on one has to finish, because
        a Visit that cannot finish produces either no Evidence or Evidence from
        a half-examined answer, and both corrupt the record.
        """
        kept = {
            tid: entry
            for tid, entry in self._by_topic.items()
            if retain and tid in retain
        }
        self._corpus = corpus
        self._index(corpus)
        for tid, entry in kept.items():
            self._by_topic.setdefault(tid, entry)

    def __contains__(self, topic_id: str) -> bool:
        return topic_id in self._by_topic

    def load(self, topic_id: str) -> Dossier:
        try:
            topic, module_id, module_title, module_order = self._by_topic[topic_id]
        except KeyError:
            raise TopicNotFound(topic_id) from None

        syllabus: list[str] = []
        for leaf in topic.leaves:
            syllabus.extend(leaf.syllabus)

        return Dossier(
            topic_id=topic.id,
            topic_title=topic.title,
            module_id=module_id,
            module_title=module_title,
            module_order=module_order,
            topic_order=topic.order,
            content=topic.content_leaves,
            ground_truth_pairs=topic.ground_truth_pairs,
            syllabus=tuple(dict.fromkeys(syllabus)),
            grading_mode_ceiling=topic.grading_mode_ceiling,
        )

    def budget_report(self) -> dict[str, int]:
        """Observed dossier sizes. ADR-0005 rests on the whole Topic fitting."""
        sizes = [self.load(tid).approx_tokens for tid in self._by_topic]
        sizes.sort()
        n = len(sizes)
        return {
            "topics": n,
            "min": sizes[0] if n else 0,
            "median": sizes[n // 2] if n else 0,
            "p90": sizes[int(n * 0.9)] if n else 0,
            "max": sizes[-1] if n else 0,
        }
