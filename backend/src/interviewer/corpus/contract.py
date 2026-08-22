"""The Corpus Contract — what an Adapter must emit (PRD-0001, ADR-0007).

This module is declarative. It holds no behaviour beyond validation, and it
speaks backbone vocabulary only: Module, Topic, leaf, Ground Truth, order, ids.
Nothing here knows what Scaler Cortex is.

One rule the Corpus owns and keeps: difficulty is not a property of the Corpus.
There is no field for it, so an Adapter cannot supply one and the Interviewer
cannot read one.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GradingMode(str, Enum):
    """How an answer can be judged. Ordered by descending authority."""

    GROUND_TRUTH = "ground_truth"
    TEXT_GROUNDED = "text_grounded"
    MODEL_JUDGMENT = "model_judgment"

    @property
    def weight(self) -> float:
        """Trust in the mode. Deliberately coarse; three named constants."""
        return _WEIGHTS[self]


_WEIGHTS = {
    GradingMode.GROUND_TRUTH: 1.0,
    GradingMode.TEXT_GROUNDED: 0.7,
    GradingMode.MODEL_JUDGMENT: 0.5,
}


class LeafKind(str, Enum):
    """What a leaf is for, in backbone terms.

    An Adapter maps its source's own units onto these. `GROUND_TRUTH` is one way
    a source supplies an authoritative answer; `PROMPT` is material posing
    questions that a Ground Truth leaf answers.
    """

    CONTENT = "content"
    PROMPT = "prompt"
    GROUND_TRUTH = "ground_truth"
    REFERENCE = "reference"


class Leaf(BaseModel):
    """The smallest unit an Adapter emits. Carries text or it does not."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    order: int = Field(ge=1)
    title: str = Field(min_length=1)
    kind: LeafKind
    text: str | None = None
    source_ref: str | None = None
    answers_leaf_id: str | None = None
    syllabus: tuple[str, ...] = ()

    @property
    def has_text(self) -> bool:
        return bool(self.text and self.text.strip())

    @model_validator(mode="after")
    def _ground_truth_must_answer_something(self) -> Leaf:
        if self.kind is LeafKind.GROUND_TRUTH and not self.answers_leaf_id:
            raise ValueError(
                f"leaf {self.id!r} is ground_truth but names no leaf it answers"
            )
        if self.kind is LeafKind.GROUND_TRUTH and not self.has_text:
            raise ValueError(f"leaf {self.id!r} is ground_truth but carries no text")
        return self


class Topic(BaseModel):
    """A Module's subdivision, and the unit of load.

    Exactly one Topic is held in context to ask one question, whatever the
    Session's scope. It is also the unit Topic Confidence is keyed on.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    order: int = Field(ge=1)
    title: str = Field(min_length=1)
    leaves: tuple[Leaf, ...]

    @field_validator("leaves")
    @classmethod
    def _ordered_and_unique(cls, v: tuple[Leaf, ...]) -> tuple[Leaf, ...]:
        if not v:
            raise ValueError("a Topic must hold at least one leaf")
        ids = [leaf.id for leaf in v]
        if len(set(ids)) != len(ids):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate leaf ids within a Topic: {dupes}")
        if [leaf.order for leaf in v] != sorted(leaf.order for leaf in v):
            raise ValueError("leaves are not in ascending order")
        return v

    @property
    def content_leaves(self) -> tuple[Leaf, ...]:
        """Leaves that carry retrievable text, in order."""
        return tuple(l for l in self.leaves if l.has_text)

    @property
    def ground_truth_pairs(self) -> tuple[tuple[Leaf, Leaf], ...]:
        """(prompt, ground truth) pairs. The strongest structure a source offers."""
        by_id = {l.id: l for l in self.leaves}
        out = []
        for leaf in self.leaves:
            if leaf.kind is LeafKind.GROUND_TRUTH and leaf.answers_leaf_id in by_id:
                out.append((by_id[leaf.answers_leaf_id], leaf))
        return tuple(out)

    @property
    def grading_mode_ceiling(self) -> GradingMode:
        """The strongest mode this Topic *can* support.

        A ceiling, not a setting: the Visit records the mode a question was
        actually written and graded under, which may be weaker than this.
        """
        if self.ground_truth_pairs:
            return GradingMode.GROUND_TRUTH
        if self.content_leaves:
            return GradingMode.TEXT_GROUNDED
        return GradingMode.MODEL_JUDGMENT


class Module(BaseModel):
    """A Track's top-level division, and the unit of Session scope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    order: int = Field(ge=1)
    title: str = Field(min_length=1)
    description: str = ""
    topics: tuple[Topic, ...]

    @field_validator("topics")
    @classmethod
    def _ordered(cls, v: tuple[Topic, ...]) -> tuple[Topic, ...]:
        if not v:
            raise ValueError("a Module must hold at least one Topic")
        if [t.order for t in v] != sorted(t.order for t in v):
            raise ValueError("topics are not in ascending order")
        return v

    @property
    def ground_truth_topic_count(self) -> int:
        return sum(1 for t in self.topics if t.ground_truth_pairs)


class Track(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    modules: tuple[Module, ...]


class CorpusProvenance(BaseModel):
    """Which extract a Session ran against (PRD-0001 §13)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    extracted_at: str
    adapter: str
    adapter_version: str = "0"


class Corpus(BaseModel):
    """A validated Corpus. Constructing one is the contract being satisfied."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: CorpusProvenance
    tracks: tuple[Track, ...]

    @model_validator(mode="after")
    def _ids_unique_across_the_whole_corpus(self) -> Corpus:
        """topic_id is the permanent join key. It must be unique globally, not
        merely within its Module — a collision would silently merge two
        Candidates' evidence for different subjects."""
        seen_topics: dict[str, str] = {}
        seen_modules: dict[str, str] = {}
        for track in self.tracks:
            for module in track.modules:
                if module.id in seen_modules:
                    raise ValueError(f"duplicate module id {module.id!r}")
                seen_modules[module.id] = module.title
                for topic in module.topics:
                    if topic.id in seen_topics:
                        raise ValueError(
                            f"duplicate topic id {topic.id!r} "
                            f"({seen_topics[topic.id]!r} and {topic.title!r})"
                        )
                    seen_topics[topic.id] = topic.title
        return self

    # -- lookups -------------------------------------------------------------

    @property
    def modules(self) -> tuple[Module, ...]:
        return tuple(m for t in self.tracks for m in t.modules)

    @property
    def topics(self) -> tuple[Topic, ...]:
        return tuple(tp for m in self.modules for tp in m.topics)

    def module(self, module_id: str) -> Module | None:
        return next((m for m in self.modules if m.id == module_id), None)

    def topic(self, topic_id: str) -> Topic | None:
        return next((t for t in self.topics if t.id == topic_id), None)

    def module_of(self, topic_id: str) -> Module | None:
        return next(
            (m for m in self.modules for t in m.topics if t.id == topic_id), None
        )
