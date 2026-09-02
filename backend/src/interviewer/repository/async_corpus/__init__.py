"""Corpus reading, for the async routes.

There is nothing async here and there is no second implementation. A Corpus is
composed in memory and read from memory, so `CorpusService`, `DossierLoader` and
`RelatedTopics` have nothing to await and gain nothing from a duplicate.

The `Async*` names remain because the routes annotate with them. They are
aliases: one class, one rebind path, no drift. `deps.refresh_corpus` rebinds
these exact singletons after an ingest or a deletion, which a parallel set of
objects would have silently missed.
"""

from ...model.corpus_models import Corpus as AsyncCorpus
from ...service.corpus.loader_service import DossierLoader as AsyncDossierLoader
from ...service.corpus.readings_service import CorpusService as AsyncCorpusService
from ...service.corpus.related_service import RelatedTopics as AsyncRelatedTopics

__all__ = [
    "AsyncDossierLoader",
    "AsyncCorpusService",
    "AsyncRelatedTopics",
    "AsyncCorpus",
]
