"""A Corpus the Candidate brought. See `adapter.py` for the pipeline."""

from ..adapter import (
    ADAPTER_NAME,
    ADAPTER_VERSION,
    FrozenTopic,
    Ingested,
    IngestReport,
    Labeller,
    ingest_notebook,
    module_id_for,
    topic_id_for,
)
from ..chunking import Chunk, chunk_source
from .extract import (
    Extracted, Figure, Page, extract, extract_figures, extract_html, extract_pdf,
    extract_text,
)
from .figures import as_chunks, attach
from ..clustering import MAX_TOPIC_TOKENS, TARGET_TOPIC_TOKENS, cluster_chunks
from ..embedding import DIM, Embedder, HashingEmbedder, ImageEmbedder, cosine
from .reingest import MATCH_FLOOR, Match, match_to_frozen
from .sources import Notebook, Source

__all__ = [
    "ADAPTER_NAME", "ADAPTER_VERSION", "Chunk", "DIM", "Embedder",
    "FrozenTopic", "ImageEmbedder",
    "HashingEmbedder", "Ingested", "IngestReport", "Labeller", "MAX_TOPIC_TOKENS",
    "Notebook", "Source", "TARGET_TOPIC_TOKENS", "chunk_source", "cluster_chunks",
    "cosine", "ingest_notebook", "module_id_for", "topic_id_for",
    "Extracted", "Figure", "Page", "as_chunks", "attach", "extract",
    "extract_figures", "extract_html", "extract_pdf", "extract_text",
    "MATCH_FLOOR", "Match", "match_to_frozen",
]
