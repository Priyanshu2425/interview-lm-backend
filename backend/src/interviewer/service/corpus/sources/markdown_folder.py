"""A second Adapter, written against the contract alone.

Its purpose is to make ADR-0007's claim checkable: the backbone interviews on
any subject, and a Corpus Source is reached through an Adapter that holds all
source-specific knowledge. Nothing in this file imports the InterviewLM adapter, and
nothing in the backbone knows this one exists.

Shape it maps:
    root/<module>/<topic>/<nn>-name.md
    a file named *answer-key* or *solution* is Ground Truth for the file whose
    name precedes it in order.
"""

from __future__ import annotations

import re
from pathlib import Path

from interviewer.model.corpus_models import (
    Corpus, CorpusProvenance, Leaf, LeafKind, Module, Topic, Track,
)

ADAPTER_NAME = "markdown_folder"


def _title(p: Path) -> str:
    return re.sub(r"^\d+[-_]", "", p.stem).replace("-", " ").replace("_", " ").title()


def _order(p: Path, fallback: int) -> int:
    m = re.match(r"^(\d+)", p.name)
    return int(m.group(1)) if m else fallback


def ingest(root: Path, *, extracted_at: str = "") -> Corpus:
    root = Path(root)
    modules: list[Module] = []
    for mi, mdir in enumerate(sorted(d for d in root.iterdir() if d.is_dir()), 1):
        topics: list[Topic] = []
        for ti, tdir in enumerate(sorted(d for d in mdir.iterdir() if d.is_dir()), 1):
            files = sorted(tdir.glob("*.md"))
            leaves: list[Leaf] = []
            previous_id: str | None = None
            for fi, f in enumerate(files, 1):
                text = f.read_text(encoding="utf-8").strip() or None
                is_key = bool(re.search(r"answer[-_]?key|solution", f.stem, re.I))
                kind = (
                    LeafKind.GROUND_TRUTH if is_key and text and previous_id
                    else LeafKind.CONTENT
                )
                lid = f"{tdir.name}/{f.stem}"
                leaves.append(Leaf(
                    id=lid, order=_order(f, fi), title=_title(f), kind=kind,
                    text=text, source_ref=str(f),
                    answers_leaf_id=previous_id if kind is LeafKind.GROUND_TRUTH else None,
                ))
                if not is_key:
                    previous_id = lid
            if leaves:
                leaves.sort(key=lambda l: l.order)
                topics.append(Topic(id=f"{mdir.name}/{tdir.name}", order=ti,
                                    title=_title(tdir), leaves=tuple(leaves)))
        if topics:
            modules.append(Module(id=mdir.name, order=mi, title=_title(mdir),
                                  topics=tuple(topics)))
    return Corpus(
        provenance=CorpusProvenance(
            source=str(root), extracted_at=extracted_at or "unknown",
            adapter=ADAPTER_NAME, adapter_version="1",
        ),
        tracks=(Track(key="md", title=_title(root), modules=tuple(modules)),),
    )
