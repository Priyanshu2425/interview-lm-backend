"""Skills routes (async)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from interviewer.service.corpus.loader_service import TopicNotFound
from interviewer.service.corpus.related_service import modules_touched
from interviewer.service.graph import pacing

from ...security.auth import current_candidate
from ...deps_async import (
    get_async_corpus,
    get_async_corpus_service,
    get_async_loader,
    get_async_notebook_service,
    get_async_related_topics,
)

if TYPE_CHECKING:
    # Annotations only. Imported under the guard because these are the
    # dependency types, not the dependency: FastAPI takes the object from
    # `Depends`, and a plain import here would be a second edge into the
    # repository package for no runtime gain.
    from ...repository.async_repositories import (
        AsyncCorpus,
        AsyncCorpusService,
        AsyncDossierLoader,
        AsyncNotebookService,
        AsyncRelatedTopics,
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
    # A Module whose Source carried no retrievable text is listed and cannot be
    # chosen. Coverage is measured against the real notebook, not against the
    # part that happened to parse (PRD-0001 §16).
    selectable: bool = True
    stub_reason: str | None = None
    # uploaded | ingesting | ready | failed | stub. `ready` for everything in
    # the shipped Corpus and for every finished ingest; the others are
    # documents that are in the Library and not yet examinable (ISSUE-0035).
    state: str = "ready"
    # Sections embedded of sections found, for a document still being read.
    progress_done: int = 0
    progress_total: int = 0


class RelatedOut(BaseModel):
    """One neighbouring Topic, and enough to decide whether to show it."""

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

    #: What this scope costs in time (ISSUE-0040). `suggested_seconds` gives every
    #: Topic its own question; `minimum_seconds` is the floor below which some Topic
    #: goes unexamined however the Session is planned.
    suggested_seconds: int
    minimum_seconds: int
    questions_at_full_coverage: int

    # Deliberately absent: any difficulty figure, and any estimate of cost. A time
    # is neither — it is derived from the Topic count alone, which is a Coverage
    # fact, and never from how much text a Topic carries.


@router.get("/skills/tracks")
async def tracks(
    corpus_service: AsyncCorpusService = Depends(get_async_corpus_service),
) -> list[dict]:
    return corpus_service.tracks()


async def _visible_notebook_tracks(
    candidate_id: str,
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> set[str]:
    """Notebook tracks visible to this candidate."""
    from interviewer.service.notebooks.corpus_view import track_key

    records = await notebook_service.store.visible_to(candidate_id)
    return {track_key(r.notebook_id) for r in records}


async def _stub_modules(
    candidate_id: str | None,
    track: str | None,
    notebook_service: AsyncNotebookService,
) -> list[ModuleOut]:
    """Documents that are in the Library and are not examinable, and why."""
    if candidate_id is None:
        return []
    from interviewer.service.notebooks.corpus_view import track_key

    out: list[ModuleOut] = []
    records = await notebook_service.store.visible_to(candidate_id)
    for record in records:
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
    """Why a document that has not failed is still not selectable."""
    if source.state == "ingesting":
        return (
            f"still being read — {source.progress_done} of "
            f"{source.progress_total} sections embedded"
        )
    if source.state == "uploaded":
        return "uploaded, waiting to be read"
    return "not examinable"


async def _all_modules(
    track: str | None,
    corpus_service: AsyncCorpusService = Depends(get_async_corpus_service),
) -> list[ModuleOut]:
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
        for m in corpus_service.modules(track)
    ]


@router.get("/skills/modules", response_model=list[ModuleOut])
async def modules(
    track: str | None = None,
    candidate_id: str = Depends(current_candidate),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
    corpus_service: AsyncCorpusService = Depends(get_async_corpus_service),
) -> list[ModuleOut]:
    """The shipped Corpus, plus this Candidate's own notebooks and nobody else's."""
    visible = await _visible_notebook_tracks(candidate_id, notebook_service)
    listed = [
        m for m in await _all_modules(track, corpus_service)
        if not m.track_key.startswith("nb-") or m.track_key in visible
    ]
    return listed + await _stub_modules(candidate_id, track, notebook_service)


@router.get("/skills/scope", response_model=ScopeOut)
async def scope(
    module_id: list[str] = Query(default=[]),
    corpus_service: AsyncCorpusService = Depends(get_async_corpus_service),
) -> ScopeOut:
    s = corpus_service.scope(module_id)
    return ScopeOut(
        module_count=s.module_count,
        topic_count=s.topic_count,
        ground_truth_topic_count=s.ground_truth_topic_count,
        strongest_mode=s.strongest_mode.value if s.strongest_mode else None,
        suggested_seconds=pacing.suggested_seconds(s.topic_count),
        minimum_seconds=pacing.minimum_seconds(s.topic_count),
        questions_at_full_coverage=pacing.questions_at_full_coverage(s.topic_count),
    )


@router.get("/skills/provenance")
async def provenance(
    candidate_id: str = Depends(current_candidate),
    notebook_service: AsyncNotebookService = Depends(get_async_notebook_service),
) -> dict:
    """Which extract a Session ran against (PRD-0001 §13)."""
    from interviewer.db.content import SHARED

    shared = [
        corpus.provenance.model_dump()
        for record in await notebook_service.store.visible_to("")
        if record.visibility == SHARED
        and (corpus := await notebook_service.corpus(record.notebook_id)) is not None
    ]
    out = shared[0] if shared else {
        "source": "none", "extracted_at": "", "adapter": "none",
        "adapter_version": "1",
    }
    if len(shared) > 1:
        out["shared"] = shared
    if candidate_id is not None:
        out["notebooks"] = [
            corpus.provenance.model_dump()
            for record in await notebook_service.store.for_candidate(candidate_id)
            if (corpus := await notebook_service.corpus(record.notebook_id)) is not None
        ]
    return out


@router.get("/skills/topics/{topic_id}")
async def topic(
    topic_id: str,
    loader: AsyncDossierLoader = Depends(get_async_loader),
) -> dict:
    """Dossier metadata. Never the Ground Truth text — no Candidate-facing route
    returns grading material (ADR-0006)."""
    try:
        d = loader.load(topic_id)
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
    """A Module the chosen scope shares material with (ADR-0023)."""

    module_id: str
    title: str
    track_key: str
    in_scope: bool
    edges: int
    score: float
    selectable: bool


@router.get("/skills/scope/related", response_model=list[TouchedOut])
async def scope_related(
    module_id: list[str] = Query(default=[]),
    corpus: AsyncCorpus = Depends(get_async_corpus),
    related: AsyncRelatedTopics = Depends(get_async_related_topics),
) -> list[TouchedOut]:
    """Which Modules the chosen scope touches, ranked here rather than there."""
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


@router.get("/skills/topics/{topic_id}/related", response_model=list[RelatedOut])
async def related(
    topic_id: str,
    related: AsyncRelatedTopics = Depends(get_async_related_topics),
    corpus: AsyncCorpus = Depends(get_async_corpus),
) -> list[RelatedOut]:
    """What else relates to this Topic — the case ADR-0005 permitted alongside."""
    if topic_id not in {topic.id for topic in corpus.topics}:
        raise HTTPException(404, "unknown topic_id")
    return [RelatedOut(**row) for row in related.for_topic(topic_id)]