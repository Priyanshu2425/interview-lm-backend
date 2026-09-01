#!/usr/bin/env python
"""Re-embed every notebook with the configured provider, and report what it cost.

There is one store and it is `content.notebook_chunk` in Postgres. The old
`data/corpus-index.json` artifact is gone (ADR-0021): a Topic's centroid is
written beside its chunks, so re-embedding a notebook is the whole migration,
and Related Topics reads the new centroids the moment they land.

Usage:

    export OPENROUTER_API_KEY=...
    python backend/scripts/reset_embeddings.py --provider openrouter

Nothing is spent without `--yes`. A dry run prints the token count and the
estimated spend and stops, which is the number you probably wanted anyway.

Cost is computed from our own token counts and our own arithmetic, as ADR-0014
requires of every figure this product bills on. The provider's dashboard is the
authority; this is the number we would have charged.

The database comes from DATABASE_URL in the environment; see the root .env's
comment about INTERVIEW_LM_DATABASE_URL before pointing anything at Neon.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def approx_tokens(text: str) -> int:
    """Four characters to a token — the estimate the rest of the product bills on."""
    return len(text) // 4


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider", default=os.environ.get("EMBEDDING_PROVIDER") or "openrouter"
    )
    parser.add_argument("--model", default=os.environ.get("EMBEDDING_MODEL") or "")
    parser.add_argument("--yes", action="store_true", help="actually spend money")
    args = parser.parse_args()

    env = {**os.environ, "EMBEDDING_PROVIDER": args.provider}
    if args.model:
        env["EMBEDDING_MODEL"] = args.model
    # A paid provider is refused unless the deployment says so out loud. This is
    # a script for spending money on purpose, so it says so.
    env.setdefault("EMBEDDING_ALLOW_PAID", "1")

    from interviewer.db.engine import create_content, make_engine
    from interviewer.adapters.s3 import S3ObjectStore
    from interviewer.embeddings import make_embedder
    from interviewer.repository.notebooks import NotebookStore
    from interviewer.service.notebooks import NotebookService

    embedder = make_embedder(env)
    price = float(getattr(embedder, "dollars_per_million", 0.0))
    print(f"provider : {embedder.model_name}")
    print(
        f"price    : ${price}/M tokens"
        if price
        else "price    : unknown — cost cannot be estimated"
    )

    engine = make_engine()
    create_content(engine)
    store = NotebookStore(engine)
    notebook_ids = store.all_notebook_ids()
    if not notebook_ids:
        print("\nno notebooks in this database — nothing to do.")
        return 0

    total = 0
    figures = 0
    for notebook_id in notebook_ids:
        record = store.get(notebook_id)
        rows = store.chunks_of(notebook_id, modality="text")
        tokens = sum(approx_tokens(r["text"]) for r in rows)
        total += tokens
        print(
            f"{notebook_id} ({record.title if record else '?'}): "
            f"{len(rows)} text chunks, ~{tokens:,} tokens"
        )
        figures += sum(len(store.figures_of(nb)) for nb in [notebook_id])
    if figures:
        print(
            f"           {figures} figure(s) across all notebooks"
            + (
                " — this provider has no image tower, so they keep the "
                "vectors they have"
                if not getattr(embedder, "supports_images", False)
                else ""
            )
        )

    estimate = total / 1_000_000 * price
    print(f"\ntotal    : ~{total:,} tokens" + (f"  ≈ ${estimate:.4f}" if price else ""))

    if not args.yes:
        print("\ndry run — nothing embedded, nothing spent, nothing reset.")
        print("re-run with --yes to do it for real.")
        return 0

    warm = getattr(embedder, "warm", None)
    if callable(warm):
        warm()

    service = NotebookService(
        engine,
        embedder=embedder,
        objects=S3ObjectStore.from_env(env),
    )

    started = time.monotonic()
    for notebook_id in notebook_ids:
        # Memberships are stored data and are carried across untouched: a
        # change of embedding model must never redraw a Topic boundary
        # (ADR-0015). This replaces vectors and nothing else.
        service.re_embed(notebook_id, embedding_model=embedder.model_name)
        print(f"  {notebook_id}: re-embedded into {embedder.model_name}")

    elapsed = time.monotonic() - started
    health = getattr(embedder, "health", lambda: {})()
    print(f"\ndone in {elapsed:.1f}s")
    print(f"calls    : {health.get('calls')}  failures: {health.get('failures')}")
    print(f"tokens   : ~{total:,} (our count, ADR-0014)")
    if price:
        print(
            f"cost     : ≈ ${estimate:.4f}  "
            f"= {int(-(-total * price * 100 // 1_000_000))} Credits"
        )
        print(
            "\nthe authority is your OpenRouter dashboard; this is the number "
            "we would have billed."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
