# The Judge is a separate call, blind to the conversation

Scoring an answer happens in a dedicated **Judge** call that receives only the
question, the answer, and the relevant **Ground Truth** or dossier excerpt. It
is not given the conversation history, and it is not the same call that
conducted the interview.

## Why

The model that has just spent twenty minutes building rapport is the worst
available grader of that conversation. Sycophancy here is not a prompt defect to
be instructed away — it is conversational context working as intended. A
confident, articulate, wrong answer is exactly the input that fools an inline
grader.

This is also the only guardrail whose failure is invisible. Scope violations and
leaked answers are obvious on reading a transcript. A systematically generous
judge emits plausible numbers that are quietly wrong, and those numbers become
**Evidence** — a permanent write into a Beta distribution that misdirects every
later question choice.

It protects the weighting scheme too: applying weight 1.0 to a sycophantic score
because it came from an **Answer Key** is worse than not weighting at all.

## Considered and rejected

**Inline grading** — cheaper and simpler, and it was rejected on data integrity
rather than cost. Anyone tempted to "improve" the Judge by handing it
conversation history for nuance is re-introducing the exact failure this
decision exists to prevent.

**An adversarial second-opinion judge** — deferred, not dismissed. It doubles
grading cost to address a problem we cannot yet measure. Session replay
(see ADR-0001) will make judge drift measurable, and the decision can then be
made with data.

## Amendment — blindness is context isolation, not location

**MCP Mode** grades in a subagent dispatched by the host Claude, not on our
server. This does not weaken the decision above, because the property being
protected is context isolation rather than where the call runs. A subagent
begins with a fresh context, receives only the question, the answer and the
grounding, and ends when it returns a score.

What was rejected remains rejected: the *host itself* must never grade, having
just conducted the conversation. See ADR-0006 for how grading material reaches
the subagent without passing through the interviewing context.
