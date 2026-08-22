"""ISSUE-0021 — a Corpus nobody divided.

The Notebook Adapter's whole job is to manufacture the structure Cortex hands
us for free: Modules, Topics, order, and dossiers under budget. These tests are
the contract's generality being checked rather than asserted.
"""

from __future__ import annotations

import pytest

from interviewer.corpus.adapters.notebook import (
    HashingEmbedder,
    Notebook,
    Source,
    ingest_notebook,
)
from interviewer.corpus.conformance import validate
from interviewer.corpus.contract import GradingMode, LeafKind
from interviewer.corpus.loader import DossierLoader

ATTENTION = """# Attention

Attention scores every pair of positions in a sequence. The score is a dot
product between a query vector and a key vector, and the result decides how much
of each value vector flows forward. Nothing recurrent survives here; the whole
sequence is available at once, which is what made the architecture parallel.

## Scaling

Dot products grow with dimension. A query and key of dimension d_k produce a
score whose variance grows with d_k, and a large score saturates the softmax
until gradients vanish. Dividing by the square root of d_k keeps the variance
near one, which keeps the softmax in a region where it still has a gradient.

# Ensembles

Bagging trains many models on bootstrap resamples and averages them. Averaging
attacks variance: each model overfits its own resample differently, and the
differences cancel. It does nothing for bias, because every model in the
ensemble carries the same bias the base learner had.

## Boosting

Boosting fits models in sequence, each one on the errors of the last. It attacks
bias rather than variance, and it will happily overfit if left running, which is
why the number of rounds is the parameter that matters most.
"""


def _long(seed: str, sentences: int) -> str:
    """Prose with a stable vocabulary, long enough to become several chunks."""
    return " ".join(
        f"{seed} point {i} follows from the previous one and restates it."
        for i in range(sentences)
    )


#: Four themed sections, each large enough to chunk, so clustering has work to do.
NOTES = "\n\n".join(
    [
        "# Attention\n\n" + ATTENTION.split("# Ensembles")[0] + _long("attention softmax query key value", 60),
        "# Ensembles\n\n" + _long("bagging bootstrap variance averaging ensemble", 60),
        "# Optimisation\n\n" + _long("gradient descent learning rate momentum optimiser", 60),
        "# Evaluation\n\n" + _long("precision recall calibration threshold evaluation", 60),
    ]
)


def notebook(text: str = NOTES, *, title: str = "Revision notes") -> Notebook:
    return Notebook(
        notebook_id="nb-test",
        title="Test notebook",
        sources=(Source(source_id="s1", title=title, text=text),),
    )


@pytest.fixture(scope="module")
def ingested():
    return ingest_notebook(notebook(), embedder=HashingEmbedder())


# -- the contract ------------------------------------------------------------


def test_a_notebook_of_one_markdown_file_is_a_conformant_corpus(ingested):
    report = validate(ingested.corpus)
    assert report.violations == [], report.render()


def test_one_source_is_one_module(ingested):
    assert len(ingested.corpus.modules) == 1
    assert ingested.corpus.modules[0].title == "Revision notes"


def test_the_adapter_imports_no_other_adapter():
    """ADR-0007: an Adapter holds its own source's knowledge and nobody else's."""
    import ast
    import pathlib

    pkg = pathlib.Path(
        __file__
    ).resolve().parents[1] / "src" / "interviewer" / "corpus" / "adapters" / "notebook"
    for f in pkg.rglob("*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            for m in mods:
                assert "cortex" not in m, f"{f.name} -> {m}"
                assert "markdown_folder" not in m, f"{f.name} -> {m}"


# -- locators ----------------------------------------------------------------


def test_every_locator_reslices_its_source_exactly(ingested):
    for chunk in ingested.chunks:
        assert NOTES[chunk.char_start : chunk.char_end] == chunk.text


def test_chunks_cover_the_source_without_overlapping(ingested):
    spans = sorted((c.char_start, c.char_end) for c in ingested.chunks)
    for (_, end), (start, _) in zip(spans, spans[1:]):
        assert start >= end


# -- budget ------------------------------------------------------------------


def test_no_dossier_exceeds_the_budget(ingested):
    loader = DossierLoader(ingested.corpus)
    for topic in ingested.corpus.topics:
        assert loader.load(topic.id).approx_tokens <= 10_000


def test_ingest_reports_dossier_sizes(ingested):
    assert ingested.report.dossier_tokens["max"] > 0
    assert "median" in ingested.report.dossier_tokens


def test_a_source_smaller_than_one_chunk_yields_exactly_one_topic():
    out = ingest_notebook(
        notebook("A single short paragraph about bias and variance."),
        embedder=HashingEmbedder(),
    )
    assert len(out.corpus.topics) == 1
    assert validate(out.corpus).violations == []


def test_an_oversized_cluster_splits_at_a_chunk_boundary():
    """The splitter is arithmetic. It never divides a chunk."""
    big = "\n\n".join(f"Paragraph {i} about gradient descent. " * 40 for i in range(120))
    out = ingest_notebook(notebook(big), embedder=HashingEmbedder())
    loader = DossierLoader(out.corpus)
    for topic in out.corpus.topics:
        assert loader.load(topic.id).approx_tokens <= 10_000
    leaf_ids = [l.id for t in out.corpus.topics for l in t.leaves]
    assert len(leaf_ids) == len(set(leaf_ids))
    assert len(leaf_ids) == len(out.chunks)


# -- order -------------------------------------------------------------------


def test_topic_order_follows_the_earliest_chunk_not_the_clusterer(ingested):
    by_order = sorted(ingested.corpus.modules[0].topics, key=lambda t: t.order)
    earliest = [
        min(c.char_start for c in ingested.chunks if c.topic_id == t.id)
        for t in by_order
    ]
    assert earliest == sorted(earliest)


def test_leaves_within_a_topic_are_in_locator_order(ingested):
    for topic in ingested.corpus.topics:
        starts = [
            next(c for c in ingested.chunks if c.chunk_id == l.id).char_start
            for l in topic.leaves
        ]
        assert starts == sorted(starts)


def test_dossier_text_is_the_source_spans_concatenated(ingested):
    loader = DossierLoader(ingested.corpus)
    for topic in ingested.corpus.topics:
        dossier = loader.load(topic.id)
        spans = [
            NOTES[c.char_start : c.char_end]
            for c in sorted(
                (c for c in ingested.chunks if c.topic_id == topic.id),
                key=lambda c: c.char_start,
            )
        ]
        assert [l.text for l in dossier.content] == spans


# -- determinism -------------------------------------------------------------


def test_ingesting_the_same_notebook_twice_is_byte_identical():
    a = ingest_notebook(notebook(), embedder=HashingEmbedder())
    b = ingest_notebook(notebook(), embedder=HashingEmbedder())
    assert [t.id for t in a.corpus.topics] == [t.id for t in b.corpus.topics]
    assert a.corpus.model_dump() == b.corpus.model_dump()


def test_topic_ids_are_namespaced_to_their_notebook():
    a = ingest_notebook(notebook(), embedder=HashingEmbedder())
    b = ingest_notebook(
        Notebook(
            notebook_id="nb-other",
            title="Someone else's",
            sources=(Source(source_id="s1", title="Revision notes", text=ATTENTION),),
        ),
        embedder=HashingEmbedder(),
    )
    assert not {t.id for t in a.corpus.topics} & {t.id for t in b.corpus.topics}


# -- labelling ---------------------------------------------------------------


def test_a_failing_labeller_falls_back_and_ingest_still_completes():
    def explode(_texts):
        raise RuntimeError("provider down")

    out = ingest_notebook(notebook(), embedder=HashingEmbedder(), labeller=explode)
    assert validate(out.corpus).violations == []
    assert all(t.title.strip() for t in out.corpus.topics)
    assert out.report.labels_fell_back is True


def test_a_labeller_that_answers_is_used():
    out = ingest_notebook(
        notebook(),
        embedder=HashingEmbedder(),
        labeller=lambda texts: "Named by the model",
    )
    assert all(t.title == "Named by the model" for t in out.corpus.topics)
    assert out.report.labels_fell_back is False


# -- grading mode ------------------------------------------------------------


def test_this_slice_claims_no_ground_truth(ingested):
    assert all(
        t.grading_mode_ceiling is GradingMode.TEXT_GROUNDED
        for t in ingested.corpus.topics
    )
    assert all(
        l.kind is LeafKind.CONTENT for t in ingested.corpus.topics for l in t.leaves
    )


# -- the port ----------------------------------------------------------------


def test_the_embedder_is_reached_through_a_port():
    """Swapping the implementation touches no pipeline code."""
    calls = []

    class Counting(HashingEmbedder):
        def embed(self, texts):
            calls.append(len(texts))
            return super().embed(texts)

    out = ingest_notebook(notebook(), embedder=Counting())
    assert calls and sum(calls) == len(out.chunks)
