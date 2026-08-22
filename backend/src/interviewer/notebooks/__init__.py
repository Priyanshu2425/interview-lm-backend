"""Notebooks — a Corpus the Candidate brought, stored and served.

The Adapter under `corpus/adapters/notebook/` is pure and knows nothing about
Postgres. This package is where its output is persisted, composed into the
Corpus the API serves, and deleted when the Candidate says so.
"""

from .service import (
    IngestNotClaimable, NotebookService, SharedCorpusIsNotYours,
    SourceBytesMissing, UploadedSource,
)
from .store import NotebookRecord, NotebookStore, SourceRecord

__all__ = [
    "IngestNotClaimable", "NotebookRecord", "NotebookService", "NotebookStore",
    "SharedCorpusIsNotYours", "SourceBytesMissing", "SourceRecord",
    "UploadedSource",
]
