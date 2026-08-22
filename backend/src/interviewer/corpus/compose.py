"""Serving more than one Corpus Source at once.

The backbone was always corpus-agnostic (ADR-0007); it was never multi-Corpus.
A Candidate examining themselves on a course *and* on their own notes needs both
visible in one picker, and `topic_id` was already required to be globally unique
precisely so that this is a merge rather than a namespace problem.
"""

from __future__ import annotations

from .contract import Corpus, CorpusProvenance


def compose(*corpora: Corpus) -> Corpus:
    """Merge Corpora into one. Track keys must not collide, and ids may not either."""
    present = [c for c in corpora if c is not None]
    if not present:
        raise ValueError("compose() needs at least one Corpus")
    if len(present) == 1:
        return present[0]
    return Corpus(
        provenance=CorpusProvenance(
            source=" + ".join(c.provenance.source for c in present),
            extracted_at=max(c.provenance.extracted_at for c in present),
            adapter=" + ".join(sorted({c.provenance.adapter for c in present})),
            adapter_version=" + ".join(
                sorted({c.provenance.adapter_version for c in present})
            ),
        ),
        tracks=tuple(t for c in present for t in c.tracks),
    )
