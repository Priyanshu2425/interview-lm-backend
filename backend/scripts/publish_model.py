#!/usr/bin/env python
"""Publish a Hugging Face checkpoint to the bucket, so a deployment never fetches it.

Run once per model per revision, by hand, from somewhere with a hub connection.
Everything afterwards reads the bucket: boots are reproducible, offline hosts
work, and nobody's ingest depends on huggingface.co being up.

    python backend/scripts/publish_model.py google/siglip2-base-patch16-224 \
        --revision <commit-sha> --bucket my-models

The revision is required and is a commit sha, not a branch. "The model" is a
commit: `main` moving is a different vector space, and a notebook embedded in
the old one needs re-embedding rather than a shrug — which is only possible if
what was used is written down. It is, in `notebook.embedding_model`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

#: Everything needed to load the model, and nothing else. Optimiser states and
#: duplicate serialisations of the same weights are the bulk of a repo.
WANTED = {
    ".json", ".txt", ".model", ".safetensors", ".jinja", ".py",
}
SKIP_PREFIXES = (".git", "README", ".cache")
MANIFEST = "manifest.json"
_BLOCK = 1024 * 1024


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def wanted(path: Path, root: Path) -> bool:
    name = path.relative_to(root).as_posix()
    if any(name.startswith(p) for p in SKIP_PREFIXES):
        return False
    return path.suffix in WANTED


def download(repo_id: str, revision: str) -> Path:
    try:
        from huggingface_hub import snapshot_download
    except ModuleNotFoundError:
        sys.exit(
            "huggingface_hub is missing: pip install -e 'backend[embeddings]'"
        )
    print(f"downloading {repo_id}@{revision[:12]} from the hub")
    return Path(snapshot_download(repo_id=repo_id, revision=revision))


def build_manifest(root: Path, repo_id: str, revision: str, dim: int) -> dict:
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not wanted(path, root):
            continue
        files.append({
            "name": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_of(path),
        })
    return {"repo_id": repo_id, "revision": revision, "dim": dim, "files": files}


def publish(args) -> int:
    root = Path(args.local) if args.local else download(args.repo_id, args.revision)
    manifest = build_manifest(root, args.repo_id, args.revision, args.dim)
    prefix = f"{args.prefix}/{args.repo_id}/{args.revision}"
    total = sum(f["size"] for f in manifest["files"])
    print(f"{len(manifest['files'])} files, {total / 1e6:.1f} MB -> "
          f"s3://{args.bucket}/{prefix}")

    if args.dry_run:
        for entry in manifest["files"]:
            print(f"  {entry['name']:<48} {entry['size']:>12,}  {entry['sha256'][:12]}")
        return 0

    # The application's client rather than a second one: it is what knows the
    # store is R2 and reads R2's credentials. A `boto3.client("s3")` built here
    # would resolve AWS's endpoint and publish the weights somewhere no
    # deployment reads from, successfully and silently.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from interviewer.embeddings.artifacts import _client

    client = _client()
    for entry in manifest["files"]:
        key = f"{prefix}/{entry['name']}"
        # Re-running is cheap on purpose: publishing is the kind of thing that
        # gets interrupted, and resuming should not re-upload gigabytes.
        if not args.force and _matches(client, args.bucket, key, entry):
            print(f"  = {entry['name']}")
            continue
        print(f"  ↑ {entry['name']} ({entry['size']:,})")
        client.upload_file(str(root / entry["name"]), args.bucket, key)

    # Written last. A manifest present means every file it names is present,
    # so a fetcher that reads it can trust what it says.
    client.put_object(
        Bucket=args.bucket,
        Key=f"{prefix}/{MANIFEST}",
        Body=json.dumps(manifest, indent=2).encode(),
        ContentType="application/json",
    )
    print(f"\npublished. set:\n  EMBEDDING_MODEL={args.repo_id}\n"
          f"  EMBEDDING_REVISION={args.revision}\n  MODEL_BUCKET={args.bucket}")
    return 0


def _matches(client, bucket: str, key: str, entry: dict) -> bool:
    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except Exception:
        return False
    if head["ContentLength"] != entry["size"]:
        return False
    return head.get("Metadata", {}).get("sha256", entry["sha256"]) == entry["sha256"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_id", help="e.g. google/siglip2-base-patch16-224")
    parser.add_argument("--revision", required=True, help="commit sha, never a branch")
    parser.add_argument("--bucket", default=os.environ.get("MODEL_BUCKET", ""))
    parser.add_argument("--prefix", default=os.environ.get("MODEL_PREFIX", "models"))
    parser.add_argument("--dim", type=int, default=768)
    parser.add_argument("--local", help="publish an already-downloaded directory")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="re-upload everything")
    args = parser.parse_args()
    if not args.bucket and not args.dry_run:
        parser.error("--bucket (or MODEL_BUCKET) is required")
    return publish(args)


if __name__ == "__main__":
    raise SystemExit(main())
