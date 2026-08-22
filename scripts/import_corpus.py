#!/usr/bin/env python
"""Import a conformant Corpus into a shared Corpus in Postgres.

The Scaler material used to ship in the image and be read off disk. SPEC-0006
turns it into *an import*: the same pipeline every uploaded document goes
through, into the same tables, with one stage different — nothing is clustered
and no `topic_id` is minted, because this material arrives with 71 Topics that
are the join key for every row of Evidence and Topic Confidence (ISSUE-0034).

    python scripts/import_corpus.py --corpus data/corpus.json --title "Scaler Cortex"

Re-running it is a no-op per Module: a Source is deduplicated by the content and
the structure it carries, so an interrupted import is resumed by running the
same command again and costs nothing for the Modules already in.

One Source per Module, and the Module keeps its own id. Session scope is keyed
on `module_id`, so a Module that changed id on the way into the database would
be a different Module to every Session that named it.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=os.environ.get("CORPUS_PATH")
                        or str(ROOT / "data" / "corpus.json"))
    parser.add_argument("--title", default="Scaler Cortex")
    parser.add_argument(
        "--notebook-id",
        help="import into an existing shared Corpus rather than creating one",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report what would be imported and write nothing",
    )
    args = parser.parse_args()

    from interviewer.corpus.adapters.cortex import ingest
    from interviewer.corpus.adapters.notebook.structured import GivenLeaf, GivenTopic
    from interviewer.db.content import SHARED
    from interviewer.db.engine import create_content, create_core, make_engine
    from interviewer.embeddings import make_embedder
    from interviewer.metering.ledger import CreditLedger
    from interviewer.notebooks import NotebookService

    path = Path(args.corpus)
    if not path.exists():
        print(f"no Corpus at {path} — see data/README.md")
        return 1
    corpus = ingest(path)
    modules = list(corpus.modules)
    print(f"corpus: {len(modules)} Modules, {len(list(corpus.topics))} Topics")
    if args.dry_run:
        for module in modules:
            print(f"  {module.id}  {len(module.topics):>3} Topics  {module.title}")
        return 0

    engine = make_engine()
    create_core(engine)
    create_content(engine)
    embedder = make_embedder()
    service = NotebookService(
        engine, embedder=embedder, credits=CreditLedger(engine)
    )

    notebook_id = args.notebook_id
    if notebook_id is None:
        import uuid

        from interviewer.db.content import PLATFORM_OWNER

        notebook_id = f"nb-{uuid.uuid4().hex[:12]}"
        service.create(
            notebook_id, PLATFORM_OWNER, args.title, visibility=SHARED
        )
        print(f"created shared Corpus {notebook_id}")

    imported = skipped = 0
    for order, module in enumerate(modules, 1):
        given = [
            GivenTopic(
                topic_id=topic.id,
                title=topic.title,
                order=topic.order,
                leaves=tuple(
                    GivenLeaf(
                        leaf_id=leaf.id,
                        title=leaf.title,
                        text=leaf.text or "",
                        kind=leaf.kind.value,
                        answers_leaf_id=leaf.answers_leaf_id,
                    )
                    for leaf in topic.leaves
                ),
            )
            for topic in module.topics
        ]
        if not any(t.text.strip() for t in given):
            print(f"  {module.id}: no text, skipped")
            skipped += 1
            continue
        added = service.import_structured(
            notebook_id,
            source_id=f"src-{module.id}",
            title=module.title,
            module_id=module.id,
            topics=given,
            as_operator=True,
        )
        if added.deduplicated:
            print(f"  {module.id}: already imported")
            skipped += 1
            continue
        imported += 1
        print(f"  {module.id}: {added.topics} Topics, {added.chunks} chunks")

    print(f"imported {imported} Module(s), skipped {skipped}")
    print(f"shared Corpus is {notebook_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
