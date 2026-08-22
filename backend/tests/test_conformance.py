"""PRD-0001 gaps — reporting, conformance, and a second Adapter."""

import pytest

from interviewer.corpus.adapters import markdown_folder
from interviewer.corpus.conformance import (
    CONFORMANCE_EXPECTATIONS, diff_topics, fixture_corpus, validate,
)
from interviewer.corpus.contract import GradingMode
from interviewer.corpus.loader import DossierLoader


def test_the_report_names_every_violation_not_only_the_first():
    """An Adapter author fixing one error at a time is the failure mode."""
    from interviewer.corpus.contract import (
        Corpus, CorpusProvenance, Leaf, LeafKind, Module, Topic, Track,
    )

    leaf = Leaf(id="a", order=1, title="t", kind=LeafKind.CONTENT, text="x")
    t1 = Topic(id="same", order=1, title="One", leaves=(leaf,))
    t2 = Topic(id="same", order=1, title="Two", leaves=(leaf,))
    # bypass Corpus's own validator to exercise the report
    c = Corpus.model_construct(
        provenance=CorpusProvenance(source="s", extracted_at="t", adapter="a"),
        tracks=(Track(key="k", title="T", modules=(
            Module(id="m1", order=1, title="M1", topics=(t1,)),
            Module(id="m1", order=2, title="M1 again", topics=(t2,)),
        )),),
    )
    r = validate(c)
    assert not r.ok
    assert len(r.violations) >= 2
    assert any("topic id" in v for v in r.violations)
    assert any("module id" in v for v in r.violations)


def test_the_report_states_dossier_sizes_at_ingest(corpus):
    r = validate(corpus)
    assert r.dossier_tokens["topics"] == 71
    assert r.dossier_tokens["max"] > r.dossier_tokens["median"] > 0


def test_the_report_records_provenance(corpus):
    r = validate(corpus)
    assert r.provenance["source"] == "cortex.scaler.com"
    assert r.provenance["adapter"] == "cortex"
    assert r.provenance["extracted_at"]


def test_leaves_with_no_content_are_kept_as_stubs_not_omitted(corpus):
    """A video Class is a real part of the curriculum even though we cannot
    read it."""
    r = validate(corpus)
    assert r.stub_leaves > 0
    assert r.leaves == 430


def test_a_topic_that_is_all_stubs_is_flagged_rather_than_rejected():
    from interviewer.corpus.contract import (
        Corpus, CorpusProvenance, Leaf, LeafKind, Module, Topic, Track,
    )

    c = Corpus(
        provenance=CorpusProvenance(source="s", extracted_at="t", adapter="a"),
        tracks=(Track(key="k", title="T", modules=(
            Module(id="m", order=1, title="M", topics=(
                Topic(id="t", order=1, title="All video", leaves=(
                    Leaf(id="l", order=1, title="Recording",
                         kind=LeafKind.REFERENCE, text=None),
                )),
            )),
        )),),
    )
    r = validate(c)
    assert r.ok                       # not a violation
    assert r.stub_only_topics == ["t"]
    assert any("Model judgment" in w for w in r.warnings)


def test_a_reingest_that_moves_topic_boundaries_is_reported(corpus, corpus_path):
    from interviewer.corpus.adapters.cortex import ingest

    same = diff_topics(corpus, ingest(corpus_path))
    assert same == {"added": [], "removed": [], "leaves_changed": [], "stable": 71}

    trimmed = corpus.model_copy(update={"tracks": corpus.tracks[:1]})
    moved = diff_topics(corpus, trimmed)
    assert len(moved["removed"]) == 14      # the DSA Track's Topics
    assert moved["added"] == []


def test_the_cli_validates_a_corpus_locally(corpus_path, capsys):
    from interviewer.corpus.cli import main

    assert main(["cli", str(corpus_path)]) == 0
    out = capsys.readouterr().out
    assert "topics=71" in out and "OK" in out


def test_the_cli_reports_a_broken_corpus_rather_than_crashing(tmp_path, capsys):
    from interviewer.corpus.cli import main

    bad = tmp_path / "corpus.json"
    bad.write_text("{ not json", encoding="utf-8")
    assert main(["cli", str(bad)]) == 1
    assert "failed" in capsys.readouterr().out


# -- the fixture, and a second Adapter --------------------------------------

def test_the_fixture_corpus_satisfies_the_contract():
    r = validate(fixture_corpus())
    assert r.ok, r.violations
    assert r.ground_truth_pairs == 1


def test_the_fixture_exercises_all_three_grading_mode_ceilings():
    c = fixture_corpus()
    for tid, expected in CONFORMANCE_EXPECTATIONS.items():
        assert c.topic(tid).grading_mode_ceiling is expected


def test_a_second_adapter_is_implementable_against_the_contract_alone(tmp_path):
    """ADR-0007's claim, made checkable."""
    root = tmp_path / "handbook"
    topic = root / "01-basics" / "01-arrays"
    topic.mkdir(parents=True)
    (topic / "01-notes.md").write_text("Arrays are contiguous.", encoding="utf-8")
    (topic / "02-quiz.md").write_text("Q: cost of append?", encoding="utf-8")
    (topic / "03-answer-key.md").write_text("Amortised O(1).", encoding="utf-8")
    other = root / "01-basics" / "02-strings"
    other.mkdir(parents=True)
    (other / "01-notes.md").write_text("Strings are immutable.", encoding="utf-8")

    corpus = markdown_folder.ingest(root)
    r = validate(corpus)
    assert r.ok, r.violations
    assert r.topics == 2
    assert r.ground_truth_pairs == 1

    # and the backbone consumes it with no changes at all
    loader = DossierLoader(corpus)
    d = loader.load("01-basics/01-arrays")
    assert d.grading_mode_ceiling is GradingMode.GROUND_TRUTH
    assert "Amortised O(1)" not in d.text_for_prompt(include_ground_truth=False)
    assert "Amortised O(1)" in d.text_for_prompt(include_ground_truth=True)

    d2 = loader.load("01-basics/02-strings")
    assert d2.grading_mode_ceiling is GradingMode.TEXT_GROUNDED


def test_an_adapter_may_declare_that_its_source_carries_no_ground_truth(tmp_path):
    root = tmp_path / "wiki"
    t = root / "01-m" / "01-t"
    t.mkdir(parents=True)
    (t / "01-page.md").write_text("Some prose.", encoding="utf-8")
    corpus = markdown_folder.ingest(root)
    assert validate(corpus).ground_truth_pairs == 0
    assert corpus.topic("01-m/01-t").grading_mode_ceiling is GradingMode.TEXT_GROUNDED
