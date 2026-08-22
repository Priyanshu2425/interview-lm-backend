"""The real model, when someone asks for it.

Everything else about the embedder is tested against stubs, deliberately: the
suite must stay fast and must not download 1.5GB. But a stub cannot tell you
that `padding="max_length"` is the right call, that `get_text_features` returns
a pooled vector rather than one per token, or that the checkpoint really is 768
dimensions wide.

    INTERVIEWER_MODEL_TESTS=1 .venv/bin/python -m pytest backend/tests/test_siglip_integration.py

Off by default, and skipped rather than failed when the extra is not installed.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("INTERVIEWER_MODEL_TESTS") != "1",
    reason="set INTERVIEWER_MODEL_TESTS=1 to run against real weights",
)

CHECKPOINT = "google/siglip2-base-patch16-224"


@pytest.fixture(scope="module")
def model():
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from interviewer.embeddings import make_embedder

    embedder = make_embedder({
        "EMBEDDING_PROVIDER": "siglip",
        "EMBEDDING_MODEL": CHECKPOINT,
        "EMBEDDING_DIM": "768",
    })
    embedder.warm()
    yield embedder
    embedder.close()


def test_the_checkpoint_is_the_width_the_column_expects(model):
    from interviewer.db.content import EMBEDDING_DIM

    (vector,) = model.embed(["a short passage about attention"])
    assert len(vector) == EMBEDDING_DIM


def test_vectors_are_unit_length(model):
    (vector,) = model.embed(["gradients flow backwards through the graph"])
    assert sum(x * x for x in vector) == pytest.approx(1.0, abs=1e-4)


def test_the_whole_chunk_reaches_the_real_tokenizer(model):
    """Window pooling, proved against the tokenizer rather than a stub.

    Both inputs are identical for their first 64 tokens. Under truncation their
    cosine would be 1.0 and every downstream number would be computed from a
    tenth of each chunk.
    """
    head = "Attention weights every token against every other token. "
    a = head + "The chain rule propagates gradients backwards. " * 40
    b = head + "Convolutional kernels slide across the input plane. " * 40
    va, vb = model.embed([a, b])
    similarity = sum(x * y for x, y in zip(va, vb))
    assert similarity < 0.99, "the tails were discarded — pooling is not running"


def test_identical_text_is_identical_vectors(model):
    """Determinism, and the padding mode that guarantees it."""
    first, second = model.embed(["the same passage twice", "the same passage twice"])
    assert first == pytest.approx(second, abs=1e-5)


def test_the_image_tower_answers_in_the_same_space(model):
    from PIL import Image
    import io

    def png(colour):
        buffer = io.BytesIO()
        Image.new("RGB", (224, 224), colour).save(buffer, format="PNG")
        return buffer.getvalue()

    blue, red = model.embed_images([png((10, 30, 200)), png((200, 20, 10))])
    assert len(blue) == len(red) == 768
    assert sum(x * x for x in blue) == pytest.approx(1.0, abs=1e-4)
    # Different pictures are different vectors; that is all the pipeline needs.
    assert sum(x * y for x, y in zip(blue, red)) < 0.999


def test_a_corrupt_image_is_refused_rather_than_embedded(model):
    from interviewer.embeddings.errors import EmbeddingContractError

    with pytest.raises(EmbeddingContractError):
        model.embed_images([b"this is not a png"])


# -- the Corpus index, and whether its neighbours mean anything --------------

def test_related_topics_beat_chance_by_a_wide_margin(model):
    """The measurement that made mean-centring non-optional.

    A caption-trained text tower maps long technical prose into a very narrow
    cone, so raw cosines between Topics all sat between 0.974 and 0.998 and the
    ranking was noise: "NumPy" came back nearest to "CNN Fundamentals". Centring
    on the Corpus mean restores the spread.

    The proxy for "is this neighbour real" is the Track. DSA and AIML are
    genuinely different subjects, so a cross-Track neighbour is nearly always
    wrong. Picking at random scores about 68%; the raw space scored 86%; centred
    scores in the low nineties. The floor below is set under the measured value
    with room for model and tokenizer drift — it exists to catch the space
    collapsing again, not to pin a number.
    """
    from pathlib import Path

    from interviewer.corpus.adapters.cortex import ingest
    from interviewer.corpus.index import build

    corpus = ingest(Path(__file__).resolve().parents[2] / "data" / "corpus.json")
    index = build(corpus, model)
    track_of = {
        topic.id: track.key
        for track in corpus.tracks
        for module in track.modules
        for topic in module.topics
    }

    hits = total = 0
    for topic_id, neighbours in index.related.items():
        for neighbour in neighbours:
            total += 1
            hits += track_of[topic_id] == track_of[neighbour.topic_id]

    assert total > 300, "the Corpus should yield roughly five edges per Topic"
    assert hits / total > 0.85, (
        f"neighbours are {hits / total:.0%} same-Track, barely above the ~68% "
        "chance rate — the embedding space has collapsed again"
    )


def test_the_index_spreads_out_once_centred(model):
    """Directly: the cone is real, and centring opens it."""
    from pathlib import Path

    from interviewer.corpus.adapters.cortex import ingest
    from interviewer.corpus.index import build, centre

    corpus = ingest(Path(__file__).resolve().parents[2] / "data" / "corpus.json")
    index = build(corpus, model)
    ids = sorted(index.centroids)[:30]

    def cos(a, b):
        return sum(x * y for x, y in zip(a, b))

    raw = [
        cos(index.centroids[a], index.centroids[b])
        for i, a in enumerate(ids) for b in ids[i + 1:]
    ]
    centred = [
        cos(centre(index.centroids[a], index.mean), centre(index.centroids[b], index.mean))
        for i, a in enumerate(ids) for b in ids[i + 1:]
    ]
    assert max(raw) - min(raw) < 0.1, "the raw space is expected to be collapsed"
    assert max(centred) - min(centred) > 0.5
