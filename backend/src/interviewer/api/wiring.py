"""Builds the dependency graph the API serves from."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

import numpy as np

from interviewer.confidence.selector import TopicSelector
from interviewer.confidence.store import (
    ConfidenceStore, EvidenceLedger, VisitLifecycle,
)
from interviewer.confidence.summary import SummaryService
from interviewer.corpus.service import CorpusService
from interviewer.db.engine import create_content, create_core, make_engine
from interviewer.graph.machine import Deps
from interviewer.graph.ports import Ports, SystemClock
from interviewer.graph.runner import SessionRunner
from interviewer.graph.sessions import SessionStore
from interviewer.judge.interviewer import Interviewer
from interviewer.judge.judge import Judge
from interviewer.judge.question_writer import QuestionWriter
from interviewer.metering.client import BindingStore, MeteredModelClient
from interviewer.metering.keyvault import (
    AcceptingValidator, KeyVault, LocalKms, OpenRouterValidator,
)
from interviewer.metering.ledger import CreditLedger, PoolLedger
from interviewer.metering.transport import OpenRouterTransport, ScriptedTransport

from .deps import get_corpus, get_corpus_service, get_loader


@dataclass
class Wiring:
    engine: object
    deps: Deps
    runner: SessionRunner
    summary: SummaryService
    credits: CreditLedger
    pool: PoolLedger
    vault: KeyVault
    sessions: SessionStore


@lru_cache(maxsize=1)
def wiring() -> Wiring:
    engine = make_engine()
    create_core(engine)
    create_content(engine)

    corpus = get_corpus()
    loader = get_loader()
    confidence = ConfidenceStore(engine)
    visits = VisitLifecycle(engine)
    evidence = EvidenceLedger(engine)
    sessions = SessionStore(engine)
    credits = CreditLedger(engine)

    # The stand-in is chosen by an explicit flag, never by the absence of a
    # platform key. A BYOK Candidate supplies their own key per call, so a
    # deployment with no platform key at all is a real deployment — not a
    # reason to serve scripted text that looks like a model reply.
    key = os.environ.get("OPENROUTER_API_KEY", "")
    fake = os.environ.get("INTERVIEWER_FAKE_MODEL") == "1"
    transport = (
        ScriptedTransport(cost_usd=Decimal("0.06")) if fake
        else OpenRouterTransport(key)
    )
    vault = KeyVault(
        engine, LocalKms(),
        AcceptingValidator() if fake else OpenRouterValidator(),
    )
    metered = MeteredModelClient(
        engine, transport, credits, key_resolver=vault.resolver()
    )

    deps = Deps(
        ports=Ports(clock=SystemClock(), rng=np.random.default_rng(), model=metered),
        loader=loader,
        corpus=get_corpus_service(),
        sessions=sessions,
        visits=visits,
        evidence=evidence,
        confidence=confidence,
        judge=Judge(),
        writer=QuestionWriter(),
        selector=TopicSelector(confidence),
        interviewer=Interviewer(),
        credits=credits,
        bindings=BindingStore(engine),
        metered=metered,
    )
    return Wiring(
        engine=engine,
        deps=deps,
        runner=SessionRunner(deps),
        summary=SummaryService(corpus, confidence, visits, evidence, credits),
        credits=credits,
        pool=PoolLedger(engine),
        vault=vault,
        sessions=sessions,
    )
