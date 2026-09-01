"""Model weights, uploaded documents and figure bytes, in Cloudflare R2.

Two stores with one client. The model store is read-only at runtime and is what
lets a deployment boot without reaching huggingface.co: weights are published
once, by hand, at a pinned revision, and every process afterwards pulls the same
verified bytes. The object store holds the documents a Candidate uploaded and
the figures lifted out of them, whose lifecycle belongs to the notebook that
owns them.

The document half arrived with ISSUE-0033 and changed what this module is for.
It used to hold things that could be rebuilt — a figure is an addition to a
Module, and losing one costs a picture. It now holds the only copy of what a
Candidate handed over, which is why a deployment that configures a bucket must
be able to reach it before it accepts an upload.

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

from interviewer.service.embeddings.errors import EmbeddingUnavailable

log = logging.getLogger(__name__)

MANIFEST = "manifest.json"
_CHUNK = 1024 * 1024


# R2 signs every request for one region, and it is not a choice a deployment
# makes: no other value works. A variable here would be a variable with one
# legal setting, which is a way of inviting somebody to set a second.
R2_REGION = "auto"


def _client(env: dict | None = None):
    """boto3, imported here so a deployment that never uses a bucket never needs it.

    The store is Cloudflare R2. boto3 is how it is spoken to — R2 serves the S3
    API and SigV4 is the only way in — but nothing about this deployment runs on
    AWS, and no name here says otherwise. The endpoint and the two credentials
    are R2's, read under R2's names and passed explicitly rather than picked up
    from whatever the ambient AWS environment of the host happens to hold.
    """
    env = os.environ if env is None else env
    try:
        import boto3
        from botocore.config import Config
    except ModuleNotFoundError as exc:  # pragma: no cover - optional extra
        # Not the `embeddings` extra any more: boto3 is runtime, because the
        # upload path needs it (ISSUE-0033). Reaching here means the image was
        # built without its own requirements.txt.
        raise EmbeddingUnavailable(
            "bucket access needs boto3, which backend/requirements.txt pins. "
            "This process was installed without it."
        ) from exc

    endpoint = endpoint_url(env)
    if not endpoint:
        # Reached only with a bucket configured, so this is a half-configured
        # deployment rather than a deployment without one. Refusing beats
        # resolving AWS's endpoint from a region and failing there: the bucket
        # named in CONTENT_BUCKET does not exist on AWS, and the error that
        # comes back from asking says nothing about why.
        raise EmbeddingUnavailable(
            "a bucket is configured and R2_ENDPOINT_URL is not. The store is "
            "Cloudflare R2: set it to https://<account-id>.r2.cloudflarestorage.com, "
            "or unset the bucket to keep objects on local disk."
        )

    key_id = (env.get("R2_ACCESS_KEY_ID") or "").strip()
    secret = (env.get("R2_SECRET_ACCESS_KEY") or "").strip()
    if not (key_id and secret):
        # Said once, here, naming both. The alternative is NoCredentialsError
        # raised somewhere inside a Candidate's upload, which names neither and
        # reads like the bucket is down.
        raise EmbeddingUnavailable(
            "R2_ENDPOINT_URL is set and R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY "
            "are not. Those two are the id and secret of an R2 API token with "
            "Object Read & Write on the bucket."
        )

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=R2_REGION,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        config=Config(
            # Its own retries, because a 1.5GB pull over a flaky link should
            # recover rather than fail a boot.
            retries={"max_attempts": 5, "mode": "adaptive"},
            # boto3 1.36 began attaching a CRC32 trailer to every upload, which
            # is `aws-chunked` on the wire and is the one place stores serving
            # the S3 API diverge from S3 itself. Ask for a checksum only where
            # the API requires one: every object here is addressed by the
            # sha256 of its own bytes, so the integrity claim is made by the
            # layer that checks it rather than by a transport header.
            request_checksum_calculation="when_required",
        ),
    )


def endpoint_url(env: dict | None = None) -> str | None:
    """Where R2 serves the S3 API: https://<account-id>.r2.cloudflarestorage.com.

    The account id is on the R2 page of the Cloudflare dashboard. A deployment
    with no bucket never asks: `object_store` hands back the local disk and no
    client is ever built.
    """
    env = os.environ if env is None else env
    return (env.get("R2_ENDPOINT_URL") or "").strip() or None


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
        env.get("MODEL_CACHE_DIR") or (Path.home() / ".cache" / "interview-lm-models")
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
        cache_root(env).parent / "interview-lm-content",
        env.get("CONTENT_PREFIX") or "notebooks",
    )
