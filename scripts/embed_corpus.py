#!/usr/bin/env python
"""Embed the shipped Corpus and precompute Related Topics.

Run after a scrape, or after changing the embedding model. Nothing else needs
it: the artifact is read at runtime and never written there, so a deployment
serves Related Topics without ever loading a model.

    python scripts/embed_corpus.py --provider siglip

What this does **not** do is the point of it. It never clusters, never labels,
never mints a `topic_id`. The shipped Corpus arrives with its Topics already
drawn, and those ids are the join key for every row of Evidence and Topic
Confidence — so the build reads structure and adds vectors beside it (ISSUE-0029).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

DEFAULT_ARTIFACT = ROOT / "data" / "corpus-index.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=str(ROOT / "data" / "corpus.json"))
    parser.add_argument("--out", default=str(DEFAULT_ARTIFACT))
    parser.add_argument(
        "--provider",
        default=os.environ.get("EMBEDDING_PROVIDER") or "siglip",
        help="hashing is a lexical stand-in and will not answer 'what relates "
             "to this'; it exists so the pipeline is testable",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--force",
        action="store_true",
        help="rebuild even when the Corpus and model are unchanged — what you "
             "want after changing how the index is built",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether the artifact is current, and when it is not, "
             "which of the Corpus and the model moved — they are different "
             "problems. Writes nothing.",
    )
    args = parser.parse_args()

    from interviewer.corpus.adapters.cortex import ingest
    from interviewer.corpus.index import build, fingerprint
    from interviewer.corpus.related import RelatedTopics, load, save
    from interviewer.embeddings import make_embedder

    corpus = ingest(Path(args.corpus))
    out = Path(args.out)
    current = fingerprint(corpus)
    topics = list(corpus.topics)
    print(f"corpus: {len(topics)} Topics, fingerprint {current[:16]}")

    existing = load(out)
    if args.check:
        # The same reading the operator console shows, computed the same way.
        # Two implementations of "is this stale" would eventually disagree, and
        # the one an operator trusts is whichever they read last.
        reading = RelatedTopics(
            existing, corpus,
            embedding_model=os.environ.get("EMBEDDING_MODEL_NAME") or None,
        ).staleness.reading()
        if reading["state"] == "absent":
            print("no artifact — run without --check to build one")
            return 1
        print(f"artifact: {existing.embedding_model}, "
              f"fingerprint {existing.fingerprint[:16]}, "
              f"built {existing.built_at or 'at an unrecorded time'}")
        if reading["state"] == "fresh":
            print("current")
            return 0
        # Which of the two moved, because they are different problems: a
        # re-scrape needs a rebuild, a model swap needs a rebuild *and* a
        # decision about what the deployment is running.
        print(f"STALE — {reading['reason']}")
        print("neighbours are still being served"
              if reading["serving"] else
              "neighbours are not being served until this is rebuilt")
        return 1

    embedder = make_embedder({**os.environ, "EMBEDDING_PROVIDER": args.provider})
    model = getattr(embedder, "model_name", "unknown")
    if not args.force and existing is not None \
            and existing.fingerprint == current \
            and existing.embedding_model == model:
        # Re-running against an unchanged Corpus is a no-op that says so,
        # rather than a several-minute job that looks like work.
        print(f"already current for {model} — nothing to do")
        return 0

    warm = getattr(embedder, "warm", None)
    if callable(warm):
        started = time.monotonic()
        warm()
        print(f"model ready in {time.monotonic() - started:.1f}s")

    started = time.monotonic()
    # The clock is read here and passed in, never inside the build: the artifact
    # is reviewed in a diff, so everything describing content stays deterministic
    # and only the stamp differs between two builds of one Corpus.
    index = build(
        corpus, embedder, top_k=args.top_k,
        built_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )
    print(f"embedded {index.topic_count} Topics in "
          f"{time.monotonic() - started:.1f}s with {index.embedding_model}")

    missing = [t.id for t in topics if t.id not in index.centroids]
    if missing:
        # Not a failure: a Topic of pure references has nothing to embed. Worth
        # saying out loud, because silently covering 60 of 71 Topics would look
        # exactly like covering all of them.
        print(f"{len(missing)} Topic(s) carried no text and have no neighbours")

    save(index, out)
    try:
        shown = out.relative_to(ROOT)
    except ValueError:
        shown = out
    print(f"wrote {shown} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
