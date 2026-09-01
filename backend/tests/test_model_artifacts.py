"""Weights arrive whole, or they do not arrive.

A model fetched over a flaky link and loaded anyway is the worst outcome
available here: it produces vectors, they are wrong, and nothing reports a
problem. So every file is checksummed against a manifest, written aside and
moved into place, and re-fetched when it does not match.

The S3 client is hand-rolled rather than mocked with a library — it is fifteen
lines, and a fake we can make misbehave on purpose is worth more than one we
cannot.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from interviewer.adapters.s3 import (
    LocalObjectStore, ModelSpec, ensure_local, sha256_of,
)
from interviewer.service.embeddings.errors import EmbeddingUnavailable


class FakeS3:
    """Enough of boto3's surface to fetch a model, and to fail like it does."""

    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects
        self.downloads: list[str] = []
        self.corrupt: set[str] = set()
        self.unreachable = False

    def get_object(self, Bucket, Key):  # noqa: N803 - boto3's spelling
        if self.unreachable:
            raise ConnectionError("no route to host")
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": _Body(self.objects[Key])}

    def download_file(self, bucket, key, path):
        if self.unreachable:
            raise ConnectionError("no route to host")
        self.downloads.append(key)
        data = self.objects[key]
        if key in self.corrupt:
            data = data + b"tampered"
        Path(path).write_bytes(data)


class _Body:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


@pytest.fixture()
def published():
    files = {"config.json": b'{"hidden": 768}', "model.safetensors": b"WEIGHTS" * 100}
    manifest = {
        "repo_id": "google/siglip2-base-patch16-224",
        "revision": "abc123",
        "dim": 768,
        "files": [
            {"name": n, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()}
            for n, b in files.items()
        ],
    }
    prefix = "models/google/siglip2-base-patch16-224/abc123"
    objects = {f"{prefix}/{n}": b for n, b in files.items()}
    objects[f"{prefix}/manifest.json"] = json.dumps(manifest).encode()
    return FakeS3(objects)


@pytest.fixture()
def spec():
    return ModelSpec("google/siglip2-base-patch16-224", "abc123", "bucket")


def test_a_cold_cache_downloads_every_file_and_verifies_it(tmp_path, spec, published):
    target = ensure_local(spec, root=tmp_path, client=published)
    assert (target / "config.json").read_bytes() == b'{"hidden": 768}'
    assert len(published.downloads) == 2


def test_a_warm_cache_downloads_nothing(tmp_path, spec, published):
    ensure_local(spec, root=tmp_path, client=published)
    published.downloads.clear()
    ensure_local(spec, root=tmp_path, client=published)
    assert published.downloads == []


def test_a_file_that_does_not_match_the_manifest_is_fetched_again(
    tmp_path, spec, published
):
    target = ensure_local(spec, root=tmp_path, client=published)
    (target / "config.json").write_bytes(b"corrupted on disk")
    published.downloads.clear()
    ensure_local(spec, root=tmp_path, client=published)
    assert published.downloads == [
        "models/google/siglip2-base-patch16-224/abc123/config.json"
    ]


def test_a_download_that_arrives_wrong_is_refused_and_leaves_nothing_behind(
    tmp_path, spec, published
):
    published.corrupt = {"models/google/siglip2-base-patch16-224/abc123/config.json"}
    with pytest.raises(EmbeddingUnavailable) as caught:
        ensure_local(spec, root=tmp_path, client=published)
    assert "sha256" in str(caught.value)
    # No `.part` masquerading as a complete file for the next boot to load.
    assert not list(spec.cache_dir(tmp_path).glob("*.part"))
    assert not (spec.cache_dir(tmp_path) / "config.json").exists()


def test_an_unreachable_bucket_on_a_cold_cache_is_a_named_failure(
    tmp_path, spec, published
):
    published.unreachable = True
    with pytest.raises(EmbeddingUnavailable):
        ensure_local(spec, root=tmp_path, client=published)


def test_an_unreachable_bucket_on_a_warm_cache_still_boots(tmp_path, spec, published):
    """An offline host with the weights already on disk is a working deployment."""
    ensure_local(spec, root=tmp_path, client=published)
    published.unreachable = True
    assert ensure_local(spec, root=tmp_path, client=published).exists()


def test_the_cache_path_separates_revisions(tmp_path, spec):
    other = ModelSpec(spec.repo_id, "def456", spec.bucket)
    assert spec.cache_dir(tmp_path) != other.cache_dir(tmp_path)


def test_object_keys_are_content_addressed(tmp_path):
    store = LocalObjectStore(tmp_path)
    assert store.key_for("nb1", "hash1") == store.key_for("nb1", "hash1")
    assert store.key_for("nb1", "hash1") != store.key_for("nb1", "hash2")


def test_deleting_a_notebook_empties_its_prefix(tmp_path):
    store = LocalObjectStore(tmp_path)
    store.put(store.key_for("nb1", "a"), b"one")
    store.put(store.key_for("nb1", "b"), b"two")
    store.put(store.key_for("nb2", "c"), b"other notebook")
    assert store.delete_prefix("nb1") == 2
    assert store.get(store.key_for("nb2", "c")) == b"other notebook"


def test_sha256_of_reads_large_files_in_blocks(tmp_path):
    path = tmp_path / "big"
    path.write_bytes(b"x" * (3 * 1024 * 1024))
    assert sha256_of(path) == hashlib.sha256(b"x" * (3 * 1024 * 1024)).hexdigest()
