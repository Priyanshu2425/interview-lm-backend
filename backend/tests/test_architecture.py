"""Rules that decay in exactly one careless import, enforced statically."""

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "interviewer"


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


#: The one file outside `metering` allowed to open a socket, and it is named
#: rather than its package widened. An embedding call is metered too (ADR-0016),
#: but it is not a chat completion and cannot go through the chat transport; the
#: exemption is this file, so the next network import anywhere else still fails.
_NETWORK_EXEMPT = {"embeddings/http.py"}


def test_no_module_outside_metering_constructs_a_provider_client():
    """SPEC-0005: an unmetered call must be impossible, not discouraged."""
    offenders = []
    for f in SRC.rglob("*.py"):
        if "metering" in f.parts:
            continue
        if f.relative_to(SRC).as_posix() in _NETWORK_EXEMPT:
            continue
        for mod in _imports(f):
            if mod.split(".")[0] in {"httpx", "openai", "anthropic", "requests"}:
                offenders.append(f"{f.relative_to(SRC)} imports {mod}")
    assert not offenders, offenders


def test_confidence_math_depends_on_nothing_in_the_system():
    """PRD-0002 calls it the deepest module; the boundary erodes first."""
    math = SRC / "confidence" / "math.py"
    for mod in _imports(math):
        assert not mod.startswith("interviewer"), mod
        assert "graph" not in mod and "db" not in mod, mod


def test_the_confidence_package_never_imports_the_graph():
    for f in (SRC / "confidence").glob("*.py"):
        for mod in _imports(f):
            assert "interviewer.graph" not in mod, f"{f.name} -> {mod}"
            assert not mod.startswith("..graph"), f"{f.name} -> {mod}"


def test_the_corpus_package_knows_nothing_about_sessions_or_credits():
    """ADR-0007: the Corpus is source material, not the system."""
    for f in (SRC / "corpus").rglob("*.py"):
        for mod in _imports(f):
            for forbidden in ("graph", "metering", "judge", "db"):
                assert forbidden not in mod, f"{f.name} -> {mod}"


def test_cortex_vocabulary_does_not_leak_past_its_adapter():
    """Answer Key, Assignment, Class and contest are one source's words."""
    adapter = SRC / "corpus" / "adapters" / "cortex.py"
    leaks = []
    for f in SRC.rglob("*.py"):
        if f == adapter or "tests" in f.parts:
            continue
        src = f.read_text()
        # strip comments and docstrings: prose may reference the domain freely
        tree = ast.parse(src)
        code_ids = {
            n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
        } | {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        }
        for word in ("answerKeyId", "assignmentId", "contestSyllabus",
                     "markdownPath", "contentType"):
            if word in code_ids:
                leaks.append(f"{f.relative_to(SRC)}: {word}")
    assert not leaks, leaks


def test_nothing_reaches_for_the_clock_or_randomness_outside_ports():
    """Determinism is a property of the code, not of discipline."""
    # ports.py defines the injection points; wiring.py is the composition root
    # where the real world is assembled once; client.py times latency only.
    #
    # base.py jitters a retry backoff. The rule protects the reproducibility of
    # an interview — same seed, same Session — and how long a failed embedding
    # call waits before the next attempt is not part of that: it changes no
    # vector, no Topic and no score. Unjittered, several workers recovering
    # together would synchronise into a second stampede.
    allowed = {"ports.py", "client.py", "wiring.py", "base.py"}
    offenders = []
    for f in SRC.rglob("*.py"):
        if f.name in allowed:
            continue
        src = f.read_text()
        for bad in ("time.time(", "datetime.now(", "random.random(",
                    "np.random.default_rng("):
            if bad in src:
                offenders.append(f"{f.relative_to(SRC)}: {bad}")
    assert not offenders, offenders


def test_the_corpus_never_imports_a_concrete_embedder():
    """ADR-0007: the Corpus is source material, not the system.

    `corpus/` owns the *port*. The moment it imports the package that loads
    weights and opens sockets, the Adapter stops being testable without them
    and the arrow between them has quietly reversed.
    """
    for f in (SRC / "corpus").rglob("*.py"):
        for mod in _imports(f):
            assert "embeddings" not in mod.split("."), f"{f.name} -> {mod}"


def test_importing_the_app_loads_no_machine_learning_stack():
    """The default deployment runs the stub; it must not pay for the model.

    torch and transformers are ~2.5GB of import. They belong inside `warm()`,
    which is called by the lifespan when a deployment asks for it and by
    nothing else — so importing the API must leave them absent.
    """
    import subprocess
    import sys

    probe = (
        "import sys; import interviewer.api.app as app; "
        "app.create_app(); "
        "print(sorted(m for m in ('torch', 'transformers') if m in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]", out.stdout


def test_every_provider_satisfies_the_port_it_is_injected_through():
    """`BaseEmbedder` is a base, not a second contract.

    A subclass that stopped satisfying `Embedder` would still construct, still
    register, and fail only where it is finally injected — which is inside an
    ingest, holding a Candidate's upload.
    """
    from interviewer.corpus.adapters.notebook.embedding import Embedder
    from interviewer.embeddings import make_embedder, registered

    for name in registered():
        embedder = make_embedder({"EMBEDDING_PROVIDER": name})
        assert isinstance(embedder, Embedder), name
        if getattr(embedder, "supports_images", False):
            from interviewer.corpus.adapters.notebook.embedding import ImageEmbedder

            assert isinstance(embedder, ImageEmbedder), name
