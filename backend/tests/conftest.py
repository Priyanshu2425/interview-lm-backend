import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend" / "src"))

from interviewer.corpus.adapters.cortex import ingest  # noqa: E402
from interviewer.corpus.loader import DossierLoader  # noqa: E402


@pytest.fixture(scope="session")
def corpus_path() -> Path:
    """Where the shipped Corpus lives, when there is one.

    It is not in this repository — `data/README.md` says why — so the tests that
    need it say so and skip, rather than failing with a file-not-found that
    looks like a bug in the code they were about to exercise. Everything that
    does not need it still runs: the embedder, the chunker, the confidence
    maths, and the whole notebook pipeline on its own fixtures.
    """
    path = Path(os.environ.get("CORPUS_PATH") or REPO / "data" / "corpus.json")
    if not path.exists():
        pytest.skip(
            f"no Corpus at {path} — see data/README.md. Set CORPUS_PATH to point "
            "at one, or run the tests that do not need it."
        )
    return path


@pytest.fixture(scope="session")
def corpus(corpus_path):
    return ingest(corpus_path)


@pytest.fixture(scope="session")
def loader(corpus):
    return DossierLoader(corpus)


# -- database fixtures -------------------------------------------------------

from interviewer.db.engine import create_core, create_graph, make_engine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def no_real_provider():
    """The suite never reaches a Provider.

    The stand-in used to be inherited from a missing OPENROUTER_API_KEY, which
    also meant a real deployment with only BYOK keys served scripted text. It is
    an explicit choice now, so the suite makes it explicitly.
    """
    os.environ["INTERVIEWER_FAKE_MODEL"] = "1"
    yield
    os.environ.pop("INTERVIEWER_FAKE_MODEL", None)


@pytest.fixture(scope="session")
def engine():
    e = make_engine()
    create_core(e)
    create_graph(e)
    return e


@pytest.fixture()
def clean_db(engine):
    """Each test starts from empty core tables."""
    from sqlalchemy import text

    with engine.begin() as c:
        c.execute(text(
            "TRUNCATE core.evidence, core.topic_confidence, core.topic_visit, "
            "core.session, core.identity, core.candidate, core.call_record, "
            "core.credit_ledger, core.byok_key, core.pool_ledger, "
            "core.corpus_version, "
            "core.visit_provider_binding RESTART IDENTITY CASCADE"
        ))
    return engine


@pytest.fixture()
def metered_deps(clean_db, loader, corpus):
    """Deps whose model calls run through the real metering chokepoint."""
    from decimal import Decimal

    import numpy as np

    from interviewer.confidence.selector import TopicSelector
    from interviewer.confidence.store import (
        ConfidenceStore, EvidenceLedger, VisitLifecycle,
    )
    from interviewer.corpus.service import CorpusService
    from interviewer.graph.machine import Deps
    from interviewer.graph.ports import FrozenClock, Ports
    from interviewer.graph.sessions import SessionStore
    from interviewer.judge.interviewer import Interviewer
    from interviewer.judge.judge import Judge
    from interviewer.judge.question_writer import QuestionWriter
    from interviewer.metering.client import BindingStore, MeteredModelClient
    from interviewer.metering.ledger import CreditLedger, PoolLedger
    from interviewer.metering.transport import ScriptedTransport

    ledger = CreditLedger(clean_db)
    transport = ScriptedTransport(cost_usd=Decimal("0.06"))
    metered = MeteredModelClient(clean_db, transport, ledger,
                                 key_resolver=lambda cid: "sk-or-candidate")
    d = Deps(
        ports=Ports(clock=FrozenClock(), rng=np.random.default_rng(3), model=metered),
        loader=loader,
        corpus=CorpusService(corpus),
        sessions=SessionStore(clean_db),
        visits=VisitLifecycle(clean_db),
        evidence=EvidenceLedger(clean_db),
        confidence=ConfidenceStore(clean_db),
        judge=Judge(),
        writer=QuestionWriter(),
        selector=TopicSelector(ConfidenceStore(clean_db)),
        interviewer=Interviewer(max_turns=4),
        credits=ledger,
        bindings=BindingStore(clean_db),
        metered=metered,
    )
    d.transport = transport            # test handle
    d.pool = PoolLedger(clean_db)
    return d


@pytest.fixture()
def deps(clean_db, loader, corpus):
    """A fully wired, fully deterministic set of dependencies."""
    from interviewer.confidence.store import (
        ConfidenceStore, EvidenceLedger, VisitLifecycle,
    )
    from interviewer.corpus.service import CorpusService
    from interviewer.graph.machine import Deps
    from interviewer.graph.ports import Ports, ScriptedModel
    from interviewer.graph.sessions import SessionStore
    from interviewer.judge.judge import Judge
    from interviewer.judge.question_writer import QuestionWriter
    from interviewer.confidence.selector import TopicSelector
    from interviewer.judge.interviewer import Interviewer

    model = ScriptedModel(
        replies={
            "question_writer": [],
            "judge": [],
        },
        default="SCORE: 0.8\nWHY: solid reasoning.",
    )
    return Deps(
        ports=Ports(clock=__import__("interviewer.graph.ports", fromlist=["x"]).FrozenClock(),
                    rng=__import__("numpy").random.default_rng(11),
                    model=model),
        loader=loader,
        corpus=CorpusService(corpus),
        sessions=SessionStore(clean_db),
        visits=VisitLifecycle(clean_db),
        evidence=EvidenceLedger(clean_db),
        confidence=ConfidenceStore(clean_db),
        judge=Judge(),
        writer=QuestionWriter(),
        selector=TopicSelector(ConfidenceStore(clean_db)),
        interviewer=Interviewer(max_turns=4),
    )


# -- notebooks ---------------------------------------------------------------


@pytest.fixture()
def content_db(engine):
    """The `content` schema, empty. Deliberately separate from `clean_db`:
    emptying notebook material must never be the same act as emptying Evidence.
    """
    from sqlalchemy import text

    from interviewer.db.engine import create_content

    create_content(engine)
    with engine.begin() as c:
        c.execute(text(
            "TRUNCATE content.notebook, content.notebook_source, "
            "content.notebook_topic, content.notebook_chunk CASCADE"
        ))
        # Corpus Version events are permanent and live in `core`. They are
        # emptied here too, because a test asserting "one event" must not be
        # reading another test's history.
        c.execute(text("TRUNCATE core.corpus_version RESTART IDENTITY"))
    return engine


@pytest.fixture()
def notebooks(content_db, counting):
    from interviewer.notebooks import NotebookService

    return NotebookService(content_db, embedder=counting)


@pytest.fixture(scope="session")
def real_notes() -> str:
    """Real prose, not lorem: several Cortex classes pasted into one document,
    which is what a Candidate's own notes actually look like to the Adapter."""
    files = sorted((REPO / "data" / "markdown" / "aiml").rglob("*.md"))[:25]
    return "\n\n".join(f.read_text() for f in files)


@pytest.fixture()
def counting():
    """An Embedder that records what it was asked to embed.

    Used where the assertion is about *not spending* — a deduplicated upload
    must reach no provider at all.
    """
    from interviewer.corpus.adapters.notebook import HashingEmbedder

    class Counting(HashingEmbedder):
        def __init__(self):
            super().__init__()
            self.calls = []

        def embed(self, texts):
            self.calls.append(len(texts))
            return super().embed(texts)

    return Counting()


@pytest.fixture()
def seeing():
    """An Embedder with an image tower, and no model behind it.

    A figure's vector is derived from its bytes, so two different pictures are
    two different vectors and the same picture twice is the same vector — which
    is all the pipeline actually asks of an image tower.
    """
    from interviewer.corpus.adapters.notebook import HashingEmbedder

    class Seeing(HashingEmbedder):
        model_name = "seeing-v1"
        supports_images = True

        def __init__(self):
            super().__init__()
            self.calls = []
            self.images = []

        def embed(self, texts):
            self.calls.append(len(texts))
            return super().embed(texts)

        def embed_images(self, images, hashes=None):
            self.images.append(len(images))
            return super().embed([data.hex()[:4096] for data in images])

    return Seeing()


@pytest.fixture()
def objects(tmp_path):
    """Figure bytes on disk. The same contract S3 answers, without a bucket."""
    from interviewer.embeddings.artifacts import LocalObjectStore

    return LocalObjectStore(tmp_path / "content")


@pytest.fixture()
def illustrated(content_db, seeing, objects):
    """A NotebookService with the figure lane switched on."""
    from interviewer.notebooks import NotebookService

    return NotebookService(
        content_db, embedder=seeing, objects=objects, images=True
    )
