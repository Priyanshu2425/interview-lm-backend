"""Extraction — text, and the locator that will cite it.

Every extractor returns the same thing: a body of text, and for each region of
it the page or anchor a citation should name. A source that yields no text is
not an error here; it is a **stub**, and it says why (PRD-0001 §16).

Fetching is deliberately absent. HTML arrives already fetched, from the surface
that the Candidate was browsing with — the server does not follow a URL a user
supplied, and no module outside `metering` opens a socket (SPEC-0005).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass(frozen=True, slots=True)
class Page:
    """A region of the extracted text, and what a citation calls it."""

    number: int
    char_start: int
    char_end: int
    anchor: str = ""


@dataclass(frozen=True, slots=True)
class Figure:
    """A picture lifted out of a Source, and where on the page it was.

    Carries the same locator vocabulary as a chunk because it becomes one: a
    figure is a chunk whose payload is pixels (ADR-0017). `data` is always PNG,
    whatever the PDF stored, so one decoder serves every source.
    """

    page: int
    index: int
    data: bytes
    width: int
    height: int
    media_type: str = "image/png"

    @property
    def pixels(self) -> int:
        return self.width * self.height


@dataclass(frozen=True, slots=True)
class Extracted:
    text: str
    pages: tuple[Page, ...] = field(default_factory=tuple)
    stub_reason: str | None = None

    @property
    def is_stub(self) -> bool:
        return bool(self.stub_reason) or not self.text.strip()

    def page_of(self, char_start: int) -> int:
        for page in self.pages:
            if page.char_start <= char_start < page.char_end:
                return page.number
        return self.pages[-1].number if self.pages else 1

    def anchor_of(self, char_start: int) -> str:
        for page in self.pages:
            if page.char_start <= char_start < page.char_end:
                return page.anchor
        return ""


def extract_text(text: str) -> Extracted:
    """Markdown and plain text arrive already extracted."""
    if not text.strip():
        return Extracted("", (), "no extractable text")
    return Extracted(text, (Page(1, 0, len(text)),))


def extract_pdf(data: bytes) -> Extracted:
    """Text per page, so a citation can say `source · p.14`.

    A PDF of scanned images extracts to nothing. That is the common case for
    lecture handouts and it is a state, not a failure.
    """
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError:  # pragma: no cover - dependency is declared
        return Extracted("", (), "pdf extraction is unavailable on this deployment")

    try:
        reader = PdfReader(io.BytesIO(data))
        parts: list[str] = []
        pages: list[Page] = []
        cursor = 0
        for number, page in enumerate(reader.pages, 1):
            body = (page.extract_text() or "").strip()
            if not body:
                continue
            block = body + "\n\n"
            parts.append(block)
            pages.append(Page(number, cursor, cursor + len(block)))
            cursor += len(block)
    except Exception as exc:  # a malformed file is a stub, not a 500
        return Extracted("", (), f"could not be read as a PDF: {type(exc).__name__}")

    if not parts:
        return Extracted("", (), "no extractable text (the pages carry images only)")
    return Extracted("".join(parts), tuple(pages))


class _Reader(HTMLParser):
    """Main content, with the heading each passage sits under.

    Deliberately small: the parts of a page that are navigation, script or style
    are dropped by name, and what remains is the prose. A page whose prose is
    written by JavaScript leaves nothing behind, which is exactly the stub case.
    """

    SKIP = {"script", "style", "nav", "header", "footer", "aside", "noscript",
            "form", "svg", "button"}
    BLOCK = {"p", "div", "li", "section", "article", "tr", "br", "pre", "blockquote"}
    HEADING = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.regions: list[Page] = []
        self._skip_depth = 0
        self._in_heading = False
        self._heading = ""
        self._length = 0
        self._region_start = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag in self.HEADING:
            self._close_region()
            self._in_heading = True
            self._heading = ""
        elif tag in self.BLOCK:
            self._emit("\n\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self.HEADING:
            self._in_heading = False
            self._emit("\n\n")

    def handle_data(self, data):
        if self._skip_depth:
            return
        body = re.sub(r"\s+", " ", data)
        if not body.strip():
            return
        if self._in_heading:
            self._heading += body.strip()
        self._emit(body)

    def _emit(self, body: str) -> None:
        self.parts.append(body)
        self._length += len(body)

    def _close_region(self) -> None:
        if self._length > self._region_start:
            self.regions.append(
                Page(1, self._region_start, self._length, self._heading)
            )
            self._region_start = self._length

    def finish(self) -> tuple[str, tuple[Page, ...]]:
        self._close_region()
        text = re.sub(r"\n{3,}", "\n\n", "".join(self.parts)).strip()
        return text, tuple(self.regions)


def extract_html(html: str, *, url: str = "") -> Extracted:
    """A page the Candidate was reading, with its headings kept as anchors."""
    reader = _Reader()
    try:
        reader.feed(html)
    except Exception as exc:
        return Extracted("", (), f"could not be read as a page: {type(exc).__name__}")
    text, regions = reader.finish()
    if not text.strip():
        return Extracted(
            "", (), "no extractable text (the page's content is written by script)"
        )
    # Regions were measured against the untrimmed buffer; anchor lookup only
    # needs their order, so they are re-based onto the trimmed text.
    rebased = _rebase(regions, len(text))
    return Extracted(text, rebased or (Page(1, 0, len(text)),))


def _rebase(regions: tuple[Page, ...], length: int) -> tuple[Page, ...]:
    if not regions:
        return ()
    span = regions[-1].char_end or 1
    out = []
    for region in regions:
        start = min(length, region.char_start * length // span)
        end = min(length, max(start + 1, region.char_end * length // span))
        out.append(Page(1, start, end, region.anchor))
    return tuple(out)


#: Below this, a "figure" is a rule, a bullet or a logo fragment. Embedding it
#: costs a forward pass and buys a vector of nothing.
MIN_FIGURE_PIXELS = 64 * 64

#: A deck of scanned pages can carry thousands of image XObjects. Ingest is
#: bounded rather than open-ended, and says so when it stops.
MAX_FIGURES_PER_SOURCE = 64


def extract_figures(
    data: bytes,
    *,
    media_type: str = "application/pdf",
    max_figures: int = MAX_FIGURES_PER_SOURCE,
    min_pixels: int = MIN_FIGURE_PIXELS,
) -> tuple[Figure, ...]:
    """The pictures in a Source, normalised to PNG, in page then position order.

    Never raises: a Source whose images cannot be read is a Source with no
    figures, exactly as a Source with no text is a stub rather than a failure.
    Text extraction is the product; figures are an addition to it, and an
    addition must not be able to take the product down.
    """
    if media_type != "application/pdf" or not data:
        return ()
    try:
        from pypdf import PdfReader
        from PIL import Image, ImageOps
    except ModuleNotFoundError:
        return ()

    out: list[Figure] = []
    try:
        reader = PdfReader(io.BytesIO(data))
        for number, page in enumerate(reader.pages, 1):
            for index, embedded in enumerate(page.images):
                if len(out) >= max_figures:
                    return tuple(out)
                try:
                    image = Image.open(io.BytesIO(embedded.data))
                    image.load()
                    image = ImageOps.exif_transpose(image).convert("RGB")
                except Exception:
                    continue
                if image.width * image.height < min_pixels:
                    continue
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                out.append(
                    Figure(
                        page=number,
                        index=index,
                        data=buffer.getvalue(),
                        width=image.width,
                        height=image.height,
                    )
                )
    except Exception:
        return tuple(out)
    return tuple(out)


def extract(
    *, text: str = "", data: bytes | None = None, media_type: str = "text/markdown",
    url: str = "",
) -> Extracted:
    """One door for every source type the Adapter accepts."""
    if media_type == "application/pdf":
        return extract_pdf(data or b"")
    if media_type in {"text/html", "application/xhtml+xml"}:
        return extract_html(text, url=url)
    return extract_text(text)
