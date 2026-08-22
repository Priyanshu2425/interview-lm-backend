"""The Cortex Adapter — the only component that knows Scaler Cortex's shape.

ADR-0007: all source-specific knowledge lives here and nowhere else. This is the
mapping the backbone refuses to guess — what counts as a Module, what counts as a
Topic, which text is Ground Truth, and how Cortex's own units collapse into that
shape.

Cortex vocabulary appears in this file (Class, Answer Key, Assignment, contest)
and must not leak past it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..contract import (
    Corpus,
    CorpusProvenance,
    Leaf,
    LeafKind,
    Module,
    Topic,
    Track,
)

ADAPTER_NAME = "cortex"
ADAPTER_VERSION = "1"

# How a Cortex Class's `kind` maps onto backbone leaf kinds.
_KIND = {
    "answer_key": LeafKind.GROUND_TRUTH,
    "assignment": LeafKind.PROMPT,
    "revision": LeafKind.CONTENT,
    "concepts": LeafKind.CONTENT,
    "interview_insights": LeafKind.CONTENT,
    "other": LeafKind.CONTENT,
}


class AdapterError(ValueError):
    """The source could not be mapped onto the contract."""


def _read_text(cls: dict[str, Any], root: Path) -> str | None:
    """Cortex text lives on disk beside corpus.json, not inline."""
    if cls.get("contentType") != "text":
        return None
    rel = cls.get("markdownPath")
    if not rel:
        return cls.get("textContent") or None
    path = root / rel
    if not path.is_file():
        # The scrape writes no file for a Class it found empty, and records
        # chars=0 for it. That is an empty Class, not data loss — but a missing
        # file for a Class that *did* have content is a broken extract, and
        # ingest is where that must surface rather than at question time.
        if int(cls.get("chars") or 0) == 0:
            return None
        raise AdapterError(
            f"class {cls.get('id')!r} declares markdownPath {rel!r} with "
            f"{cls.get('chars')} chars, but the file is missing"
        )
    body = path.read_text(encoding="utf-8")
    # strip the YAML front matter the scrape writes
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            body = body[end + 4 :]
    return body.strip() or None


def _leaf(cls: dict[str, Any], root: Path) -> Leaf:
    kind = _KIND.get(cls.get("kind") or "other", LeafKind.CONTENT)
    text = _read_text(cls, root)

    # A Contest is deliberately out of scope: we keep its syllabus as curriculum
    # metadata and take none of its problems.
    syllabus = tuple(cls.get("contestSyllabus") or ())
    if cls.get("contentType") == "contest":
        kind = LeafKind.REFERENCE

    # An Answer Key with no text cannot be Ground Truth, whatever Cortex calls it.
    if kind is LeafKind.GROUND_TRUTH and not (text and text.strip()):
        kind = LeafKind.CONTENT

    return Leaf(
        id=str(cls["id"]),
        order=int(cls["order"]),
        title=str(cls["title"]),
        kind=kind,
        text=text,
        source_ref=cls.get("url"),
        answers_leaf_id=(
            str(cls["assignmentId"])
            if kind is LeafKind.GROUND_TRUTH and cls.get("assignmentId")
            else None
        ),
        syllabus=syllabus,
    )


def ingest(corpus_json: Path, *, data_root: Path | None = None) -> Corpus:
    """Turn a Cortex scrape into a validated Corpus.

    Raises on anything the contract will not accept. Validation happens here, at
    ingest, rather than being discovered at question time.
    """
    corpus_json = Path(corpus_json)
    root = Path(data_root) if data_root else corpus_json.parent / "markdown"
    try:
        raw = json.loads(corpus_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise AdapterError(f"{corpus_json} is not valid JSON: {e}") from e

    tracks: list[Track] = []
    for t in raw.get("tracks", []):
        modules: list[Module] = []
        for m in t.get("modules", []):
            topics: list[Topic] = []
            for tp in m.get("topics", []):
                leaves = [_leaf(c, root) for c in tp.get("classes", [])]
                leaves.sort(key=lambda l: l.order)
                if not leaves:
                    continue  # a Topic Cortex left empty is not a Topic
                topics.append(
                    Topic(
                        id=str(tp["id"]),
                        order=int(tp["order"]),
                        title=str(tp["title"]).strip(),
                        leaves=tuple(leaves),
                    )
                )
            if not topics:
                continue
            topics.sort(key=lambda x: x.order)
            # Cortex module order is not always dense (CV skips topic 6); the
            # contract wants ascending, not gapless, so renumber nothing.
            modules.append(
                Module(
                    id=str(m["id"]),
                    order=int(m["order"]),
                    title=str(m["title"]).strip(),
                    description=str(m.get("description") or "").strip(),
                    topics=tuple(topics),
                )
            )
        modules.sort(key=lambda x: x.order)
        tracks.append(
            Track(
                key=str(t["key"]),
                title=str(t["title"]).strip(),
                modules=tuple(modules),
            )
        )

    return Corpus(
        provenance=CorpusProvenance(
            source=str(raw.get("source", "unknown")),
            extracted_at=str(raw.get("scrapedAt", "")),
            adapter=ADAPTER_NAME,
            adapter_version=ADAPTER_VERSION,
        ),
        tracks=tuple(tracks),
    )
