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
#: The provider transport moved to `adapters/` with ADR-0027 — it talks to a
#: system we do not own, which is what that directory is now for. The rule it
#: was exempted from is unchanged: this is still the *only* module outside
#: metering that may hold an HTTP client to a provider, and `MeteredModelClient`
#: is still its only caller.
_NETWORK_EXEMPT = {
    "embeddings/http.py", "service/embeddings/http.py",
    "adapters/openrouter.py",
}


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
    math = SRC / "model" / "confidence_models.py"
    for mod in _imports(math):
        assert not mod.startswith("interviewer"), mod
        assert "graph" not in mod and "db" not in mod, mod


def test_the_confidence_package_never_imports_the_graph():
    for f in (SRC / "service" / "confidence").glob("*.py"):
        for mod in _imports(f):
            assert "interviewer.graph" not in mod, f"{f.name} -> {mod}"
            assert not mod.startswith("..graph"), f"{f.name} -> {mod}"


def test_the_corpus_package_knows_nothing_about_sessions_or_credits():
    """ADR-0007: the Corpus is source material, not the system."""
    for f in (SRC / "corpus").rglob("*.py"):
        for mod in _imports(f):
            for forbidden in ("graph", "metering", "judge", "db"):
                assert forbidden not in mod, f"{f.name} -> {mod}"


def test_source_vocabulary_does_not_leak_past_its_adapter():
    """Answer Key, Assignment, Class and contest are one source's words."""
    adapter = SRC / "adapters" / "interview_lm.py"
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
    allowed = {
        "ports.py",
        "client.py",
        "wiring.py",
        "base.py",
        # Middleware needs real time for rate limiting (sliding window) and
        # request logging (timing). These are infrastructure concerns at the
        # HTTP layer, similar to client.py's retry backoff timing.
        "rate_limit.py",
        "request_logging.py",
    }
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
        "import sys; import interviewer.app as app; "
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
    from interviewer.service.embeddings.hashing import Embedder
    from interviewer.service.embeddings import make_embedder, registered

    for name in registered():
        embedder = make_embedder({"EMBEDDING_PROVIDER": name})
        assert isinstance(embedder, Embedder), name
        if getattr(embedder, "supports_images", False):
            from interviewer.service.embeddings.hashing import ImageEmbedder

            assert isinstance(embedder, ImageEmbedder), name


def test_the_session_grader_assembles_no_probe_and_no_hint():
    """ADR-0002, where it is newly at risk (ISSUE-0044).

    Grading at the end reads the transcript, and the transcript holds every
    probe and hint the Interviewer spent. The bundle handed to the Judge is
    built from one named kind — the question — and the Candidate's turns, so
    the only way a probe reaches a grader is for this file to start naming
    kinds it currently does not. Asserted rather than trusted, because the
    failure is silent: a Judge shown the hints grades the help.
    """
    grader = SRC / "service" / "judge" / "session_grader_service.py"
    tree = ast.parse(grader.read_text())
    literals = {
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and "\n" not in n.value          # docstrings and prose are free
    }
    assert "probe" not in literals and "hint" not in literals
    assert "question" in literals       # the one interviewer kind it reads


#: What `adapters/` is allowed to be about (ADR-0027): one file per system we
#: do not own. Adding a file here means adding a dependency on somebody else's
#: uptime, so the list is written down rather than inferred.
_FOREIGN_SYSTEMS = {"gatehouse.py", "openrouter.py", "s3.py"}


def test_adapters_holds_foreign_systems_and_nothing_else():
    """ADR-0027: the directory answers one question — what do we depend on that
    we do not control? The notebook ingest pipeline lived here and answered it
    wrongly, because nothing is on the other side of it."""
    found = {
        f.name for f in (SRC / "adapters").glob("*.py") if f.name != "__init__.py"
    }
    assert found == _FOREIGN_SYSTEMS, found


def test_a_corpus_source_is_not_an_adapter_directory():
    """The *word* Adapter still means a Corpus Source (ADR-0007, CONTEXT.md).
    The three implementations live beside the contract they satisfy."""
    sources = SRC / "service" / "corpus" / "sources"
    assert (sources / "interview_lm.py").is_file()
    assert (sources / "markdown_folder.py").is_file()
    assert (sources / "notebook").is_dir()
    assert (SRC / "service" / "corpus" / "conformance.py").is_file()


def test_every_embedder_lives_with_the_other_embedders():
    """ADR-0027: `HashingEmbedder` sat under `adapters/` while `SiglipEmbedder`
    sat under `service/embeddings/`, so the registry imported back out of the
    adapters tree to build its default."""
    from interviewer.service.embeddings.hashing import HashingEmbedder  # noqa: F401

    strays = [
        f"{f.relative_to(SRC)} -> {mod}"
        for f in SRC.rglob("*.py")
        for mod in _imports(f)
        if "adapters" in mod and "embedd" in mod
    ]
    assert not strays, strays
