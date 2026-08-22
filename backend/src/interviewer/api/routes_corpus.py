from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from interviewer.corpus.loader import TopicNotFound

from .deps import (
    get_corpus, get_corpus_service, get_loader, get_notebook_service,
    get_related_topics,
)

router = APIRouter(tags=["corpus"])


class ModuleOut(BaseModel):
    module_id: str
    track_key: str
    order: int
    title: str
    description: str
    topic_count: int
    ground_truth_topic_count: int
    ceiling: str
    #: A Module whose Source carried no retrievable text is listed and cannot be
    #: chosen. Coverage is measured against the real notebook, not against the
    #: part that happened to parse (PRD-0001 §16).
    selectable: bool = True
    stub_reason: str | None = None


class RelatedOut(BaseModel):
    """One neighbouring Topic, and enough to decide whether to show it.

    `same_module` is reported rather than filtered on. A Topic's nearest
    neighbours are often its own Module's, which is true and useful for "what
    leads into this"; cross-Module neighbours are the sideways connection this
    index was built for. Which to show is the surface's decision (ISSUE-0031).
    """

    topic_id: str
    title: str
    module_id: str
    same_module: bool
    score: float


class ScopeOut(BaseModel):
    module_count: int
    topic_count: int
    ground_truth_topic_count: int
    strongest_mode: str | None
    # Deliberately absent: any difficulty figure, and any estimate of cost.


@router.get("/corpus/tracks")
def tracks() -> list[dict]:
    return get_corpus_service().tracks()


@router.get("/corpus/modules", response_model=list[ModuleOut])
def modules(track: str | None = None, candidate_id: str | None = None) -> list[ModuleOut]:
    """The shipped Corpus, plus this Candidate's own notebooks and nobody else's.

    A notebook Track is private to the Candidate who uploaded it, so the picker
    is filtered by ownership rather than by what happens to be loaded.
    """
    visible = _visible_notebook_tracks(candidate_id)
    listed = [
        m for m in _all_modules(track)
        if not m.track_key.startswith("nb-") or m.track_key in visible
    ]
    return listed + _stub_modules(candidate_id, track)


def _stub_modules(candidate_id: str | None, track: str | None) -> list[ModuleOut]:
    """Sources that extracted to nothing, shown rather than hidden.

    A stub holds no Topic, so it cannot be part of a Corpus at all — it is read
    from the notebook record instead. Omitting it would make Coverage a
    measurement of what parsed rather than of what the Candidate uploaded.
    """
    if candidate_id is None:
        return []
    from interviewer.notebooks.corpus_view import track_key

    svc = get_notebook_service()
    out: list[ModuleOut] = []
    for record in svc.store.for_candidate(candidate_id):
        key = track_key(record.notebook_id)
        if track and track != key:
            continue
        for source in record.sources:
            if source.state != "stub":
                continue
            out.append(
                ModuleOut(
                    module_id=source.module_id,
                    track_key=key,
                    order=source.order,
                    title=source.title,
                    description="",
                    topic_count=0,
                    ground_truth_topic_count=0,
                    ceiling="model_judgment",
                    selectable=False,
                    stub_reason=source.stub_reason,
                )
            )
    return out


def _visible_notebook_tracks(candidate_id: str | None) -> set[str]:
    if candidate_id is None:
        return set()
    from interviewer.notebooks.corpus_view import track_key

    svc = get_notebook_service()
    return {track_key(r.notebook_id) for r in svc.store.for_candidate(candidate_id)}


def _all_modules(track: str | None) -> list[ModuleOut]:
    return [
        ModuleOut(
            module_id=m.module_id,
            track_key=m.track_key,
            order=m.order,
            title=m.title,
            description=m.description,
            topic_count=m.topic_count,
            ground_truth_topic_count=m.ground_truth_topic_count,
            ceiling=m.ceiling.value,
        )
        for m in get_corpus_service().modules(track)
    ]


@router.get("/corpus/scope", response_model=ScopeOut)
def scope(module_id: list[str] = Query(default=[])) -> ScopeOut:
    s = get_corpus_service().scope(module_id)
    return ScopeOut(
        module_count=s.module_count,
        topic_count=s.topic_count,
        ground_truth_topic_count=s.ground_truth_topic_count,
        strongest_mode=s.strongest_mode.value if s.strongest_mode else None,
    )


@router.get("/corpus/provenance")
def provenance(candidate_id: str | None = None) -> dict:
    """Which extract a Session ran against (PRD-0001 §13).

    The shipped Corpus has one provenance and it is reported as itself. A
    notebook is a second Source with a second provenance, listed separately —
    merging them into one composite string would name an extract that never
    happened.
    """
    from .deps import get_base_corpus

    out = get_base_corpus().provenance.model_dump()
    if candidate_id is not None:
        svc = get_notebook_service()
        out["notebooks"] = [
            corpus.provenance.model_dump()
            for record in svc.store.for_candidate(candidate_id)
            if (corpus := svc.corpus(record.notebook_id)) is not None
        ]
    return out


@router.get("/corpus/topics/{topic_id}")
def topic(topic_id: str) -> dict:
    """Dossier metadata. Never the Ground Truth text — no Candidate-facing route
    returns grading material (ADR-0006)."""
    try:
        d = get_loader().load(topic_id)
    except TopicNotFound:
        raise HTTPException(status_code=404, detail="unknown topic_id") from None
    return {
        "topic_id": d.topic_id,
        "title": d.topic_title,
        "module_id": d.module_id,
        "module_title": d.module_title,
        "leaf_count": len(d.content),
        "is_empty": d.is_empty,
        "approx_tokens": d.approx_tokens,
        "grading_mode_ceiling": d.grading_mode_ceiling.value,
        "syllabus": list(d.syllabus),
    }


@router.get("/corpus/topics/{topic_id}/related", response_model=list[RelatedOut])
def related(topic_id: str) -> list[RelatedOut]:
    """What else relates to this Topic — the case ADR-0005 permitted alongside.

    Precomputed, never queried. The neighbours were decided when the index was
    built, so no vector search runs here and nothing is embedded: ADR-0005's
    "there is no query to embed" stays literally true of the running system.

    An empty list means one of three things — no index, an index that no longer
    matches the Corpus, or a Topic that genuinely has no neighbours — and looks
    identical from out here on purpose. All three render as nothing, and all
    three are honest.
    """
    if topic_id not in {topic.id for topic in get_corpus().topics}:
        raise HTTPException(404, "unknown topic_id")
    return [RelatedOut(**row) for row in get_related_topics().for_topic(topic_id)]
