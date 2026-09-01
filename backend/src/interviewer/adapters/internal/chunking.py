"""The shared chunker, carrying the one rule this Adapter owns.

Chunking itself moved to `corpus/chunking.py` (ISSUE-0029) so that the shipped
Corpus and a Candidate's notebook are cut into spans by the same code. What
stayed behind is the part that is genuinely about notebooks: a heading that
announces worked answers has to start a new chunk, because a question and its
answer must land in different leaves before either can be recognised for what it
is (ISSUE-0024).
"""

from __future__ import annotations

from functools import partial

from ...util.chunking import (
    MAX_CHARS,
    TARGET_CHARS,
    Chunk,
    first_heading,
    leaf_title,
)
from ...util.chunking import chunk_source as _chunk_source
from .notebook.extract import Extracted


def answer_boundary(text: str, start: int, end: int) -> bool:
    """A heading announcing worked answers always begins a new chunk."""
    from .mining import KEY_HEADING, PROMPT_HEADING

    head = text[start:end][:200]
    return bool(KEY_HEADING.match(head.lstrip()) or PROMPT_HEADING.match(head.lstrip()))


chunk_source = partial(_chunk_source, boundary=answer_boundary)

__all__ = [
    "MAX_CHARS", "TARGET_CHARS", "Chunk", "Extracted", "answer_boundary",
    "chunk_source", "first_heading", "leaf_title",
]
