"""The contract as something an Adapter author can run locally.

Two things live here: a validation report that names **every** violation rather
than the first one, and a conformance check plus fixture an author can run
without the rest of the system.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from pydantic import ValidationError

from ...model.corpus_models import Corpus, GradingMode, Leaf, LeafKind, Module, Topic, Track


@dataclass
class Report:
    """What ingest observed. Violations are collected, not raised one at a time."""

    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tracks: int = 0
    modules: int = 0
    topics: int = 0
    leaves: int = 0
    stub_leaves: int = 0
    stub_only_topics: list[str] = field(default_factory=list)
    ground_truth_pairs: int = 0
    ceilings: dict[str, int] = field(default_factory=dict)
    dossier_tokens: dict[str, int] = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.violations

    def render(self) -> str:
        lines = [
            f"tracks={self.tracks} modules={self.modules} topics={self.topics} "
            f"leaves={self.leaves}",
            f"ground-truth pairs={self.ground_truth_pairs}  "
            f"ceilings={self.ceilings}",
            f"dossier tokens={self.dossier_tokens}",
            f"stub leaves={self.stub_leaves}  "
            f"stub-only topics={len(self.stub_only_topics)}",
            f"provenance={self.provenance}",
        ]
        for w in self.warnings:
            lines.append(f"  warn: {w}")
        for v in self.violations:
            lines.append(f"  VIOLATION: {v}")
        lines.append("OK" if self.ok else f"{len(self.violations)} violation(s)")
        return "\n".join(lines)


def validate(corpus: Corpus) -> Report:
    """Report every violation in one pass.

    Constructing a Corpus already enforces the hard rules; this adds the checks
    an author needs to see all at once, and the observations a Session depends
    on (sizes, stubs, ceilings).
    """
    from .loader_service import DossierLoader

    r = Report(provenance=corpus.provenance.model_dump())
    r.tracks = len(corpus.tracks)
    r.modules = len(corpus.modules)
    r.topics = len(corpus.topics)

    topic_ids = Counter()
    module_ids = Counter()
    for track in corpus.tracks:
        if not track.modules:
            r.violations.append(f"track {track.key!r} holds no Modules")
        for m in track.modules:
            module_ids[m.id] += 1
            orders = [t.order for t in m.topics]
            if orders != sorted(orders):
                r.violations.append(f"module {m.id!r} topics are not in order")
            for t in m.topics:
                topic_ids[t.id] += 1
                r.leaves += len(t.leaves)
                stubs = [l for l in t.leaves if not l.has_text]
                r.stub_leaves += len(stubs)
                if len(stubs) == len(t.leaves):
                    # A Topic examinable only under Model judgment. Flagged, not
                    # rejected: absence of text is a mode, not a failure.
                    r.stub_only_topics.append(t.id)
                for l in t.leaves:
                    if l.kind is LeafKind.GROUND_TRUTH and not l.answers_leaf_id:
                        r.violations.append(
                            f"leaf {l.id!r} is ground_truth but answers nothing"
                        )
                r.ground_truth_pairs += len(t.ground_truth_pairs)

    for tid, n in topic_ids.items():
        if n > 1:
            r.violations.append(f"topic id {tid!r} appears {n} times")
    for mid, n in module_ids.items():
        if n > 1:
            r.violations.append(f"module id {mid!r} appears {n} times")

    r.ceilings = dict(Counter(t.grading_mode_ceiling.value for t in corpus.topics))
    r.dossier_tokens = DossierLoader(corpus).budget_report()

    if r.stub_only_topics:
        r.warnings.append(
            f"{len(r.stub_only_topics)} Topic(s) carry no retrievable text and "
            f"will be examined under Model judgment"
        )
    if r.dossier_tokens.get("max", 0) > 12_000:
        r.warnings.append(
            f"largest dossier is {r.dossier_tokens['max']} tokens — ADR-0005 "
            f"assumes a whole Topic fits in context"
        )
    return r


def diff_topics(before: Corpus, after: Corpus) -> dict:
    """Report a re-ingest that moved Topic boundaries.

    `topic_id` is the join key for everything permanent, so a Topic appearing,
    vanishing or changing shape is a fact an operator must see rather than
    discover through a posterior that stopped accumulating.
    """
    b = {t.id: t for t in before.topics}
    a = {t.id: t for t in after.topics}
    changed = [
        tid for tid in b.keys() & a.keys()
        if {l.id for l in b[tid].leaves} != {l.id for l in a[tid].leaves}
    ]
    return {
        "added": sorted(a.keys() - b.keys()),
        "removed": sorted(b.keys() - a.keys()),
        "leaves_changed": sorted(changed),
        "stable": len(b.keys() & a.keys()) - len(changed),
    }


def fixture_corpus() -> Corpus:
    """A minimal Corpus satisfying the contract.

    An Adapter author can compare against this without the rest of the system,
    and the conformance test below runs against it — which is what makes the
    contract's generality checkable rather than asserted.
    """
    from ...model.corpus_models import CorpusProvenance

    prompt = Leaf(id="l3", order=3, title="Assessment", kind=LeafKind.PROMPT,
                  text="Q1. Why scale by sqrt(d_k)?")
    key = Leaf(id="l4", order=4, title="Worked solution",
               kind=LeafKind.GROUND_TRUTH, text="Large d_k saturates softmax.",
               answers_leaf_id="l3")
    return Corpus(
        provenance=CorpusProvenance(
            source="fixture", extracted_at="2026-01-01T00:00:00Z",
            adapter="fixture", adapter_version="1",
        ),
        tracks=(Track(key="fx", title="Fixture Track", modules=(
            Module(id="fx-m1", order=1, title="Grounded Module", topics=(
                Topic(id="fx-t1", order=1, title="With Ground Truth", leaves=(
                    Leaf(id="l1", order=1, title="Notes", kind=LeafKind.CONTENT,
                         text="Attention scales scores before the softmax."),
                    prompt, key,
                )),
                Topic(id="fx-t2", order=2, title="Text only", leaves=(
                    Leaf(id="l5", order=1, title="Notes", kind=LeafKind.CONTENT,
                         text="Bagging attacks variance."),
                )),
            )),
            Module(id="fx-m2", order=2, title="Reference Only", topics=(
                Topic(id="fx-t3", order=1, title="No text at all", leaves=(
                    Leaf(id="l6", order=1, title="External test",
                         kind=LeafKind.REFERENCE, text=None,
                         syllabus=("Arrays", "Hashing")),
                )),
            )),
        )),),
    )


CONFORMANCE_EXPECTATIONS = {
    "fx-t1": GradingMode.GROUND_TRUTH,
    "fx-t2": GradingMode.TEXT_GROUNDED,
    "fx-t3": GradingMode.MODEL_JUDGMENT,
}
