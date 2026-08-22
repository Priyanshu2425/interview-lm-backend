# A citation is read on request, beside the Evidence it grounded

Decides: ISSUE-0025 (the placement it was waiting for)
Source: ISSUE-0025; ADR-0006; PRD-0002 §the record

## The decision

A citation appears in the **Evidence drawer**, opened per Topic Visit, under
*"What grounded the questions"*. It appears nowhere in the live exchange.

## Why not in the exchange

The obvious placement is beside the question: here is what you are being asked
about, and here is the passage it came from. It is refused, and the reason is
not visual.

**A citation in the exchange is a hint nobody asked for.** The graph owns the
hint move — a Candidate asks and the Interviewer decides — and a passage shown
alongside the question hands over the same help without the asking, without the
record, and without whatever the hint move costs a Candidate. It would make
every question open-book while the Evidence still says it was not.

Worse, it inverts the examination. A question grounded in a span, shown with the
span, tests reading rather than recall.

## Why the drawer

The citation's job is **attribution**, not assistance: it lets somebody check
that a question came from the material rather than from the model's imagination,
and check it *afterwards*. The Evidence row is where that check belongs, and the
drawer is where the row already keeps everything a reader has to open
deliberately.

It also puts the citation beside the thing it justifies. A span means little on
its own; beside "graded ground_truth, weight 1.0, reading after: Looks solid" it
is doing the work it exists for.

## What holds it there

- Nothing in the exchange fetches or renders a citation, and no route offers one
  mid-Session.
- The drawer names source and page, never a byte offset — a reader is being sent
  to a place in a document, not to an index into a string.
- A Topic with no chunks records an empty citation list and renders without one,
  and a model-judged Visit says why it has none rather than quoting something
  anyway.
- No similarity query runs during a Session; the citation was recorded when the
  question was written, and a test counts embedder calls across a whole Session
  to prove it.

## Revisiting

An open-book Grading Mode would reopen this, because then showing the span is
the point rather than a leak. That is a fourth Grading Mode and a different
Judge, not a placement change.
