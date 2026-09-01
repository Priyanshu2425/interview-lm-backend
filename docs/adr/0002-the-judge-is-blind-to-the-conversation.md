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

## Amendment — the Judge reads two dimensions (ISSUE-0043)

Rubric v2 returns two numbers instead of one: **SOURCE**, how much of the
supplied material the answer explained, and **TRUTH**, how close to correct the
answer is on the subject. One number could not say both, and a single score let
whichever question the grader happened to weigh stand for the other. A Candidate
who explains the course faithfully and a Candidate who is correct from somewhere
else are different readings, and they no longer collapse.

**What did not change.** The Judge is still a separate call and still blind. It
receives the question, the answer and the grounding, and nothing about the
conversation — reading twice gives it no reason to see the exchange, and it does
not. Grading Mode is untouched: it still picks exactly one grounding tier and
still supplies the weight, which is the trust owed to the grounding rather than
a claim about how well the answer used it. `math.py` is untouched too; the Beta
update sees one number, exactly as before.

**What changed.** `Verdict` carries both readings and the version of the rubric
that produced them, `source_score` and `truth_score` are stored on the Evidence
row beside `score`, and the combination that feeds the posterior is stated once
in `judge.py`: the grounded modes take the two in equal halves, and
`MODEL_JUDGMENT` — which supplies no material to have explained — has no SOURCE
at all, so its `source_score` is null and its `score` is TRUTH unchanged. Null,
not zero: an answer graded against nothing did not fail to explain the material,
it was never asked to.

The two readings are reported separately and are never fused into a headline
figure. That is the refusal `AGENTS.md` already makes for Coverage and Mastery,
for the same reason — the average of two different questions answers neither.
The combination above is an input to the math and not a reading shown as a
score, which is why it lives on `Verdict` and not on any screen.

**MCP Mode still redeems one number.** The subagent grades against the material
it is handed and returns a score, and that row records neither sub-score. It is
a grader that reads one dimension, and a null says so rather than a zero
inventing a reading it never took.
