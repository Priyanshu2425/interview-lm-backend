"""How long a scope needs, and how many questions fit in a clock (ISSUE-0040).

A Candidate picks Modules and then picks a duration, and nothing has connected the
two. Eight Modules in fifteen minutes is a Session that examines three Topics and
says so afterwards.

Every figure here is derived from **Topic count alone**. Not from dossier length,
not from `approx_tokens`, not from anything else the Corpus knows about the
material. "This Topic has more text, so it needs longer" is a difficulty reading
wearing a duration's clothes, and difficulty is not a Corpus property (ADR-0007).
Topic count is a Coverage fact, which is already published on the endpoint these
figures join.

Pure by construction: this module imports nothing from the project, so the arithmetic
can be read and tested without a database, a Corpus, or a model.
"""

from __future__ import annotations

#: One question and the follow-ups it earns. `Interviewer.max_turns` bounds a
#: question at six turns; three minutes is that bound at a conversational pace,
#: rounded to something a human can hold in their head.
SECONDS_PER_QUESTION = 180

#: How many Topics one question may span before it stops examining any of them.
#: The same ceiling the planner enforces, and the reason a compressed Session is
#: shorter rather than infinitely compressible.
MAX_TOPICS_PER_QUESTION = 3


def suggested_seconds(topic_count: int) -> int:
    """Long enough to give every Topic its own question.

    The figure a Candidate should see beside a scope: what full Coverage costs.
    """
    return max(0, topic_count) * SECONDS_PER_QUESTION


def minimum_seconds(topic_count: int) -> int:
    """The floor, below which some Topic goes unexamined entirely.

    Grouping is what a short clock buys, and it buys a bounded amount: at three
    Topics per question, a scope of twelve still needs four questions. Under this,
    a Session cannot touch every Topic however it is planned.

    Never zero for a non-empty scope — one Topic is one question.
    """
    if topic_count <= 0:
        return 0
    questions = -(-topic_count // MAX_TOPICS_PER_QUESTION)  # ceil
    return questions * SECONDS_PER_QUESTION


def budget_questions(seconds: int) -> int:
    """How many questions fit. At least one, because a Session that asks nothing
    is not a short Session — it is a broken one."""
    return max(1, seconds // SECONDS_PER_QUESTION)


def questions_at_full_coverage(topic_count: int) -> int:
    """One per Topic. Named rather than inlined, because the surface shows it and
    a bare `topic_count` at the call site would read as a coincidence."""
    return max(0, topic_count)


def is_compressed(topic_count: int, seconds: int) -> bool:
    """True when the clock cannot afford a question per Topic, so the planner must
    group. The planner decides *how*; this only says whether it has to."""
    return budget_questions(seconds) < questions_at_full_coverage(topic_count)
