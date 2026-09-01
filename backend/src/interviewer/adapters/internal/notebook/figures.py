"""Where a figure belongs, decided by arithmetic.

ADR-0015 froze Topic boundaries and made them text's business. A figure is
attached to a Topic that text already drew; it never mints one and never moves
one. The shared embedding space makes attaching by similarity *possible* — a
diagram and its explanation genuinely do land near each other — and that is
exactly the temptation this module refuses. Similarity moves when the model
moves. Position does not, so re-ingesting a source attaches every figure
identically, and a citation means the same thing next month.

The rule, in order:

  1. the Topic of the text chunk at the figure's position on its own page,
  2. failing that, the Topic of the earliest chunk on the nearest page,
  3. failing that — a Source with no prose at all — nothing.

Rule 2 earns its place on real material. A slide deck puts a diagram on a page
whose only words are its title, and the passage that explains it sits on the
page before. Refusing to look past the page boundary drops exactly the figures
worth citing, which is why "nearest page" is the fallback rather than "none".
"""

from __future__ import annotations

from typing import Sequence

from ..chunking import Chunk
from .extract import Figure
from .sources import digest


def attach(figures: Sequence[Figure], chunks: Sequence[Chunk]) -> list[str | None]:
    """One `topic_id` (or None) per figure, in the order the figures arrived."""
    by_page: dict[int, list[Chunk]] = {}
    for chunk in chunks:
        if chunk.topic_id is None:
            continue
        by_page.setdefault(chunk.page, []).append(chunk)
    for page in by_page.values():
        page.sort(key=lambda c: c.char_start)

    out: list[str | None] = []
    for figure in figures:
        candidates = by_page.get(figure.page)
        if candidates:
            # A PDF gives no coordinates for an embedded image through this
            # path, so position within a page is the reading order the figure
            # was found in — deterministic, and right for the common case of a
            # figure sitting under the passage that introduces it.
            position = min(figure.index, len(candidates) - 1)
            out.append(candidates[position].topic_id)
            continue
        near = _nearest_page(by_page, figure.page)
        out.append(by_page[near][0].topic_id if near is not None else None)
    return out


def _nearest_page(by_page: dict[int, list[Chunk]], page: int) -> int | None:
    """The closest page carrying prose; the earlier one when two tie.

    Ties resolve backwards on purpose: a figure is introduced by the text
    before it far more often than by the text after it.
    """
    if not by_page:
        return None
    return min(by_page, key=lambda p: (abs(p - page), p))


def as_chunks(
    figures: Sequence[Figure],
    topic_ids: Sequence[str | None],
    *,
    source_id: str,
    notebook_id: str,
    object_key_for,
) -> list[Chunk]:
    """Figures, as rows of the chunk table.

    `char_start`/`char_end` are the figure's position on its page rather than a
    span of the source text — a picture has no characters. They exist so that
    ordering by locator keeps working, and so a figure sorts near the prose it
    sits beside. Dossier build never reads them: it filters to text (ADR-0017).
    """
    out: list[Chunk] = []
    for figure, topic_id in zip(figures, topic_ids):
        if topic_id is None:
            continue
        content_hash = digest(figure.data.hex())
        out.append(
            Chunk(
                chunk_id=f"{source_id}#fig{figure.page:04d}-{figure.index:03d}",
                source_id=source_id,
                page=figure.page,
                char_start=figure.index,
                char_end=figure.index + 1,
                text="",
                content_hash=content_hash,
                anchor="",
                topic_id=topic_id,
                modality="image",
                object_key=object_key_for(notebook_id, content_hash),
                media_type=figure.media_type,
            )
        )
    return out
