"""Corpus readings the surface needs.

The surface computes nothing: Topic counts, Ground Truth counts and the Grading
Mode a scope can support all arrive already decided.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...model.corpus import Corpus, GradingMode


@dataclass(frozen=True, slots=True)
class ModuleReading:
    module_id: str
    track_key: str
    order: int
    title: str
    description: str
    topic_count: int
    ground_truth_topic_count: int
    ceiling: GradingMode


@dataclass(frozen=True, slots=True)
class ScopeReading:
    """What a chosen set of Modules can produce. Never a difficulty claim."""

    module_count: int
    topic_count: int
    ground_truth_topic_count: int
    strongest_mode: GradingMode | None


class CorpusService:
    __slots__ = ("_c",)

    def __init__(self, corpus: Corpus) -> None:
        self._c = corpus

    def rebind(self, corpus: Corpus) -> None:
        """Swap the Corpus in place — see `DossierLoader.rebind`."""
        self._c = corpus

    def modules(self, track_key: str | None = None) -> list[ModuleReading]:
        out = []
        for track in self._c.tracks:
            if track_key and track.key != track_key:
                continue
            for m in track.modules:
                ceilings = [t.grading_mode_ceiling for t in m.topics]
                out.append(
                    ModuleReading(
                        module_id=m.id,
                        track_key=track.key,
                        order=m.order,
                        title=m.title,
                        description=m.description,
                        topic_count=len(m.topics),
                        ground_truth_topic_count=m.ground_truth_topic_count,
                        ceiling=min(ceilings, key=_authority),
                    )
                )
        return out

    def tracks(self) -> list[dict]:
        return [
            {
                "key": t.key,
                "title": t.title,
                "module_count": len(t.modules),
                "topic_count": sum(len(m.topics) for m in t.modules),
            }
            for t in self._c.tracks
        ]

    def scope(self, module_ids: list[str]) -> ScopeReading:
        mods = [m for m in self._c.modules if m.id in set(module_ids)]
        topics = [t for m in mods for t in m.topics]
        modes = [t.grading_mode_ceiling for t in topics]
        return ScopeReading(
            module_count=len(mods),
            topic_count=len(topics),
            ground_truth_topic_count=sum(1 for t in topics if t.ground_truth_pairs),
            strongest_mode=min(modes, key=_authority) if modes else None,
        )

    def topic_ids_for(self, module_ids: list[str]) -> list[str]:
        wanted = set(module_ids)
        return [t.id for m in self._c.modules if m.id in wanted for t in m.topics]


_ORDER = {
    GradingMode.GROUND_TRUTH: 0,
    GradingMode.TEXT_GROUNDED: 1,
    GradingMode.MODEL_JUDGMENT: 2,
}


def _authority(mode: GradingMode) -> int:
    return _ORDER[mode]
