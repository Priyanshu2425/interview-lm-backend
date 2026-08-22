"""What a Candidate hands us, before anything has been made of it."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...digest import digest
from .extract import Page


@dataclass(frozen=True, slots=True)
class Source:
    """One uploaded file, page or note.

    `text` is what extraction produced. A Source that extracted to nothing is
    not an error — it is a stub, and ISSUE-0023 gives it its reason.
    """

    source_id: str
    title: str
    text: str = ""
    media_type: str = "text/markdown"
    stub_reason: str | None = None
    #: Where each region of the text came from, so a citation can name a page.
    pages: tuple[Page, ...] = field(default_factory=tuple)
    url: str = ""

    @property
    def is_stub(self) -> bool:
        return bool(self.stub_reason) or not self.text.strip()


@dataclass(frozen=True, slots=True)
class Notebook:
    """A Candidate's own Corpus Source. One notebook, many Sources."""

    notebook_id: str
    title: str
    sources: tuple[Source, ...] = field(default_factory=tuple)


__all__ = ["Notebook", "Source", "digest"]
