"""ISSUE-0024 — the notebook's own answer keys, found rather than invented.

The distinction this file defends: material that *came from the source* can be
Ground Truth, and material a model wrote cannot, however confident it sounds.
Principle 4 — refuse the number you cannot justify — is a grading weight here.
"""

from __future__ import annotations

import pytest

from interviewer.adapters.internal.notebook import (
    HashingEmbedder, Notebook, Source, ingest_notebook,
)
from interviewer.service.corpus.conformance import validate
from interviewer.model.corpus import GradingMode, LeafKind

WORKED = """# Exercises: bias and variance

**Q1.** A model scores 0.98 on training data and 0.61 on held-out data. Name the
failure and the two cheapest remedies.

**Q2.** Bagging and boosting both build ensembles. Which attacks variance, which
attacks bias, and why does the answer follow from how each one is trained?

**Q3.** You add 10,000 rows of training data and validation error does not move.
What does that tell you about where the error is coming from?

## Answer key

**A1.** Overfitting: the gap between training and held-out score is variance.
The cheapest remedies are regularisation and more data, in that order, because
regularisation costs nothing to try.

**A2.** Bagging attacks variance — each model overfits its own bootstrap
resample differently and averaging cancels the differences. Boosting attacks
bias, because each model is fitted on the residual errors of the last.

**A3.** The error is bias, not variance. Variance falls with more data; bias does
not, so a flat validation curve under more data says the model class is too
simple.
"""

PLAIN = """# Gradient descent

Gradient descent follows the negative gradient of the loss surface. The learning
rate decides how far each step travels, and a rate that is too large oscillates
across a ravine rather than descending it. Momentum accumulates a velocity over
past gradients, which damps the oscillation and speeds progress along the floor
of the ravine.
""" * 4


def notebook(text: str) -> Notebook:
    return Notebook(
        notebook_id="nb-gt",
        title="Notes",
        sources=(Source(source_id="s1", title="Exercises", text=text),),
    )


@pytest.fixture(scope="module")
def mined():
    return ingest_notebook(notebook(WORKED), embedder=HashingEmbedder())


@pytest.fixture(scope="module")
def unmined():
    return ingest_notebook(notebook(PLAIN), embedder=HashingEmbedder())


def test_worked_solutions_become_paired_prompt_and_ground_truth(mined):
    pairs = [p for t in mined.corpus.topics for p in t.ground_truth_pairs]
    assert pairs, "a source that is literally questions-and-answers mined nothing"
    for prompt, key in pairs:
        assert prompt.kind is LeafKind.PROMPT
        assert key.kind is LeafKind.GROUND_TRUTH
        assert key.answers_leaf_id == prompt.id


def test_a_mined_topic_grades_at_full_authority(mined):
    modes = {t.grading_mode_ceiling for t in mined.corpus.topics}
    assert GradingMode.GROUND_TRUTH in modes
    assert GradingMode.GROUND_TRUTH.weight == 1.0


def test_prose_alone_stays_text_grounded(unmined):
    assert all(
        t.grading_mode_ceiling is GradingMode.TEXT_GROUNDED
        for t in unmined.corpus.topics
    )
    assert not any(t.ground_truth_pairs for t in unmined.corpus.topics)


def test_no_topic_claims_ground_truth_without_a_key_behind_it(mined, unmined):
    for ingested in (mined, unmined):
        for topic in ingested.corpus.topics:
            if topic.grading_mode_ceiling is GradingMode.GROUND_TRUTH:
                assert topic.ground_truth_pairs


def test_every_key_is_text_that_came_from_the_source(mined):
    """Nothing is generated. A model-written key is model judgment in disguise."""
    for topic in mined.corpus.topics:
        for _, key in topic.ground_truth_pairs:
            assert key.text in WORKED


def test_ground_truth_never_reaches_the_question_asker(mined):
    from interviewer.service.corpus.loader import DossierLoader

    loader = DossierLoader(mined.corpus)
    for topic in mined.corpus.topics:
        dossier = loader.load(topic.id)
        if not dossier.ground_truth_pairs:
            continue
        teaching = dossier.text_for_prompt(include_ground_truth=False)
        for _, key in dossier.ground_truth_pairs:
            assert key.text not in teaching


def test_a_key_is_retrievable_by_the_prompt_it_answers(mined):
    from interviewer.service.corpus.loader import DossierLoader

    loader = DossierLoader(mined.corpus)
    for topic in mined.corpus.topics:
        dossier = loader.load(topic.id)
        for prompt, key in dossier.ground_truth_pairs:
            found = [k for p, k in dossier.ground_truth_pairs if p.id == prompt.id]
            assert found == [key]


def test_a_notebook_with_no_question_material_is_still_examinable(unmined):
    assert validate(unmined.corpus).violations == []
    assert unmined.corpus.topics


def test_mining_survives_the_store(notebooks):
    notebooks.create("nb-gt", "cand-1", "Exercises")
    notebooks.add_source("nb-gt", source_id="s1", title="Exercises", text=WORKED)
    corpus = notebooks.corpus("nb-gt")
    pairs = [p for t in corpus.topics for p in t.ground_truth_pairs]
    assert pairs, "mining was lost between the Adapter and the store"
    assert any(
        t.grading_mode_ceiling is GradingMode.GROUND_TRUTH for t in corpus.topics
    )
    assert validate(corpus).violations == []


def test_the_picker_reports_the_ground_truth_a_notebook_carries(notebooks):
    notebooks.create("nb-gt2", "cand-1", "Exercises")
    added = notebooks.add_source(
        "nb-gt2", source_id="s1", title="Exercises", text=WORKED
    )
    from interviewer.service.corpus import CorpusService

    reading = CorpusService(notebooks.corpus("nb-gt2")).modules()[0]
    assert reading.ground_truth_topic_count >= 1
    assert added.state == "ready"
