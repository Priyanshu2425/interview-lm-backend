#!/usr/bin/env python
"""Re-embed everything with the configured provider, and report what it cost.

Two stores, and they are not the same kind of thing — worth being explicit,
because "the embedding data" sounds like one place and is two:

  the Corpus index   data/corpus-index.json — a build artifact, committed,
                     read at runtime, never written by the API (ADR-0018)
  notebook material  content.notebook_chunk in Postgres — a Candidate's, and
                     deleted when they say so (ADR-0010)

Usage:

    export OPENROUTER_API_KEY=...
    python scripts/reset_embeddings.py --provider openrouter --yes

Nothing is destroyed without `--yes`. A dry run prints the token count and the
estimated spend and stops, which is the number you probably wanted anyway.

Cost is computed from our own token counts and our own arithmetic, as ADR-0014
requires of every figure this product bills on. The provider's dashboard is the
authority; this is the number we would have charged.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

CORPUS = ROOT / "data" / "corpus.json"
ARTIFACT = ROOT / "data" / "corpus-index.json"


def approx_tokens(text: str) -> int:
    """Four characters to a token — the estimate the rest of the product bills on."""
    return len(text) // 4


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default=os.environ.get("EMBEDDING_PROVIDER") or "openrouter")
    parser.add_argument("--model", default=os.environ.get("EMBEDDING_MODEL") or "")
    parser.add_argument("--corpus", action="store_true", help="only the Corpus index")
    parser.add_argument("--notebooks", action="store_true", help="only notebook material")
    parser.add_argument("--yes", action="store_true", help="actually spend money")
    args = parser.parse_args()

    both = not (args.corpus or args.notebooks)
    do_corpus = both or args.corpus
    do_notebooks = both or args.notebooks

    env = {**os.environ, "EMBEDDING_PROVIDER": args.provider}
    if args.model:
        env["EMBEDDING_MODEL"] = args.model
    # A paid provider is refused unless the deployment says so out loud. This is
    # a script for spending money on purpose, so it says so.
    env.setdefault("EMBEDDING_ALLOW_PAID", "1")

    from interviewer.corpus.adapters.interview_lm import ingest
    from interviewer.corpus.index import _topic_chunks, build
    from interviewer.corpus.related import save
    from interviewer.embeddings import make_embedder

    embedder = make_embedder(env)
    price = float(getattr(embedder, "dollars_per_million", 0.0))
    print(f"provider : {embedder.model_name}")
    print(f"price    : ${price}/M tokens"
          if price else "price    : unknown — cost cannot be estimated")

    corpus_tokens = notebook_tokens = 0
    corpus = None

    if do_corpus:
        corpus = ingest(CORPUS)
        corpus_tokens = sum(
            approx_tokens(chunk)
            for topic in corpus.topics
            for chunk in _topic_chunks(topic)
        )
        print(f"\ncorpus   : {len(list(corpus.topics))} Topics, "
              f"~{corpus_tokens:,} tokens")

    rows: list[dict] = []
    if do_notebooks:
        try:
            from interviewer.db.engine import create_content, make_engine
            from interviewer.notebooks.store import NotebookStore

            engine = make_engine()
            create_content(engine)
            store = NotebookStore(engine)
            for notebook_id in store.all_notebook_ids():
                rows.extend(store.chunks_of(notebook_id, modality="text"))
            notebook_tokens = sum(approx_tokens(r["text"]) for r in rows)
            print(f"notebooks: {len(rows)} text chunks, ~{notebook_tokens:,} tokens")
            figures = sum(
                len(store.figures_of(nb)) for nb in store.all_notebook_ids()
            )
            if figures:
                print(f"           {figures} figure(s) — this provider has no image "
                      "tower, so they keep the vectors they have")
        except Exception as exc:
            print(f"notebooks: unreachable ({type(exc).__name__}: {exc})")
            do_notebooks = False

    total = corpus_tokens + notebook_tokens
    estimate = total / 1_000_000 * price
    print(f"\ntotal    : ~{total:,} tokens"
          + (f"  ≈ ${estimate:.4f}" if price else ""))

    if not args.yes:
        print("\ndry run — nothing embedded, nothing spent, nothing reset.")
        print("re-run with --yes to do it for real.")
        return 0

    warm = getattr(embedder, "warm", None)
    if callable(warm):
        warm()

    started = time.monotonic()
    if do_corpus and corpus is not None:
        print("\nembedding the Corpus...")
        index = build(corpus, embedder)
        save(index, ARTIFACT)
        print(f"  rebuilt {ARTIFACT.name}: {index.topic_count} Topics, "
              f"{sum(len(v) for v in index.related.values())} edges")

    if do_notebooks and rows:
        print("\nre-embedding notebook material...")
        from interviewer.notebooks.service import NotebookService

        service = NotebookService(engine, embedder=embedder)
        for notebook_id in store.all_notebook_ids():
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
        print(f"cost     : ≈ ${estimate:.4f}  "
              f"= {int(-(-total * price * 100 // 1_000_000))} Credits")
        print("\nthe authority is your OpenRouter dashboard; this is the number "
              "we would have billed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
