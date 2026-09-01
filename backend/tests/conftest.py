import os
import sys
from pathlib import Path

import pytest

# --- the suite runs against the local Postgres, and only the local one -------
#
# `make_engine()` with no argument reads DATABASE_URL, so an exported one — the
# shared Neon URL this repo is provisioned on, say, exported to run an import —
# would silently point all 780 tests at production. They create schemas, insert
# eight hundred rows and drop what they made. This is not hypothetical: it
# happened to `cltv` on the same database.
#
# Cleared here, before anything imports the engine module or binds a DSN.
# `INTERVIEW_LM_TEST_ALLOW_REMOTE_DB=1` is the deliberate way past it.
# Keys wrapped in a test are read back in the same process and never again,
# so the suite opts in to a per-process key-encryption key rather than carrying
# a secret. A deployment that did this would lose every BYOK key at restart,
# which is why it has to be asked for.
os.environ.setdefault("BYOK_KEK_EPHEMERAL", "1")

if os.environ.get("INTERVIEW_LM_TEST_ALLOW_REMOTE_DB") != "1":
    for _var in ("DATABASE_URL", "GRAPH_DATABASE_URL", "INTERVIEW_LM_DATABASE_URL"):
        os.environ.pop(_var, None)

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend" / "src"))

from interviewer.adapters.interview_lm import ingest  # noqa: E402
from interviewer.service.corpus.loader import DossierLoader  # noqa: E402


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

from interviewer.db.content import CONTENT  # noqa: E402
from interviewer.db.engine import create_core, create_graph, make_engine  # noqa: E402
from interviewer.db.schema import CORE  # noqa: E402


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
    # `wiring()` builds its own engine and runs `create_content`'s migration
    # DDL on its first call, memoized after (`@lru_cache`) — cheap forever
    # after, but that first call needs an ACCESS EXCLUSIVE lock on `notebook`.
    # Left to happen lazily, the first caller can be a request whose own
    # async session already holds a read lock on that same table from an
    # earlier statement in the same request — a real deadlock, not a slow
    # query. Paying for it here, before any test opens a transaction, means
    # every in-request call after this one is instant and lock-free.
    from interviewer.wiring import wiring

    wiring()
    return e


@pytest.fixture()
def clean_db(engine):
    """Each test starts from empty core tables."""
    from sqlalchemy import text

    with engine.begin() as c:
        tables = ", ".join(f"{CORE}.{t}" for t in (
            "evidence", "topic_confidence", "topic_visit", "session", "identity",
            "candidate", "call_record", "credit_ledger", "byok_key",
            "pool_ledger", "corpus_version", "visit_provider_binding",
            # ISSUE-0039. A table left out of this list is a table that leaks
            # one test's rows into the next, which is a failure attributed to
            # whichever test happens to run second.
            "message", "plan_item", "session_plan",
        ))
        c.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    return engine


def session_grader(deps, *, provider: str = "deepseek"):
    """The real grader, built over whatever this `Deps` was given."""
    from interviewer.service.judge.session_grader import SessionGrader

    return SessionGrader(
        sessions=deps.sessions,
        visits=deps.visits,
        evidence=deps.evidence,
        loader=deps.loader,
        transcript=deps.transcript,
        judge=deps.judge,
        model=deps.ports.model,
        plans=deps.planner,
        bindings=deps.bindings,
        metered=deps.metered,
        provider=provider,
    )


def grade_session(deps, session_id: str, *, provider: str = "deepseek") -> list:
    """Grade a Session and write its Evidence — the real call, not a stand-in.

    ISSUE-0042 took grading out of the loop and this stood in for it; ISSUE-0044
    put it at the end of the Session, so this is now `SessionGrader.grade` under
    the name every test already calls. It is idempotent, so a test that runs a
    Session to its end — which grades it in the graph — and then calls this gets
    the same rows rather than a second set.
    """
    return session_grader(deps, provider=provider).grade(session_id)


@pytest.fixture()
def metered_deps(clean_db, loader, corpus):
    """Deps whose model calls run through the real metering chokepoint."""
    from decimal import Decimal

    import numpy as np

    from interviewer.service.confidence.selector import TopicSelector
    from interviewer.service.confidence.store import (
        ConfidenceStore, EvidenceLedger, VisitLifecycle,
    )
    from interviewer.service.corpus import CorpusService
    from interviewer.service.graph.machine import Deps
    from interviewer.service.graph.planner import PlanStore, SessionPlanner
    from interviewer.service.graph.ports import FrozenClock, Ports
    from interviewer.service.graph.sessions import SessionStore
    from interviewer.service.graph.transcript import Transcript
    from interviewer.service.judge.interviewer import Interviewer
    from interviewer.service.judge.judge import Judge
    from interviewer.service.judge.question_writer import QuestionWriter
    from interviewer.service.metering.client import BindingStore, MeteredModelClient
    from interviewer.service.metering.ledger import CreditLedger, PoolLedger
    from interviewer.service.metering.transport import ScriptedTransport

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
        transcript=Transcript(clean_db),
        selector=TopicSelector(ConfidenceStore(clean_db)),
        planner=SessionPlanner(
            loader=loader, corpus=CorpusService(corpus),
            selector=TopicSelector(ConfidenceStore(clean_db)),
            plans=PlanStore(clean_db),
        ),
        interviewer=Interviewer(max_turns=4),
        credits=ledger,
        bindings=BindingStore(clean_db),
        metered=metered,
    )
    d.grader = session_grader(d)
    d.transport = transport            # test handle
    d.pool = PoolLedger(clean_db)
    return d


@pytest.fixture()
def deps(clean_db, loader, corpus):
    """A fully wired, fully deterministic set of dependencies."""
    from interviewer.service.confidence.store import (
        ConfidenceStore, EvidenceLedger, VisitLifecycle,
    )
    from interviewer.service.corpus import CorpusService
    from interviewer.service.graph.machine import Deps
    from interviewer.service.graph.planner import PlanStore, SessionPlanner
    from interviewer.service.graph.ports import Ports, ScriptedModel
    from interviewer.service.graph.sessions import SessionStore
    from interviewer.service.graph.transcript import Transcript
    from interviewer.service.judge.judge import Judge
    from interviewer.service.judge.question_writer import QuestionWriter
    from interviewer.service.confidence.selector import TopicSelector
    from interviewer.service.judge.interviewer import Interviewer

    model = ScriptedModel(
        replies={
            "question_writer": [],
            "judge": [],
        },
        default="SOURCE: 0.8\nTRUTH: 0.8\nWHY: solid reasoning.",
    )
    d = Deps(
        ports=Ports(clock=__import__("interviewer.service.graph.ports", fromlist=["x"]).FrozenClock(),
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
        transcript=Transcript(clean_db),
        selector=TopicSelector(ConfidenceStore(clean_db)),
        planner=SessionPlanner(
            loader=loader, corpus=CorpusService(corpus),
            selector=TopicSelector(ConfidenceStore(clean_db)),
            plans=PlanStore(clean_db),
        ),
        interviewer=Interviewer(max_turns=4),
    )
    # The Session grades itself at its end (ISSUE-0044), so the fixture that
    # runs Sessions has to carry the thing that does it.
    d.grader = session_grader(d)
    return d


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
            f"TRUNCATE {CONTENT}.notebook, {CONTENT}.notebook_source, "
            f"{CONTENT}.notebook_topic, {CONTENT}.notebook_chunk CASCADE"
        ))
        # Corpus Version events are permanent and live in `core`. They are
        # emptied here too, because a test asserting "one event" must not be
        # reading another test's history.
        c.execute(text(f"TRUNCATE {CORE}.corpus_version RESTART IDENTITY"))
    return engine


@pytest.fixture()
def notebooks(content_db, counting):
    from interviewer.service.notebooks import NotebookService

    return NotebookService(content_db, embedder=counting)


@pytest.fixture(scope="session")
def real_notes() -> str:
    """Real prose, not lorem: several InterviewLM classes pasted into one document,
    which is what a Candidate's own notes actually look like to the Adapter."""
    files = sorted((REPO / "data" / "markdown" / "aiml").rglob("*.md"))[:25]
    return "\n\n".join(f.read_text() for f in files)


@pytest.fixture()
def counting():
    """An Embedder that records what it was asked to embed.

    Used where the assertion is about *not spending* — a deduplicated upload
    must reach no provider at all.
    """
    from interviewer.adapters.internal.notebook import HashingEmbedder

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
    from interviewer.adapters.internal.notebook import HashingEmbedder

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
    from interviewer.service.embeddings.artifacts import LocalObjectStore

    return LocalObjectStore(tmp_path / "content")


@pytest.fixture()
def illustrated(content_db, seeing, objects):
    """A NotebookService with the figure lane switched on."""
    from interviewer.service.notebooks import NotebookService

    return NotebookService(
        content_db, embedder=seeing, objects=objects, images=True
    )


@pytest.fixture()
def ingested():
    """Wait for a document to stop being in flight, the way the surface does.

    ISSUE-0035 separated the upload from the ingestion: `POST /sources` returns
    as soon as the bytes are durable, and the embedding runs in a thread. So a
    test that wants a Module has to do what the Library does — poll — rather
    than assume the work finished inside the request.
    """
    import time

    TERMINAL = {"ready", "failed", "stub"}

    def wait(client, notebook_id: str, source_id: str | None = None,
             *, timeout: float = 60.0) -> dict:
        deadline = time.monotonic() + timeout
        last: dict = {}
        while time.monotonic() < deadline:
            body = client.get(f"/v1/notebooks/{notebook_id}").json()
            sources = body["sources"]
            if source_id is not None:
                sources = [s for s in sources if s["source_id"] == source_id]
            last = sources[-1] if sources else {}
            if sources and all(s["state"] in TERMINAL for s in sources):
                return last
            time.sleep(0.02)
        raise AssertionError(f"ingest did not finish in {timeout}s: {last}")

    return wait


#: Where the imported Corpus is kept between tests. A separate schema, so that
#: `content_db` can empty `content` completely — a test asserting an empty picker
#: must see one — while the expensive part of the import survives.
TEMPLATE = "content_template"
SHIPPED = "nb-shipped"


@pytest.fixture(scope="session")
def shipped_template(engine, corpus_path):
    """Import the shipped Corpus once, and keep a copy to stamp out per test.

    ISSUE-0037 removed the disk path, so material reaches the API by being
    imported into Postgres — which makes "a Corpus the API serves" cost an
    embed and eight hundred inserts. Paying that once per test took the suite
    from 40 seconds to nearly two minutes, so it is paid once per session and
    copied with `INSERT ... SELECT` afterwards.
    """
    from sqlalchemy import text

    from interviewer.adapters.interview_lm import ingest as ingest_corpus
    from interviewer.adapters.internal.notebook import HashingEmbedder
    from interviewer.adapters.internal.notebook.structured import GivenLeaf, GivenTopic
    from interviewer.db.content import CONTENT, PLATFORM_OWNER, SHARED
    from interviewer.db.engine import create_content
    from interviewer.service.notebooks import NotebookService

    create_content(engine)
    corpus = ingest_corpus(corpus_path)
    track_of = {
        module.id: (track.key, track.title)
        for track in corpus.tracks
        for module in track.modules
    }
    with engine.begin() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {TEMPLATE} CASCADE"))
        c.execute(text(
            f"TRUNCATE {CONTENT}.notebook, {CONTENT}.notebook_source, "
            f"{CONTENT}.notebook_topic, {CONTENT}.notebook_chunk CASCADE"
        ))

    service = NotebookService(engine, embedder=HashingEmbedder())
    service.create(
        SHIPPED, PLATFORM_OWNER, "InterviewLM", visibility=SHARED,
        provenance=corpus.provenance.model_dump(),
    )
    for module in corpus.modules:
        key, title = track_of[module.id]
        service.import_structured(
            SHIPPED,
            source_id=f"src-{module.id}",
            title=module.title,
            module_id=module.id,
            track_key=key,
            track_title=title,
            topics=[
                GivenTopic(
                    topic_id=topic.id,
                    title=topic.title,
                    order=topic.order,
                    leaves=tuple(
                        GivenLeaf(
                            leaf_id=leaf.id,
                            title=leaf.title,
                            text=leaf.text or "",
                            kind=leaf.kind.value,
                            answers_leaf_id=leaf.answers_leaf_id,
                        )
                        for leaf in topic.leaves
                    ),
                )
                for topic in module.topics
            ],
            as_operator=True,
        )

    tables = ("notebook", "notebook_source", "notebook_topic", "notebook_chunk")
    with engine.begin() as c:
        c.execute(text(f"CREATE SCHEMA {TEMPLATE}"))
        for table in tables:
            c.execute(text(
                f"CREATE TABLE {TEMPLATE}.{table} AS "  # noqa: S608
                f"SELECT * FROM {CONTENT}.{table}"
            ))
    yield tables
    with engine.begin() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {TEMPLATE} CASCADE"))


@pytest.fixture()
def served_corpus(content_db, shipped_template):
    """The shipped Corpus, served from rows, restored from the template.

    Ordering matters and is why `content_db` comes first: it empties `content`,
    and this fills it back in. In the order the arguments are declared.
    """
    from sqlalchemy import text

    from interviewer import deps
    from interviewer.db.content import CONTENT

    with content_db.begin() as c:
        for table in shipped_template:
            c.execute(text(
                f"INSERT INTO {CONTENT}.{table} SELECT * FROM {TEMPLATE}.{table}"
            ))
    deps.refresh_corpus()
    yield SHIPPED
    deps.refresh_corpus()


# --- signed in -------------------------------------------------------------
#
# Every Candidate-scoped endpoint resolves the Candidate from a Gatehouse token
# (ADR-0026), so a client that presents none is refused before the route runs.
# These tests are not about authentication — `test_token_verification.py` and
# `test_api_authentication.py` are — so they sign in by overriding the one
# dependency, and say so at the call site rather than carrying a fake token.
#
# The default subject is the id the fixtures already use.
SIGNED_IN_CANDIDATE = "cand_test"


def signed_in_client(candidate_id: str = SIGNED_IN_CANDIDATE):
    """A TestClient whose requests arrive already authenticated."""
    from fastapi.testclient import TestClient

    from interviewer.app import create_app
    from interviewer.security.auth import current_candidate

    application = create_app()
    application.dependency_overrides[current_candidate] = lambda: candidate_id
    return TestClient(application)
