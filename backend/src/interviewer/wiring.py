"""The composition root: one provider per thing, built when first asked for.

Everything here lives for the length of the process. Request-scoped objects —
anything bound to an `AsyncSession` — belong in `deps_async.py` and never here;
a session cached in a singleton outlives the context that opened it.

`Wiring` is a facade over the providers, not a container built ahead of them.
That is the whole point: a route that wants the Key Vault gets the Key Vault,
not both engines, the Corpus, the embedder, the LangGraph runner and every
failure mode any of those has on a cold process. `wiring().vault` still reads
the same at all its call sites.
"""

from __future__ import annotations

import os
from decimal import Decimal
from functools import lru_cache

import numpy as np

from interviewer.service.confidence.selector import TopicSelector
from interviewer.service.confidence.store import (
    ConfidenceStore, EvidenceLedger, VisitLifecycle,
)
from interviewer.service.confidence.reading import SessionReadingService
from interviewer.service.confidence.summary import CandidateReadings
from interviewer.db.engine import create_content, create_core, make_engine
from interviewer.db.engine_async import make_async_engine
from interviewer.service.graph.machine import Deps
from interviewer.service.graph.planner import PlanStore, SessionPlanner
from interviewer.service.graph.ports import Ports, SystemClock
from interviewer.service.graph.runner import SessionRunner
from interviewer.service.graph.sessions import SessionStore
from interviewer.service.graph.transcript import Transcript
from interviewer.service.judge.interviewer import Interviewer
from interviewer.service.judge.judge import Judge
from interviewer.service.judge.question_writer import QuestionWriter
from interviewer.service.ending import SessionEnding
from interviewer.service.judge.session_grader import SessionGrader
from interviewer.service.metering.client import BindingStore, MeteredModelClient
from interviewer.service.metering.keyvault import (
    AcceptingValidator, KeyVault, LocalKms, OpenRouterValidator,
)
from interviewer.service.metering.ledger import CreditLedger, PoolLedger
from interviewer.service.metering.transport import OpenRouterTransport, ScriptedTransport

from .deps import get_corpus, get_corpus_service, get_loader


def _fake_model() -> bool:
    """Whether this process talks to a scripted model instead of a provider."""
    return os.environ.get("INTERVIEWER_FAKE_MODEL") == "1"


# -- engines and schema ------------------------------------------------------


def apply_schema(engine) -> None:
    """The `core` and `content` trees, idempotently.

    Called at boot by `app.lifespan`, so a deployment applies its schema before
    it takes traffic rather than on whichever request happens to be first. Also
    called by `sync_engine()` below, because scripts, the CLI and the test suite
    reach the database without ever running a lifespan.
    """
    create_core(engine)
    create_content(engine)


@lru_cache(maxsize=1)
def sync_engine():
    """The sync engine. LangGraph's checkpointer needs one, and every service
    predating the async split takes one positionally."""
    engine = make_engine()
    apply_schema(engine)
    return engine


@lru_cache(maxsize=1)
def async_engine():
    return make_async_engine()


# -- stores ------------------------------------------------------------------


@lru_cache(maxsize=1)
def confidence_store() -> ConfidenceStore:
    return ConfidenceStore(sync_engine())


@lru_cache(maxsize=1)
def visit_lifecycle() -> VisitLifecycle:
    return VisitLifecycle(sync_engine())


@lru_cache(maxsize=1)
def evidence_ledger() -> EvidenceLedger:
    return EvidenceLedger(sync_engine())


@lru_cache(maxsize=1)
def session_store() -> SessionStore:
    return SessionStore(sync_engine())


@lru_cache(maxsize=1)
def plan_store() -> PlanStore:
    return PlanStore(sync_engine())


@lru_cache(maxsize=1)
def transcript_store() -> Transcript:
    return Transcript(sync_engine())


@lru_cache(maxsize=1)
def credit_ledger() -> CreditLedger:
    return CreditLedger(sync_engine())


@lru_cache(maxsize=1)
def pool_ledger() -> PoolLedger:
    return PoolLedger(sync_engine())


# -- metering ----------------------------------------------------------------


@lru_cache(maxsize=1)
def transport():
    if _fake_model():
        return ScriptedTransport(cost_usd=Decimal("0.06"))
    return OpenRouterTransport(os.environ.get("OPENROUTER_API_KEY", ""))


@lru_cache(maxsize=1)
def vault() -> KeyVault:
    return KeyVault(
        sync_engine(),
        LocalKms(),
        AcceptingValidator() if _fake_model() else OpenRouterValidator(),
    )


@lru_cache(maxsize=1)
def metered_client() -> MeteredModelClient:
    """The one chokepoint an unmetered call cannot get past."""
    return MeteredModelClient(
        sync_engine(),
        transport(),
        credit_ledger(),
        key_resolver=vault().resolver(),
    )


# -- the graph ---------------------------------------------------------------


@lru_cache(maxsize=1)
def session_grader() -> SessionGrader:
    """Grades a finished Session. Built outside `graph_deps` because three
    callers reach for it — the graph, `/end` and the resumption path — and only
    one of them is a graph node."""
    return SessionGrader(
        sessions=session_store(),
        visits=visit_lifecycle(),
        evidence=evidence_ledger(),
        loader=get_loader(),
        transcript=transcript_store(),
        judge=Judge(),
        model=metered_client(),
        plans=plan_store(),
        bindings=BindingStore(sync_engine()),
        metered=metered_client(),
    )


@lru_cache(maxsize=1)
def session_ending() -> SessionEnding:
    """How a Session ends. One instance, because all three callers of it — the
    graph node, `/end` and the resumption path — must end one the same way."""
    return SessionEnding(
        sessions=session_store(),
        grader=session_grader(),
        plans=plan_store(),
    )


@lru_cache(maxsize=1)
def graph_deps() -> Deps:
    """What the graph nodes reach for.

    Held rather than discarded after building the runner: `deps.refresh_corpus`
    reads `visits.open_topic_ids()` off it to keep a Topic loadable while a
    Visit is still open on it (ISSUE-0027).
    """
    confidence = confidence_store()
    return Deps(
        ports=Ports(
            clock=SystemClock(), rng=np.random.default_rng(), model=metered_client()
        ),
        loader=get_loader(),
        corpus=get_corpus_service(),
        sessions=session_store(),
        visits=visit_lifecycle(),
        evidence=evidence_ledger(),
        confidence=confidence,
        judge=Judge(),
        writer=QuestionWriter(),
        transcript=transcript_store(),
        selector=TopicSelector(confidence),
        planner=SessionPlanner(
            loader=get_loader(),
            corpus=get_corpus_service(),
            selector=TopicSelector(confidence),
            plans=plan_store(),
        ),
        interviewer=Interviewer(),
        grader=session_grader(),
        ending=session_ending(),
        credits=credit_ledger(),
        bindings=BindingStore(sync_engine()),
        metered=metered_client(),
    )


@lru_cache(maxsize=1)
def runner() -> SessionRunner:
    return SessionRunner(graph_deps())


@lru_cache(maxsize=1)
def candidate_readings() -> CandidateReadings:
    """Coverage and Mastery across every Session a Candidate has sat."""
    return CandidateReadings(get_corpus(), confidence_store())


@lru_cache(maxsize=1)
def session_reading() -> SessionReadingService:
    """One read of a Session, projected into the plan, the report and the
    summary. Four endpoints used to assemble those separately and disagree.

    Takes the loader rather than a Corpus for titles, so `refresh_corpus`
    swapping the material under a running process reaches it without a second
    rebind; the Corpus itself is held for Module structure and is rebound.
    """
    return SessionReadingService(
        sessions=session_store(),
        visits=visit_lifecycle(),
        evidence=evidence_ledger(),
        plans=plan_store(),
        loader=get_loader(),
        confidence=confidence_store(),
        corpus=get_corpus(),
        credits=credit_ledger(),
    )


#: Every provider above, in one place, so `wiring.cache_clear()` empties the
#: process rather than only the facade in front of it.
_PROVIDERS = (
    sync_engine, async_engine, confidence_store, visit_lifecycle, evidence_ledger,
    session_store, plan_store, transcript_store, credit_ledger, pool_ledger,
    transport, vault,
    metered_client, session_grader, session_ending, graph_deps, runner,
    candidate_readings, session_reading,
)


class Wiring:
    """Names the providers under the names the call sites already use.

    Every attribute is a property, so reading one builds one.
    """

    __slots__ = ()

    @property
    def sync_engine(self):
        return sync_engine()

    @property
    def async_engine(self):
        return async_engine()

    @property
    def engine(self):
        """The sync engine, under the name the sync services ask for.

        `IdentityStore`, `OperatorService` and `PriceService` are sync and take
        an engine positionally; they predate the async split and there is
        exactly one engine they can mean.
        """
        return sync_engine()

    @property
    def runner(self) -> SessionRunner:
        return runner()

    @property
    def grader(self) -> SessionGrader:
        return session_grader()

    @property
    def ending(self) -> SessionEnding:
        """How a Session ends — the one `/end` and the graph both close through."""
        return session_ending()

    @property
    def readings(self) -> CandidateReadings:
        """What is true of a Candidate, not of one Session."""
        return candidate_readings()

    @property
    def reading(self) -> SessionReadingService:
        """One Session, read once — the plan, the report and the summary."""
        return session_reading()

    @property
    def deps(self) -> Deps:
        return graph_deps()

    @property
    def credits(self) -> CreditLedger:
        return credit_ledger()

    @property
    def pool(self) -> PoolLedger:
        return pool_ledger()

    @property
    def vault(self) -> KeyVault:
        return vault()

    @property
    def sessions(self) -> SessionStore:
        return session_store()


@lru_cache(maxsize=1)
def wiring() -> Wiring:
    """The facade. Cheap: it builds nothing until something is read off it."""
    return Wiring()


def _clear_everything() -> None:
    """Empty every provider, not just the facade.

    `wiring.cache_clear()` is what the test suite calls between databases, and
    clearing only the facade would hand the next test the previous engine.
    """
    for provider in _PROVIDERS:
        provider.cache_clear()
    _clear_facade()


_clear_facade = wiring.cache_clear
wiring.cache_clear = _clear_everything


def built() -> bool:
    """Whether the graph's `Deps` exist yet.

    `refresh_corpus` asks before reaching for them, so rebuilding a Corpus on a
    process that has never run a Session does not construct a runner in order
    to tell it nothing changed.
    """
    return bool(graph_deps.cache_info().currsize)
