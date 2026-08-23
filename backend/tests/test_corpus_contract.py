"""ISSUE-0001 — the Adapter contract, tested through the real Corpus.

These assert what an Adapter author or an auditor would observe: what ingest
accepted, what it refused, and what came back for a topic_id. They do not assert
how the adapter walks the JSON.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from interviewer.corpus.adapters.interview_lm import AdapterError, ingest
from interviewer.corpus.contract import (
    Corpus,
    CorpusProvenance,
    GradingMode,
    Leaf,
    LeafKind,
    Module,
    Topic,
    Track,
)
from interviewer.corpus.loader import DossierLoader, TopicNotFound


# -- the real Corpus ingests, and reports what the documents claim -----------

def test_real_corpus_ingests_with_the_shape_the_documents_state(corpus):
    assert len(corpus.tracks) == 2
    assert len(corpus.modules) == 15
    assert len(corpus.topics) == 71


def test_ground_truth_pairs_match_the_recorded_count_and_distribution(corpus):
    assert sum(len(t.ground_truth_pairs) for t in corpus.topics) == 26

    aiml = next(t for t in corpus.tracks if t.key == "aiml")
    per_module = [m.ground_truth_topic_count for m in aiml.modules]
    assert per_module == [4, 5, 5, 5, 4, 3, 0, 0]

    dsa = next(t for t in corpus.tracks if t.key == "dsa")
    assert all(m.ground_truth_topic_count == 0 for m in dsa.modules)


def test_provenance_records_which_extract_a_session_ran_against(corpus):
    p = corpus.provenance
    assert p.source == "cortex.scaler.com"
    assert p.extracted_at
    assert p.adapter == "cortex"


def test_ingest_is_reproducible_across_runs(corpus_path):
    a, b = ingest(corpus_path), ingest(corpus_path)
    assert [t.id for t in a.topics] == [t.id for t in b.topics]
    assert [m.id for m in a.modules] == [m.id for m in b.modules]


# -- what the contract refuses ----------------------------------------------

def _leaf(i: str, order: int = 1, **kw) -> Leaf:
    kw.setdefault("kind", LeafKind.CONTENT)
    kw.setdefault("text", "body")
    return Leaf(id=i, order=order, title=f"leaf {i}", **kw)


def _corpus_with(topics: tuple[Topic, ...], second: tuple[Topic, ...] = ()) -> Corpus:
    mods = [Module(id="m1", order=1, title="M1", topics=topics)]
    if second:
        mods.append(Module(id="m2", order=2, title="M2", topics=second))
    return Corpus(
        provenance=CorpusProvenance(source="s", extracted_at="t", adapter="a"),
        tracks=(Track(key="k", title="T", modules=tuple(mods)),),
    )


def test_a_duplicate_topic_id_is_refused_and_the_message_names_it():
    t1 = Topic(id="dup", order=1, title="One", leaves=(_leaf("a"),))
    t2 = Topic(id="dup", order=1, title="Two", leaves=(_leaf("b"),))
    with pytest.raises(ValidationError, match="dup"):
        _corpus_with((t1,), (t2,))


def test_a_duplicate_topic_id_is_refused_across_modules_not_merely_within_one():
    """topic_id is the permanent join key, so uniqueness is global."""
    t1 = Topic(id="same", order=1, title="A", leaves=(_leaf("a"),))
    t2 = Topic(id="same", order=1, title="B", leaves=(_leaf("b"),))
    with pytest.raises(ValidationError, match="same"):
        _corpus_with((t1,), (t2,))


def test_a_duplicate_leaf_id_within_a_topic_is_refused():
    with pytest.raises(ValidationError, match="duplicate leaf ids"):
        Topic(id="t", order=1, title="T", leaves=(_leaf("x"), _leaf("x", 2)))


def test_a_missing_or_invalid_order_is_refused():
    with pytest.raises(ValidationError):
        Topic(id="t", order=0, title="T", leaves=(_leaf("a"),))
    with pytest.raises(ValidationError):
        Leaf(id="a", order=0, title="t", kind=LeafKind.CONTENT)


def test_unordered_leaves_are_refused():
    with pytest.raises(ValidationError, match="ascending order"):
        Topic(id="t", order=1, title="T", leaves=(_leaf("a", 2), _leaf("b", 1)))


def test_a_topic_with_no_leaves_is_refused():
    with pytest.raises(ValidationError, match="at least one leaf"):
        Topic(id="t", order=1, title="T", leaves=())


def test_ground_truth_must_name_what_it_answers_and_carry_text():
    with pytest.raises(ValidationError, match="names no leaf"):
        Leaf(id="g", order=1, title="key", kind=LeafKind.GROUND_TRUTH, text="x")
    with pytest.raises(ValidationError, match="carries no text"):
        Leaf(
            id="g", order=1, title="key", kind=LeafKind.GROUND_TRUTH,
            text=None, answers_leaf_id="p",
        )


def test_the_contract_has_no_field_for_difficulty():
    """The Corpus records none and derives none, so there is nowhere to put one."""
    for model in (Leaf, Topic, Module, Track, Corpus):
        fields = set(model.model_fields)
        assert not {f for f in fields if "difficult" in f or "level" in f}
    with pytest.raises(ValidationError):
        Leaf(id="a", order=1, title="t", kind=LeafKind.CONTENT, difficulty="hard")


def test_unparseable_source_is_refused_at_ingest(tmp_path: Path):
    bad = tmp_path / "corpus.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(AdapterError, match="not valid JSON"):
        ingest(bad)


def test_a_class_claiming_content_whose_file_is_missing_is_refused(tmp_path: Path):
    src = tmp_path / "corpus.json"
    src.write_text(json.dumps({
        "source": "s", "scrapedAt": "t",
        "tracks": [{"key": "k", "title": "T", "modules": [{
            "id": "m", "order": 1, "title": "M", "topics": [{
                "id": "tp", "order": 1, "title": "TP", "classes": [{
                    "id": "c", "order": 1, "title": "C", "contentType": "text",
                    "kind": "other", "markdownPath": "gone.md", "chars": 4200,
                }]}]}]}]}), encoding="utf-8")
    with pytest.raises(AdapterError, match="file is missing"):
        ingest(src, data_root=tmp_path)


def test_a_class_the_scrape_found_empty_is_not_an_error(tmp_path: Path):
    """chars=0 with no file is an empty Class, not data loss."""
    src = tmp_path / "corpus.json"
    src.write_text(json.dumps({
        "source": "s", "scrapedAt": "t",
        "tracks": [{"key": "k", "title": "T", "modules": [{
            "id": "m", "order": 1, "title": "M", "topics": [{
                "id": "tp", "order": 1, "title": "TP", "classes": [
                    {"id": "c1", "order": 1, "title": "empty", "contentType": "text",
                     "kind": "other", "markdownPath": "gone.md", "chars": 0},
                    {"id": "c2", "order": 2, "title": "real", "contentType": "text",
                     "kind": "other", "markdownPath": "there.md", "chars": 5},
                ]}]}]}]}), encoding="utf-8")
    (tmp_path / "there.md").write_text("hello", encoding="utf-8")
    c = ingest(src, data_root=tmp_path)
    topic = c.topic("tp")
    assert len(topic.leaves) == 2
    assert len(topic.content_leaves) == 1


# -- Ground Truth is optional, and its absence is a mode not a failure -------

def test_a_module_with_no_ground_truth_ingests_and_reports_a_lower_ceiling(corpus):
    genai = next(m for m in corpus.modules if m.title == "Basics of GenAI and AI agents")
    assert genai.ground_truth_topic_count == 0
    assert len(genai.topics) == 9
    for topic in genai.topics:
        assert topic.grading_mode_ceiling is GradingMode.TEXT_GROUNDED


def test_a_topic_with_ground_truth_reports_the_strongest_ceiling(corpus):
    attention = corpus.topic("cmrovsvm21xy1qj0fmr2rinvz")
    assert attention is not None
    assert attention.grading_mode_ceiling is GradingMode.GROUND_TRUTH


def test_a_topic_with_no_text_at_all_falls_to_model_judgment():
    topic = Topic(
        id="t", order=1, title="T",
        leaves=(_leaf("a", text=None, kind=LeafKind.REFERENCE),),
    )
    assert topic.grading_mode_ceiling is GradingMode.MODEL_JUDGMENT


def test_grading_mode_weights_are_the_three_recorded_constants():
    assert GradingMode.GROUND_TRUTH.weight == 1.0
    assert GradingMode.TEXT_GROUNDED.weight == 0.7
    assert GradingMode.MODEL_JUDGMENT.weight == 0.5


# -- the Dossier Loader ------------------------------------------------------

def test_loading_a_known_topic_returns_every_content_leaf_in_order(loader, corpus):
    topic = corpus.topic("cmrlq73jd1vkzqj0fw8nim1s9")
    d = loader.load(topic.id)
    assert d.topic_title == topic.title
    assert [l.id for l in d.content] == [l.id for l in topic.content_leaves]
    assert [l.order for l in d.content] == sorted(l.order for l in d.content)
    assert not d.is_empty


def test_an_unknown_topic_id_is_not_found_not_an_empty_dossier(loader):
    with pytest.raises(TopicNotFound):
        loader.load("no-such-topic")


def test_an_empty_dossier_is_distinguishable_from_not_found():
    topic = Topic(
        id="t", order=1, title="T",
        leaves=(_leaf("a", text=None, kind=LeafKind.REFERENCE, syllabus=("Arrays",)),),
    )
    loader = DossierLoader(_corpus_with((topic,)))
    d = loader.load("t")
    assert d.is_empty
    assert d.syllabus == ("Arrays",)
    assert d.grading_mode_ceiling is GradingMode.MODEL_JUDGMENT


def test_every_topic_loads_within_the_budget_adr_0005_rests_on(loader):
    report = loader.budget_report()
    assert report["topics"] == 71
    assert report["max"] < 12_000, report


def test_a_dossier_can_be_rendered_without_ground_truth(loader, corpus):
    attention = corpus.topic("cmrovsvm21xy1qj0fmr2rinvz")
    d = loader.load(attention.id)
    assert d.ground_truth_pairs
    key_text = d.ground_truth_pairs[0][1].text

    withheld = d.text_for_prompt(include_ground_truth=False)
    included = d.text_for_prompt(include_ground_truth=True)

    assert key_text not in withheld
    assert key_text in included
    assert len(withheld) < len(included)


def test_the_loader_reports_membership_without_raising(loader, corpus):
    assert corpus.topics[0].id in loader
    assert "nope" not in loader
