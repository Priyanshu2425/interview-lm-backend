"""Chunks, and the locators that make a citation possible.

A chunk is a contiguous span of its source. That is the whole discipline here:
`text[char_start:char_end]` is the chunk's text, exactly, so a citation can point
at the source rather than at a paraphrase of it (ADR-0015).

Shared rather than owned by an Adapter. Cutting text into contiguous spans is
the same job whatever produced the text, and both a Candidate's notebook and the
shipped Corpus need it done identically — two chunkers would mean two answers to
"is this the same span", which is the question content addressing exists to
settle. What *is* source-specific stays source-specific: the one rule that knows
about worked answers arrives as `boundary`, injected by the Adapter that
understands them (ISSUE-0029).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from typing import Callable, Protocol

from .digest import digest


class Locator(Protocol):
    """Whatever can say which page a character offset fell on.

    Structural, so the shared chunker never has to import an Adapter's idea of
    what a page is.
    """

    def page_of(self, char_start: int) -> int: ...

    def anchor_of(self, char_start: int) -> str: ...


#: Given the source and a candidate span, does a chunk have to begin here?
#: Injected, because the only rule that currently says yes is about Ground Truth
#: headings, and Ground Truth is a notebook's concern (ISSUE-0024).
Boundary = Callable[[str, int, int], bool]

#: Chunk sizes in characters. Tokens are estimated at four characters apiece,
#: the same cheap estimate the Dossier Loader reports budgets with.
TARGET_CHARS = 2_600
MAX_CHARS = 3_200

_BLOCK = re.compile(r"\n\s*\n")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(slots=True)
class Chunk:
    """A span of one Source, with everything needed to cite it."""

    chunk_id: str
    source_id: str
    page: int
    char_start: int
    char_end: int
    text: str
    content_hash: str
    anchor: str = ""
    topic_id: str | None = None
    embedding: tuple[float, ...] = field(default=())
    #: What this span is, once mining has looked at it: content | prompt |
    #: ground_truth. Set by the Adapter, carried into the store, never guessed
    #: at read time.
    leaf_kind: str = "content"
    answers_chunk_id: str | None = None
    #: text | image. An image chunk carries no prose and no leaf: it is stored,
    #: cited and searched, and dossier build steps over it (ADR-0017).
    modality: str = "text"
    #: Where the pixels are. Set for exactly the image chunks, which is a
    #: database constraint rather than a convention here.
    object_key: str | None = None
    media_type: str = "text/plain"

    @property
    def approx_tokens(self) -> int:
        return len(self.text) // 4

    @property
    def is_image(self) -> bool:
        return self.modality == "image"


def _blocks(text: str) -> list[tuple[int, int]]:
    """Partition the source into contiguous paragraph blocks.

    Contiguous, not merely adjacent: every character of the source belongs to
    exactly one block, separators included, so chunks reassemble the source.
    """
    out: list[tuple[int, int]] = []
    cursor = 0
    for m in _BLOCK.finditer(text):
        out.append((cursor, m.end()))
        cursor = m.end()
    if cursor < len(text):
        out.append((cursor, len(text)))
    return out or [(0, len(text))]


def _split_long(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Cut one oversized block at sentence boundaries, keeping spans contiguous."""
    if end - start <= MAX_CHARS:
        return [(start, end)]
    body = text[start:end]
    pieces: list[tuple[int, int]] = []
    cursor = start
    for m in _SENTENCE.finditer(body):
        boundary = start + m.end()
        if boundary - cursor >= TARGET_CHARS:
            pieces.append((cursor, boundary))
            cursor = boundary
    if cursor < end:
        pieces.append((cursor, end))
    # A block with no sentence boundaries at all still has to be divided.
    divided: list[tuple[int, int]] = []
    for a, b in pieces:
        while b - a > MAX_CHARS:
            divided.append((a, a + MAX_CHARS))
            a += MAX_CHARS
        divided.append((a, b))
    return divided


def _heading(text: str, start: int) -> bool:
    return text[start:].lstrip().startswith("#")


def chunk_source(
    source_id: str,
    text: str,
    *,
    page: int = 1,
    extracted: "Locator | None" = None,
    boundary: "Boundary | None" = None,
) -> list[Chunk]:
    """Cut a Source into chunks on structure where structure exists.

    A chunk's page is the page its first character was extracted from, so a
    citation names where the reader will actually find the passage.
    """
    spans: list[tuple[int, int]] = []
    for start, end in _blocks(text):
        spans.extend(_split_long(text, start, end))

    grouped: list[tuple[int, int]] = []
    for start, end in spans:
        if not grouped:
            grouped.append((start, end))
            continue
        gs, ge = grouped[-1]
        breaks = _heading(text, start) and (ge - gs) >= TARGET_CHARS // 2
        forced = boundary(text, start, end) if boundary is not None else False
        if breaks or (end - gs) > MAX_CHARS or forced:
            grouped.append((start, end))
        else:
            grouped[-1] = (gs, end)

    # A trailing span of pure whitespace is not a chunk; it belongs to the one
    # before it, so that every chunk carries text and the source still reassembles.
    merged: list[tuple[int, int]] = []
    for start, end in grouped:
        if not text[start:end].strip() and merged:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

    chunks = []
    for i, (start, end) in enumerate(merged, 1):
        body = text[start:end]
        chunks.append(
            Chunk(
                chunk_id=f"{source_id}#{i:04d}",
                source_id=source_id,
                page=extracted.page_of(start) if extracted else page,
                char_start=start,
                char_end=end,
                text=body,
                content_hash=digest(body),
                anchor=first_heading(body)
                or (extracted.anchor_of(start) if extracted else ""),
            )
        )
    return chunks


def first_heading(body: str) -> str:
    for line in body.splitlines():
        if line.lstrip().startswith("#"):
            return line.lstrip("# ").strip()
    return ""


def leaf_title(body: str) -> str:
    """A title for a chunk that always exists. The contract requires one."""
    heading = first_heading(body)
    if heading:
        return heading[:80]
    for line in body.splitlines():
        if line.strip():
            return line.strip()[:80]
    return "Passage"
