"""Citations — the span a question actually came from.

The Interviewer already records a `grounding_ref`: which leaves of a Topic were
put in front of the question writer. A citation is that reference resolved into
something a Candidate can read — the text, and where to find it.

Two rules hold this module in place:

- **No query.** Citations are derived from what was already handed to the model,
  never from a similarity search run afterwards. The interview loop still loads a
  dossier whole, by id (ADR-0005).
- **Snapshot, not pointer.** The text travels with the Evidence row, because the
  Evidence outlives the material (ADR-0003) and a dangling citation would make
  the permanent record less honest than no citation at all.
- **One Topic at a time.** A question may span three (ISSUE-0042), and its
  `grounding_ref` then holds one part per Topic. Each is resolved against its
  own dossier, so a citation never claims to come from material it did not.
"""

from __future__ import annotations

from .loader_service import Dossier


def resolve(dossier: Dossier, grounding_ref: dict | None) -> list[dict]:
    """Which spans grounded this question, in the reader's terms."""
    if not grounding_ref:
        return []
    leaves = {leaf.id: leaf for leaf in dossier.content}
    for _, key in dossier.ground_truth_pairs:
        leaves.setdefault(key.id, key)

    kind = grounding_ref.get("kind")
    if kind == "spanning":
        # A question spanning several Topics is grounded in each of them
        # separately (ISSUE-0042), and a citation belongs to the Topic it came
        # from. The part for *this* dossier is resolved; the others belong to
        # their own dossiers and are resolved against those.
        part = next(
            (x for x in grounding_ref.get("parts") or []
             if x.get("topic_id") == dossier.topic_id),
            None,
        )
        return resolve(dossier, part) if part else []
    if kind == "ground_truth":
        wanted = [grounding_ref.get("prompt_leaf_id")]
    elif kind == "text":
        wanted = list(grounding_ref.get("leaf_ids") or [])
    else:
        # Model judgment: anchored to a syllabus, grounded in no span at all.
        return []

    out = []
    for leaf_id in wanted:
        leaf = leaves.get(leaf_id)
        if leaf is None or not leaf.text:
            continue
        source_id, _, page = (leaf.source_ref or "").partition("#p")
        out.append(
            {
                "chunk_id": leaf.id,
                "title": leaf.title,
                "source_id": source_id,
                "page": int(page) if page.isdigit() else None,
                "text": leaf.text,
                "topic_id": dossier.topic_id,
            }
        )
    return out


def render(citation: dict) -> str:
    """What a citation is called on screen: source and page, never an offset."""
    page = citation.get("page")
    source = citation.get("title") or citation.get("source_id") or "source"
    return f"{source} · p.{page}" if page else str(source)
