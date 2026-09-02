"""ISSUE-0004 — Confidence Math and the Evidence Floor.

Pure tests. No database, no harness — which is the point of the module having
no storage, clock or randomness it does not receive.
"""

import numpy as np
import pytest

from interviewer.model.confidence_models import (
    BAND_FIRM,
    BAND_UNKNOWN,
    PRIOR,
    Band,
    NotReportable,
    Posterior,
    EvidenceDelta,
)
from interviewer.model.readings_models import CoverageReading, MasteryReading, TopicReading


# -- the update rule --------------------------------------------------------

@pytest.mark.parametrize("weight", [1.0, 0.7, 0.5])
def test_the_update_moves_alpha_and_beta_by_exactly_w_times_s(weight):
    d = EvidenceDelta.of(0.8, weight)
    assert d.alpha_delta == pytest.approx(weight * 0.8)
    assert d.beta_delta == pytest.approx(weight * 0.2)


def test_score_and_weight_are_never_conflated():
    """An answer reached after hints is worth roughly half — in `s`, not `w`."""
    hinted = EvidenceDelta.of(0.5, 1.0)      # ground-truth graded, half credit
    unhinted = EvidenceDelta.of(1.0, 0.5)    # model judgment, full credit
    assert hinted.alpha_delta == unhinted.alpha_delta == 0.5
    assert hinted.beta_delta == 0.5
    assert unhinted.beta_delta == 0.0      # different evidence entirely


def test_an_out_of_range_score_or_unknown_weight_is_refused():
    with pytest.raises(ValueError):
        EvidenceDelta.of(1.4, 1.0)
    with pytest.raises(ValueError):
        EvidenceDelta.of(0.5, 0.85)


def test_the_prior_reads_as_unknown_not_as_zero():
    assert PRIOR.band is Band.UNTESTED
    assert PRIOR.coverage == 0.0
    assert PRIOR.mastery_or_none is None


def test_asking_for_mastery_below_the_floor_raises_rather_than_guessing():
    with pytest.raises(NotReportable):
        _ = PRIOR.mastery


def test_a_posterior_below_the_prior_is_refused():
    with pytest.raises(ValueError, match="below the prior floor"):
        Posterior(0.5, 1.0)


# -- the bands are read off the interval, not off a count -------------------

def test_bands_are_derived_from_interval_width_not_from_a_count_of_answers():
    wide = Posterior(1.2, 1.2)
    narrow = Posterior(12.0, 4.5)
    assert wide.width >= BAND_UNKNOWN
    assert narrow.width < BAND_FIRM
    assert wide.band is Band.UNTESTED
    assert narrow.band is Band.FIRM_STRONG


def test_repeated_identical_evidence_narrows_the_interval_and_holds_the_mean():
    p = PRIOR
    means, widths = [], []
    for _ in range(8):
        p = p.updated(0.75, 1.0)
        if p.band.reportable:
            means.append(p.mastery)
        widths.append(p.width)
    assert widths == sorted(widths, reverse=True)
    assert max(means) - min(means) < 0.12


def test_a_firm_weak_reading_needs_its_upper_bound_below_the_ceiling():
    weak = Posterior(3.6, 7.4)
    strong = Posterior(8.2, 3.2)
    assert weak.band is Band.FIRM_WEAK and weak.interval[1] < 0.6
    assert strong.band is Band.FIRM_STRONG


def test_coverage_is_effective_evidence_not_a_count_of_questions():
    p = PRIOR
    p = p.updated(1.0, 0.5)   # model judgment
    p = p.updated(1.0, 0.7)   # text grounded
    assert p.coverage == pytest.approx(1.2)   # two questions, 1.2 effective visits


def test_an_untested_topic_and_a_missing_row_read_identically():
    assert TopicReading.of("t", PRIOR).mastery is None
    assert TopicReading.of("t", PRIOR).band is Band.UNTESTED
    assert TopicReading.of("t", PRIOR).interval is None


# -- reporting keeps the two readings apart ---------------------------------

def test_coverage_and_mastery_are_separate_and_never_fused():
    readings = [
        TopicReading.of("a", Posterior(8.2, 3.2)),
        TopicReading.of("b", Posterior(3.6, 7.4)),
        TopicReading.of("c", Posterior(1.5, 1.5)),
        TopicReading.of("d", PRIOR),
    ]
    cov = CoverageReading.of(readings, topics_total=71)
    mas = MasteryReading.of(readings)

    assert cov.topics_examined == 3
    assert cov.topics_total == 71
    assert mas.looks_solid == 1
    assert mas.looks_weak == 1
    assert mas.early_signal == 1

    # There is no field anywhere that merges them.
    for obj in (cov, mas):
        fields = set(obj.__slots__)
        assert not any("score" in f or "overall" in f or "percent" in f for f in fields)


def test_a_topic_below_the_floor_carries_no_number_in_its_reading():
    r = TopicReading.of("t", PRIOR)
    assert r.mastery is None
    assert r.label == "Untested"


# -- sampling is injected ----------------------------------------------------

def test_sampling_is_reproducible_from_an_injected_generator():
    p = Posterior(3.0, 2.0)
    a = [p.sample(np.random.default_rng(4)) for _ in range(3)]
    b = [p.sample(np.random.default_rng(4)) for _ in range(3)]
    assert a == b


def test_an_untested_topic_samples_more_widely_than_a_settled_one():
    rng = np.random.default_rng(0)
    untested = [PRIOR.sample(rng) for _ in range(400)]
    settled = [Posterior(30.0, 10.0).sample(rng) for _ in range(400)]
    assert np.std(untested) > np.std(settled) * 2
