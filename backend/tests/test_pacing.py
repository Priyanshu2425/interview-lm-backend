"""ISSUE-0040 — a scope suggests a time.

Pure arithmetic, so these tests touch no database, no Corpus and no model. That is
the property worth protecting: if this file ever needs a fixture, the reading has
started depending on the material and has become a difficulty figure.
"""

from __future__ import annotations

import ast
import inspect

from interviewer.service.graph import pacing
from interviewer.service.graph.pacing import (
    MAX_TOPICS_PER_QUESTION,
    SECONDS_PER_QUESTION,
    budget_questions,
    is_compressed,
    minimum_seconds,
    questions_at_full_coverage,
    suggested_seconds,
)


def test_a_scope_suggests_one_question_per_topic():
    assert suggested_seconds(12) == 12 * SECONDS_PER_QUESTION
    assert suggested_seconds(12) == 2160  # 36 minutes


def test_the_minimum_groups_topics_up_to_the_ceiling():
    # Twelve Topics at three per question is four questions.
    assert minimum_seconds(12) == 4 * SECONDS_PER_QUESTION


def test_the_minimum_rounds_up_rather_than_losing_a_topic():
    # Thirteen Topics need five questions, not four and a bit.
    assert minimum_seconds(13) == 5 * SECONDS_PER_QUESTION


def test_one_topic_is_one_question_never_zero():
    assert minimum_seconds(1) == SECONDS_PER_QUESTION
    assert suggested_seconds(1) == SECONDS_PER_QUESTION
    assert questions_at_full_coverage(1) == 1


def test_an_empty_scope_costs_nothing():
    assert suggested_seconds(0) == 0
    assert minimum_seconds(0) == 0
    assert questions_at_full_coverage(0) == 0


def test_a_budget_is_never_zero_questions():
    """A Session that asks nothing is broken, not short."""
    assert budget_questions(0) == 1
    assert budget_questions(1) == 1
    assert budget_questions(SECONDS_PER_QUESTION - 1) == 1


def test_a_budget_is_whole_questions_only():
    assert budget_questions(SECONDS_PER_QUESTION) == 1
    assert budget_questions(SECONDS_PER_QUESTION * 5) == 5
    # Part of a question is not a question.
    assert budget_questions(SECONDS_PER_QUESTION * 5 + 1) == 5


def test_the_suggested_time_affords_full_coverage():
    """The headline promise: take the suggestion and every Topic gets a question."""
    for topics in (1, 2, 7, 12, 57, 71):
        assert budget_questions(suggested_seconds(topics)) == topics
        assert not is_compressed(topics, suggested_seconds(topics))


def test_the_minimum_time_affords_the_grouped_plan():
    """And the floor: take the minimum and every Topic is still reachable, grouped."""
    for topics in (1, 2, 7, 12, 57, 71):
        budget = budget_questions(minimum_seconds(topics))
        assert budget * MAX_TOPICS_PER_QUESTION >= topics


def test_below_the_suggestion_the_session_is_compressed():
    assert is_compressed(12, suggested_seconds(12) - SECONDS_PER_QUESTION)
    assert is_compressed(12, minimum_seconds(12))


def test_the_minimum_never_exceeds_the_suggestion():
    for topics in range(0, 80):
        assert minimum_seconds(topics) <= suggested_seconds(topics)


def test_pacing_reads_nothing_but_a_topic_count():
    """The refusal, asserted rather than trusted.

    A time derived from dossier length is a difficulty figure, and difficulty is not
    a Corpus property (ADR-0007, AGENTS.md). The cheapest guarantee that this stays
    true is that the module cannot reach the material at all.
    """
    tree = ast.parse(inspect.getsource(pacing))
    imported = [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert imported == ["__future__"], (
        f"pacing imports {imported}; it must not be able to reach the material"
    )

    for fn in (suggested_seconds, minimum_seconds, budget_questions,
               questions_at_full_coverage, is_compressed):
        params = set(inspect.signature(fn).parameters)
        assert params <= {"topic_count", "seconds"}, (
            f"{fn.__name__} takes {params}; a pacing figure reads a count or a clock"
        )
