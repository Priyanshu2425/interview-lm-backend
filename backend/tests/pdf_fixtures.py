"""Real PDFs, built here rather than committed as binaries.

A text PDF with known page breaks and a page-image PDF with no text at all are
the two cases ISSUE-0023 turns on, and a fixture that only pretends to be a PDF
would not exercise the extractor that has to tell them apart.
"""

from __future__ import annotations

import io


def text_pdf(pages: list[str]) -> bytes:
    """A minimal, valid PDF carrying one line of text per page."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids: list[int] = []
    content_ids: list[int] = []
    for body in pages:
        escaped = body.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")
        content_ids.append(
            add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
                + stream + b"\nendstream")
        )
    pages_id = len(objects) + len(pages) + 1
    for content_id in content_ids:
        page_ids.append(
            add(
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font} 0 R >> >> "
                f"/Contents {content_id} 0 R >>".encode()
            )
        )
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    add(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode())
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    start = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\n"
        f"startxref\n{start}\n%%EOF\n".encode()
    )
    return out.getvalue()


def scanned_pdf(page_count: int = 3) -> bytes:
    """Pages carrying no text operators — what a scan of a handout produces."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def image_pdf(pages: list[str], figures_per_page: int = 1) -> bytes:
    """A PDF whose pages carry text *and* embedded raster images.

    Pillow writes the images as real page content, and the text pages are
    overlaid on top, so `page.images` finds genuine XObjects and the text
    extractor finds genuine text. A fixture that only looked like an image
    would exercise neither half of the figure lane.
    """
    import pypdf
    from PIL import Image, ImageDraw
    from pypdf import PdfWriter

    canvases = []
    for index, _ in enumerate(pages):
        # Each figure is visually distinct, so two of them cannot be told apart
        # by accident.
        sheet = Image.new("RGB", (612, 792), (255, 255, 255))
        draw = ImageDraw.Draw(sheet)
        for n in range(figures_per_page):
            box = [60 + 200 * n, 300, 220 + 200 * n, 420]
            draw.rectangle(box, fill=(20 + 60 * index, 40 + 50 * n, 200))
            draw.ellipse([b + 20 for b in box], fill=(255, 220 - 40 * n, 0))
        canvases.append(sheet)

    buffer = io.BytesIO()
    canvases[0].save(
        buffer, format="PDF", save_all=True, append_images=canvases[1:]
    )
    overlay = pypdf.PdfReader(io.BytesIO(text_pdf(pages)))
    # Cloned into the writer before anything is merged: pypdf 7 removes the
    # unattached-page path, and this project treats a DeprecationWarning as a
    # build failure.
    writer = PdfWriter(clone_from=io.BytesIO(buffer.getvalue()))
    for image_page, text_page in zip(writer.pages, overlay.pages):
        image_page.merge_page(text_page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
