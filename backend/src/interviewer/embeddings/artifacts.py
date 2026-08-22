"""Model weights and figure bytes, in S3.

Two stores with one client. The model store is read-only at runtime and is what
lets a deployment boot without reaching huggingface.co: weights are published
once, by hand, at a pinned revision, and every process afterwards pulls the same
verified bytes. The object store holds figure images, whose lifecycle belongs to
the notebook that owns them.

Nothing here decides *when* to fetch. `ensure_local` is idempotent and cheap on
a warm cache, so callers may treat it as a lookup.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .errors import EmbeddingUnavailable

log = logging.getLogger(__name__)

MANIFEST = "manifest.json"
_CHUNK = 1024 * 1024


def _client():
    """boto3, imported here so a deployment that never uses S3 never needs it."""
    try:
        import boto3
        from botocore.config import Config
    except ModuleNotFoundError as exc:  # pragma: no cover - optional extra
        raise EmbeddingUnavailable(
            "S3 access needs the 'embeddings' extra (pip install -e backend[embeddings])"
        ) from exc
    # Its own retries, because a 1.5GB pull over a flaky link should recover
    # rather than fail a boot.
    return boto3.client(
        "s3",
        config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
    )


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Which weights, at which commit, from which bucket."""

    repo_id: str
    revision: str
    bucket: str
    prefix: str = "models"

    @property
    def key_prefix(self) -> str:
        return f"{self.prefix}/{self.repo_id}/{self.revision}"

    def cache_dir(self, root: Path) -> Path:
        return root / self.repo_id.replace("/", "--") / self.revision

    @classmethod
    def from_env(cls, env: dict | None = None) -> "ModelSpec | None":
        env = os.environ if env is None else env
        bucket = env.get("MODEL_BUCKET") or ""
        model = env.get("EMBEDDING_MODEL") or ""
        revision = env.get("EMBEDDING_REVISION") or ""
        if not (bucket and model and revision):
            return None
        return cls(
            repo_id=model,
            revision=revision,
            bucket=bucket,
            prefix=env.get("MODEL_PREFIX") or "models",
        )


def cache_root(env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(
        env.get("MODEL_CACHE_DIR") or (Path.home() / ".cache" / "cortex-models")
    ).expanduser()


def ensure_local(
    spec: ModelSpec, *, root: Path | None = None, client=None
) -> Path:
    """The weights on local disk, verified. Downloads only what is missing.

    Safe to call from several processes at once: the download happens under an
    exclusive lock on the cache directory, so four uvicorn workers starting
    together pull 1.5GB once rather than four times.
    """
    root = root or cache_root()
    target = spec.cache_dir(root)
    target.mkdir(parents=True, exist_ok=True)

    with _locked(target / ".lock"):
        client = client or _client()
        manifest = _manifest(spec, target, client)
        for entry in manifest["files"]:
            _ensure_file(spec, target, entry, client)
    return target


def _manifest(spec: ModelSpec, target: Path, client) -> dict:
    """The manifest is always re-read: it is small, and it is the source of truth."""
    local = target / MANIFEST
    key = f"{spec.key_prefix}/{MANIFEST}"
    try:
        body = client.get_object(Bucket=spec.bucket, Key=key)["Body"].read()
    except Exception as exc:
        if local.exists():
            # An offline boot on a warm cache is a working deployment, not a
            # broken one.
            log.warning("model manifest unreachable, using cached copy: %s", exc)
            return json.loads(local.read_text())
        raise EmbeddingUnavailable(
            f"cannot read s3://{spec.bucket}/{key}: {exc}"
        ) from exc
    local.write_bytes(body)
    return json.loads(body)


def _ensure_file(spec: ModelSpec, target: Path, entry: dict, client) -> None:
    path = target / entry["name"]
    if path.exists() and sha256_of(path) == entry["sha256"]:
        return
    if path.exists():
        log.warning("checksum mismatch, re-downloading %s", entry["name"])

    path.parent.mkdir(parents=True, exist_ok=True)
    # Written aside and moved into place, so a process killed mid-pull never
    # leaves a half file that looks complete to the next boot.
    part = path.with_suffix(path.suffix + ".part")
    key = f"{spec.key_prefix}/{entry['name']}"
    try:
        client.download_file(spec.bucket, key, str(part))
    except Exception as exc:
        part.unlink(missing_ok=True)
        raise EmbeddingUnavailable(
            f"cannot download s3://{spec.bucket}/{key}: {exc}"
        ) from exc

    actual = sha256_of(part)
    if actual != entry["sha256"]:
        part.unlink(missing_ok=True)
        raise EmbeddingUnavailable(
            f"{entry['name']} downloaded with sha256 {actual[:12]}, "
            f"manifest says {entry['sha256'][:12]}"
        )
    os.replace(part, path)
    log.info("fetched %s (%s bytes)", entry["name"], entry.get("size"))


def _locked(path: Path):
    """An advisory lock across processes, degrading to nothing where unavailable."""
    import contextlib

    @contextlib.contextmanager
    def guard() -> Iterator[None]:
        try:
            import fcntl
        except ModuleNotFoundError:  # pragma: no cover - not posix
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    return guard()


class S3ObjectStore:
    """Figure bytes. Content-addressed, so the same diagram is stored once.

    Deliberately not the model store: these objects belong to a notebook, and
    deleting that notebook has to be able to delete them. `CASCADE` empties the
    rows; this empties the bucket.
    """

    __slots__ = ("bucket", "prefix", "_client")

    def __init__(self, bucket: str, prefix: str = "notebooks", client=None) -> None:
        self.bucket = bucket
        self.prefix = prefix
        self._client = client

    @classmethod
    def from_env(cls, env: dict | None = None) -> "S3ObjectStore | None":
        env = os.environ if env is None else env
        bucket = env.get("CONTENT_BUCKET") or env.get("MODEL_BUCKET") or ""
        if not bucket:
            return None
        return cls(bucket, env.get("CONTENT_PREFIX") or "notebooks")

    @property
    def client(self):
        if self._client is None:
            self._client = _client()
        return self._client

    def key_for(self, notebook_id: str, content_hash: str, suffix: str = "png") -> str:
        return f"{self.prefix}/{notebook_id}/figures/{content_hash}.{suffix}"

    def source_key_for(
        self, notebook_id: str, content_hash: str, suffix: str = "bin"
    ) -> str:
        """Where the uploaded document itself lives.

        Beside the figures and never among them: the two have different
        lifetimes in the reader's head — one is the material, the other is
        something lifted out of it — and a shared prefix makes "delete the
        figures" and "delete the document" the same list.
        """
        return f"{self.prefix}/{notebook_id}/sources/{content_hash}.{suffix}"

    def put(self, key: str, data: bytes, media_type: str = "image/png") -> str:
        """Idempotent on the key, which is the content hash."""
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=media_type
        )
        return key

    def get(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as exc:
            raise EmbeddingUnavailable(
                f"cannot read s3://{self.bucket}/{key}: {exc}"
            ) from exc

    def presign(self, key: str, expires: int = 900) -> str:
        """Short-lived by default: a citation is read now, not bookmarked."""
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires,
        )

    def delete_prefix(self, notebook_id: str) -> int:
        """Everything a notebook put in the bucket, gone with the notebook."""
        prefix = f"{self.prefix}/{notebook_id}/"
        removed = 0
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if not keys:
                continue
            self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})
            removed += len(keys)
        return removed


class LocalObjectStore:
    """The same contract, on disk.

    Not a test double: a single-node deployment with no bucket is a real way to
    run this, and it keeps the S3 dependency genuinely optional.
    """

    __slots__ = ("root", "prefix")

    def __init__(self, root: Path, prefix: str = "notebooks") -> None:
        self.root = Path(root)
        self.prefix = prefix

    def key_for(self, notebook_id: str, content_hash: str, suffix: str = "png") -> str:
        return f"{self.prefix}/{notebook_id}/figures/{content_hash}.{suffix}"

    def source_key_for(
        self, notebook_id: str, content_hash: str, suffix: str = "bin"
    ) -> str:
        """Where the uploaded document itself lives.

        Beside the figures and never among them: the two have different
        lifetimes in the reader's head — one is the material, the other is
        something lifted out of it — and a shared prefix makes "delete the
        figures" and "delete the document" the same list.
        """
        return f"{self.prefix}/{notebook_id}/sources/{content_hash}.{suffix}"

    def _path(self, key: str) -> Path:
        return self.root / key

    def put(self, key: str, data: bytes, media_type: str = "image/png") -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise EmbeddingUnavailable(f"missing object {key}")
        return path.read_bytes()

    def presign(self, key: str, expires: int = 900) -> str:
        return self._path(key).as_uri()

    def delete_prefix(self, notebook_id: str) -> int:
        target = self.root / self.prefix / notebook_id
        if not target.exists():
            return 0
        count = sum(1 for _ in target.rglob("*") if _.is_file())
        shutil.rmtree(target)
        return count


def object_store(env: dict | None = None):
    """S3 where configured, local disk otherwise."""
    env = os.environ if env is None else env
    store = S3ObjectStore.from_env(env)
    if store is not None:
        return store
    return LocalObjectStore(
        cache_root(env).parent / "cortex-content",
        env.get("CONTENT_PREFIX") or "notebooks",
    )
