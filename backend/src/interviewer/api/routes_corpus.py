from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from interviewer.corpus.loader import TopicNotFound

from .auth import current_candidate

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
    #: uploaded | ingesting | ready | failed | stub. `ready` for everything in
    #: the shipped Corpus and for every finished ingest; the others are
    #: documents that are in the Library and not yet examinable (ISSUE-0035).
    state: str = "ready"
    #: Sections embedded of sections found, for a document still being read.
    progress_done: int = 0
    progress_total: int = 0


class RelatedOut(BaseModel):
    """One neighbouring Topic, and enough to decide whether to show it.

    `same_module` is reported rather than filtered on. A Topic's nearest
    neighbours are often its own Module's, which is true and useful for "what
    leads into this"; cross-Module neighbours are the sideways connection this
    was built for. Which to show is the surface's decision (ISSUE-0031).
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
def modules(track: str | None = None,
            candidate_id: str = Depends(current_candidate)) -> list[ModuleOut]:
    """The shipped Corpus, plus this Candidate's own notebooks and nobody else's.

    "Nobody else's" was a comment until the Candidate stopped being a query
    parameter. Naming somebody else's id listed the Modules their uploads
    produced — the titles of a private Library, to anyone who could guess an id.

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
    """Documents that are in the Library and are not examinable, and why.

    Three situations with one shape: a Source that extracted to nothing, one
    that has not been ingested yet, and one whose ingest failed. None of them
    holds a Topic, so none can be part of a Corpus at all — they are read from
    the notebook record instead. Omitting them would make Coverage a measurement
    of what parsed rather than of what the Candidate uploaded, and would make a
    forty-second import look like a document that never arrived.
    """
    if candidate_id is None:
        return []
    from interviewer.notebooks.corpus_view import track_key

    svc = get_notebook_service()
    out: list[ModuleOut] = []
    for record in svc.store.visible_to(candidate_id):
        key = track_key(record.notebook_id)
        if track and track != key:
            continue
        for source in record.sources:
            if source.selectable:
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
                    stub_reason=source.stub_reason or _waiting_reason(source),
                    state=source.state,
                    progress_done=source.progress_done,
                    progress_total=source.progress_total,
                )
            )
    return out


def _waiting_reason(source) -> str:
    """Why a document that has not failed is still not selectable.

    Said rather than left blank: "listed and greyed out with no explanation" is
    the state ISSUE-0023 wrote `stub_reason` to prevent, and an un-ingested
    document lands in exactly the same place.
    """
    if source.state == "ingesting":
        return (
            f"still being read — {source.progress_done} of "
            f"{source.progress_total} sections embedded"
        )
    if source.state == "uploaded":
        return "uploaded, waiting to be read"
    return "not examinable"


def _visible_notebook_tracks(candidate_id: str | None) -> set[str]:
    if candidate_id is None:
        return set()
    from interviewer.notebooks.corpus_view import track_key

    svc = get_notebook_service()
    # Their own, plus every shared Corpus. Shared is the reason two Candidates
    # can hold the same `topic_id` at all, so it has to reach the picker.
    return {track_key(r.notebook_id) for r in svc.store.visible_to(candidate_id)}


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
def provenance(candidate_id: str = Depends(current_candidate)) -> dict:
    """Which extract a Session ran against (PRD-0001 §13).

    Each Library is reported as itself. Merging several into one composite
    string would name an extract that never happened, so the shared Library the
    Candidate is examined on is reported at the top level and their own
    notebooks are listed beside it.

    An imported Library keeps the provenance it arrived with (ISSUE-0037): the
    import is a transport, not a source, and "the notebook adapter" is not an
    answer to what the material was extracted from.
    """
    from interviewer.db.content import SHARED

    svc = get_notebook_service()
    shared = [
        corpus.provenance.model_dump()
        for record in svc.store.visible_to("")
        if record.visibility == SHARED
        and (corpus := svc.corpus(record.notebook_id)) is not None
    ]
    out = shared[0] if shared else {
        "source": "none", "extracted_at": "", "adapter": "none",
        "adapter_version": "1",
    }
    if len(shared) > 1:
        # Listed rather than merged, for the same reason as above.
        out["shared"] = shared
    if candidate_id is not None:
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


class TouchedOut(BaseModel):
    """A Module the chosen scope shares material with (ADR-0023).

    Carries no figure about the Candidate — no Coverage, no Mastery, nothing
    that could be combined into one — because this is a statement about the
    material and has to stay one.
    """

    module_id: str
    title: str
    track_key: str
    in_scope: bool
    edges: int
    score: float
    selectable: bool


@router.get("/corpus/scope/related", response_model=list[TouchedOut])
def scope_related(module_id: list[str] = Query(default=[])) -> list[TouchedOut]:
    """Which Modules the chosen scope touches, ranked here rather than there.

    The Module picker is where Related Topics appears (ADR-0023), because it is
    the one place a claim about the material cannot be read as a claim about the
    person: nothing has been measured yet, and choosing differently changes
    scope rather than a score.

    Aggregation and ordering are the server's, so the surface renders and
    decides nothing (ADR-0009).
    """
    from interviewer.corpus.related import modules_touched

    corpus = get_corpus()
    chosen = set(module_id)
    modules = {m.id: m for m in corpus.modules}
    if not chosen or any(m not in modules for m in chosen):
        return []
    track_of = {
        module.id: track.key for track in corpus.tracks for module in track.modules
    }
    topic_ids = [
        topic.id for mid in sorted(chosen) for topic in modules[mid].topics
    ]
    related = get_related_topics()
    touched = modules_touched(
        topic_ids,
        neighbours_of=related.for_topic,
        module_of={
            topic.id: module.id
            for module in corpus.modules
            for topic in module.topics
        },
        titles={mid: m.title for mid, m in modules.items()},
        in_scope=chosen,
    )
    return [
        TouchedOut(
            module_id=t.module_id,
            title=t.title,
            track_key=track_of.get(t.module_id, ""),
            in_scope=t.in_scope,
            edges=t.edges,
            score=t.score,
            selectable=True,
        )
        for t in touched
        if t.module_id in modules
    ]


@router.get("/corpus/topics/{topic_id}/related", response_model=list[RelatedOut])
def related(topic_id: str) -> list[RelatedOut]:
    """What else relates to this Topic — the case ADR-0005 permitted alongside.

    Answered from the centroids stored at ingest. Nothing is embedded here:
    every vector this compares was written when its Topic was, so ADR-0005's
    "there is no query to embed" stays literally true of the running system.

    An empty list means two things — a Topic whose Corpus this deployment does
    not hold, and a Topic with no neighbour above the floor — and looks
    identical from out here on purpose. Both render as nothing, and both are
    honest.
    """
    if topic_id not in {topic.id for topic in get_corpus().topics}:
        raise HTTPException(404, "unknown topic_id")
    return [RelatedOut(**row) for row in get_related_topics().for_topic(topic_id)]
