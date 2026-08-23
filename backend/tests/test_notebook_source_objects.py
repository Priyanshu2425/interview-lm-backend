"""ISSUE-0033 — the document outlives its upload.

A PDF used to be read once and thrown away: `notebook_source.text` kept what
extraction produced and the bytes were kept nowhere. That is already thin — a
re-ingest cannot re-extract, a better extractor cannot be applied to old
material, and a citation cannot show the page it came from — and it becomes
untenable when the Corpus *is* the documents.

The ordering is the part worth testing rather than assuming. Bytes are stored
**before** the row is written, the same way ADR-0017 already fixed it for
figures: a row without an object is a citation pointing at nothing, an object
without a row is unreferenced bytes a sweep can find. One is a broken product,
the other is a bill.
"""

from __future__ import annotations

import pytest
from conftest import signed_in_client

from interviewer.embeddings.errors import EmbeddingUnavailable

FIGURE_PAGES = [
    "Attention weights are a softmax over scaled dot products, and the scaling "
    "is what keeps the gradient from vanishing as the dimension grows. " * 6,
    "A convolution shares one kernel across every position, which is what makes "
    "it cheap and what makes it translation equivariant. " * 6,
]


@pytest.fixture()
def store(tmp_path):
    from interviewer.embeddings.artifacts import LocalObjectStore

    return LocalObjectStore(tmp_path)


@pytest.fixture()
def service(content_db, counting, store):
    from interviewer.notebooks import NotebookService

    return NotebookService(content_db, embedder=counting, objects=store)


def _notebook(service, notebook_id="nb-obj", candidate="cand-obj"):
    service.create(notebook_id, candidate, "Notes")
    return notebook_id


def _upload(service, notebook_id, *, source_id, title, data,
            media_type="text/markdown"):
    """A file as the upload route frames one: bytes, plus text for anything
    that is not a PDF. Kept here so these tests exercise the same call the
    surface makes rather than a shape only a test uses."""
    return service.add_source(
        notebook_id,
        source_id=source_id,
        title=title,
        data=data,
        text="" if media_type == "application/pdf" else data.decode(),
        media_type=media_type,
    )


# -- the bytes are kept ------------------------------------------------------

def test_uploaded_bytes_are_stored_and_the_source_points_at_them(service, store):
    notebook_id = _notebook(service)
    added = _upload(
        service, notebook_id, source_id="src-1", title="Notes.md",
        data=b"# Attention\n\nSoftmax over scaled dot products.\n" * 20,
    )
    record = service.store.get(notebook_id)
    source = next(s for s in record.sources if s.source_id == added.source_id)
    assert source.object_key
    assert store.get(source.object_key).startswith(b"# Attention")


def test_the_object_key_is_the_content_hash(service):
    """So the same document twice is stored once, and a re-upload costs nothing."""
    notebook_id = _notebook(service)
    data = b"# Attention\n\nSoftmax over scaled dot products.\n" * 20
    _upload(service, notebook_id, source_id="src-1", title="A.md", data=data)
    source = service.store.get(notebook_id).sources[0]
    from interviewer.corpus.adapters.notebook.sources import digest

    assert digest(data.decode()) in source.object_key or _hash_of(data) in source.object_key


def _hash_of(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def test_the_same_document_twice_is_stored_once(service, store, tmp_path):
    notebook_id = _notebook(service)
    data = b"# Attention\n\nSoftmax over scaled dot products.\n" * 20
    _upload(service, notebook_id, source_id="src-1", title="A.md", data=data)
    _upload(service, notebook_id, source_id="src-2", title="A again.md", data=data)
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert len(files) == 1
    assert len(service.store.get(notebook_id).sources) == 1


def test_a_pasted_note_is_stored_the_same_way(service, store, real_notes):
    """The rule is *what arrived is kept*, whatever shape it arrived in.

    A note pasted into a box is a document too, and a re-ingest of one has to
    re-extract from the same place a PDF's does — or `text` is still the only
    copy for half the Sources and the guarantee is half a guarantee.
    """
    notebook_id = _notebook(service)
    service.add_source(notebook_id, source_id="src-1", title="Pasted", text=real_notes)
    source = service.store.get(notebook_id).sources[0]
    assert source.object_key
    assert store.get(source.object_key).decode() == real_notes


def test_media_type_and_byte_length_are_recorded(service):
    notebook_id = _notebook(service)
    data = b"# Attention\n\nSoftmax over scaled dot products.\n" * 20
    _upload(service, notebook_id, source_id="src-1", title="A.md", data=data)
    source = service.store.get(notebook_id).sources[0]
    assert source.media_type == "text/markdown"
    assert source.byte_length == len(data)


def test_a_stub_keeps_its_bytes_too(service, store):
    """A scan is exactly the document a better extractor should be tried on."""
    from pdf_fixtures import scanned_pdf

    notebook_id = _notebook(service)
    data = scanned_pdf()
    added = _upload(
        service, notebook_id, source_id="src-1", title="Scan.pdf", data=data,
        media_type="application/pdf",
    )
    assert added.state == "stub"
    source = service.store.get(notebook_id).sources[0]
    assert source.object_key
    assert store.get(source.object_key) == data


# -- ordering ----------------------------------------------------------------

def test_the_object_is_written_before_the_row(
    content_db, counting, tmp_path, monkeypatch
):
    """A row pointing at bytes that are not there is the failure to prevent."""
    from interviewer.embeddings.artifacts import LocalObjectStore
    from interviewer.notebooks import NotebookService, NotebookStore

    seen: list[str] = []

    class Watching(LocalObjectStore):
        def put(self, key, data, media_type="application/octet-stream"):
            seen.append("object")
            return super().put(key, data, media_type)

    store = Watching(tmp_path)
    service = NotebookService(content_db, embedder=counting, objects=store)
    original = NotebookStore.create_source

    def watched(self, **kw):
        seen.append("row")
        return original(self, **kw)

    monkeypatch.setattr(NotebookStore, "create_source", watched)
    service.create("nb-order", "cand-order", "Notes")
    _upload(
        service, "nb-order", source_id="src-1", title="A.md",
        data=b"# Attention\n\nSoftmax over scaled dot products.\n" * 20,
    )
    assert seen[0] == "object"
    assert "row" in seen


def test_a_deployment_without_an_object_store_still_ingests(content_db, counting):
    """Storage is an addition, not a precondition. Nothing regresses without it."""
    from interviewer.notebooks import NotebookService

    service = NotebookService(content_db, embedder=counting, objects=None)
    service.create("nb-none", "cand-none", "Notes")
    added = _upload(
        service, "nb-none", source_id="src-1", title="A.md",
        data=b"# Attention\n\nSoftmax over scaled dot products.\n" * 20,
    )
    assert added.state == "ready"
    assert service.store.get("nb-none").sources[0].object_key is None


# -- re-ingest reads the object ---------------------------------------------

def test_re_ingest_re_extracts_from_the_stored_object(service, store):
    """Not from the text column, which is a cache of one extractor's opinion."""
    notebook_id = _notebook(service)
    _upload(
        service, notebook_id, source_id="src-1", title="A.md",
        data=b"# Attention\n\nSoftmax over scaled dot products.\n" * 20,
    )
    source = service.store.get(notebook_id).sources[0]
    # The bytes move on; the row's cached text does not.
    store.put(source.object_key, b"# Attention\n\nRewritten entirely.\n" * 20,
              "text/markdown")
    result = service.re_extract(notebook_id, source.source_id)
    assert result is not None
    sources = service.store.sources_of(notebook_id)
    assert "Rewritten entirely" in sources[0].text


def test_a_source_whose_object_is_missing_reports_a_named_failure(service, store):
    from interviewer.notebooks import SourceBytesMissing

    notebook_id = _notebook(service)
    _upload(
        service, notebook_id, source_id="src-1", title="A.md",
        data=b"# Attention\n\nSoftmax over scaled dot products.\n" * 20,
    )
    source = service.store.get(notebook_id).sources[0]
    from pathlib import Path

    Path(store.root / source.object_key).unlink()
    with pytest.raises(SourceBytesMissing) as raised:
        service.re_extract(notebook_id, source.source_id)
    assert raised.value.code == "source_bytes_missing"


def test_a_source_stored_before_this_slice_says_so_rather_than_guessing(service):
    """No object key is a different state from a missing object."""
    from interviewer.notebooks import SourceBytesMissing

    notebook_id = _notebook(service)
    service.add_source(notebook_id, source_id="src-1", title="A.md", text="short")
    import sqlalchemy as sa

    from interviewer.db.content import notebook_source

    with service.store._engine.begin() as c:  # noqa: SLF001 - fabricating an old row
        c.execute(
            sa.update(notebook_source)
            .where(notebook_source.c.source_id == "src-1")
            .values(object_key=None)
        )
    with pytest.raises(SourceBytesMissing):
        service.re_extract(notebook_id, "src-1")


# -- deletion ----------------------------------------------------------------

def test_deleting_a_corpus_deletes_its_objects_in_the_same_call_path(
    service, store, tmp_path
):
    """`CASCADE` empties the schema and has never heard of the bucket."""
    notebook_id = _notebook(service)
    _upload(
        service, notebook_id, source_id="src-1", title="A.md",
        data=b"# Attention\n\nSoftmax over scaled dot products.\n" * 20,
    )
    assert [p for p in tmp_path.rglob("*") if p.is_file()]
    service.delete(notebook_id)
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


# -- the figure path is untouched -------------------------------------------

def test_figures_still_land_under_their_own_key(content_db, seeing, tmp_path):
    """Sources and figures share a bucket and must not share a key."""
    from interviewer.embeddings.artifacts import LocalObjectStore
    from interviewer.notebooks import NotebookService
    from pdf_fixtures import image_pdf

    store = LocalObjectStore(tmp_path)
    service = NotebookService(
        content_db, embedder=seeing, objects=store, images=True
    )
    service.create("nb-fig", "cand-fig", "Notes")
    _upload(
        service, "nb-fig", source_id="src-1", title="With a picture.pdf",
        data=image_pdf(FIGURE_PAGES, figures_per_page=1),
        media_type="application/pdf",
    )
    keys = [str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file()]
    assert any("/figures/" in k for k in keys)
    assert any("/sources/" in k for k in keys)


def test_a_missing_object_raises_the_stores_own_error_underneath(store):
    with pytest.raises(EmbeddingUnavailable):
        store.get("notebooks/nb-x/sources/deadbeef.bin")


# -- a store that cannot be written to ---------------------------------------

def test_an_upload_is_refused_rather_than_half_kept(content_db, counting):
    """ISSUE-0033's ordering, read forwards.

    Bytes are stored before the row so that a row never points at an object
    that is not there. If the store cannot be written to, the honest answer is
    to refuse the upload — falling back to local disk would accept a document
    this deployment cannot keep, and the Candidate would find out weeks later
    when a retry asked for it.
    """
    from interviewer.embeddings.errors import EmbeddingUnavailable
    from interviewer.notebooks import DocumentStoreUnavailable, NotebookService

    class Unreachable:
        def source_key_for(self, notebook_id, content_hash, suffix="bin"):
            return f"notebooks/{notebook_id}/sources/{content_hash}.{suffix}"

        def put(self, key, data, media_type="application/octet-stream"):
            raise EmbeddingUnavailable("the bucket is not there")

    service = NotebookService(content_db, embedder=counting, objects=Unreachable())
    service.create("nb-nostore", "cand-nostore", "Notes")
    with pytest.raises(DocumentStoreUnavailable) as raised:
        service.upload_source(
            "nb-nostore", source_id="src-1", title="A.md", text="# Notes\n\n" + "x " * 200
        )
    assert raised.value.code == "document_store_unavailable"
    # Nothing was written: no Source row to point at bytes that are not there.
    assert service.store.get("nb-nostore").sources == ()


def test_a_deployment_with_no_bucket_is_not_the_same_as_one_it_cannot_reach(
    content_db, counting
):
    """No bucket keeps documents on disk and says so by having none configured."""
    from interviewer.notebooks import NotebookService

    service = NotebookService(content_db, embedder=counting, objects=None)
    service.create("nb-nobucket", "cand-nobucket", "Notes")
    uploaded = service.upload_source(
        "nb-nobucket", source_id="src-1", title="A.md", text="# Notes\n\n" + "x " * 200
    )
    assert uploaded.state == "uploaded"
    assert service.store.get("nb-nobucket").sources[0].object_key is None


def test_the_refusal_reaches_the_surface_with_a_code(content_db, clean_db, monkeypatch):
    from fastapi.testclient import TestClient

    from interviewer.api import deps
    from interviewer.api.app import create_app
    from interviewer.embeddings.errors import EmbeddingUnavailable

    class Unreachable:
        def source_key_for(self, notebook_id, content_hash, suffix="bin"):
            return "k"

        def put(self, *a, **kw):
            raise EmbeddingUnavailable("the bucket is not there")

    deps.get_notebook_service.cache_clear()
    deps.get_object_store.cache_clear()
    monkeypatch.setattr(deps, "get_object_store", lambda: Unreachable())
    try:  # noqa: SIM105 — the caches are the thing being restored
        client = signed_in_client()
        notebook_id = client.post(
            "/v1/notebooks", json={"candidate_id": "cand-503", "title": "Notes"}
        ).json()["notebook_id"]
        response = client.post(
            f"/v1/notebooks/{notebook_id}/sources",
            json={"title": "A.md", "text": "# Notes\n\n" + "x " * 200},
        )
        assert response.status_code == 503
        assert response.json()["code"] == "document_store_unavailable"
        assert "refused rather than half-kept" in response.json()["message"]
    finally:
        deps.get_notebook_service.cache_clear()
