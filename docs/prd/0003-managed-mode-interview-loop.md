# PRD-0003 — Managed Mode Interview Loop

Status: ready-for-agent
Depends on: PRD-0001, PRD-0002; ADR-0001, ADR-0002, ADR-0003, ADR-0004

## Problem Statement

A Candidate preparing for an AI/ML interview has 1.9 MB of course material and
no way to be examined on it.

Reading is not preparation. The failure mode of self-study is that a Candidate
recognises material and mistakes recognition for the ability to explain it under
questioning — which is the only thing the actual interview will test. What is
missing is the examination: something that picks a Topic, asks a real question,
listens to the answer, probes when the answer is vague, and records what
happened well enough that next week's practice starts from this week's result.

Nothing in the system does this. The Corpus exists and the tracker exists; there
is no loop between them.

Building that loop the obvious way — a ReAct agent with tools for "load a Topic",
"grade the answer", "update confidence" — fails in two specific ways. The
Evidence write becomes something a model can skip, repeat, or attach the wrong
weight to, and a silently doubled `β` is invisible until Mastery is wrong weeks
later. And grading becomes unmeasurable, because we have no way to know whether
grading is any good except by replaying Sessions against changed prompts, and an
agent-driven loop does not replay.

There is a third failure, subtler than both. The model that has just spent twenty
minutes building rapport is the worst available grader of that conversation. A
confident, articulate, wrong answer is exactly the input that fools an inline
grader — and unlike a scope violation or a leaked answer, a systematically
generous judge is invisible on reading the transcript. It emits plausible numbers
that are quietly wrong, and those numbers are a permanent write.

## Solution

Run the Session as an explicit state machine with the model calls made *inside*
nodes rather than deciding which node runs next:

`select_topic → load_dossier → generate_question → interrupt → grade →
update_confidence → decide_next`

Agency is confined to the region around the Answer Turn — probing a vague answer,
offering a hint, deciding a follow-up is warranted before scoring. Everything
that must happen exactly once is a graph edge, and a graph edge cannot not run.

Scoring is a separate call that never sees the conversation. The Judge receives
the question, the answer, and the grounding, applies a versioned rubric, and
returns a score. It has no memory of the Candidate having been articulate,
likeable, or confident.

`interrupt()` is the Answer Turn. The graph parks and a surface resumes it, which
is why adding voice or a code editor later changes who calls `resume` rather than
changing the graph. The surface built here is text, where the boundary is
unambiguous: the Candidate submits.

The Session ends on a duration the Candidate chose before it began — softly,
after the current Topic Visit completes, never inside one.

## User Stories

1. As a Candidate, I want to start a mock interview scoped to the Modules I choose, so that I practise the part of the course I am actually being examined on.
2. As a Candidate, I want to choose how long the Session runs before it starts, so that I can practise in the time I actually have.
3. As a Candidate, I want the Session to end after the current question completes rather than mid-question, so that my last answer still counts.
4. As a Candidate, I want the first question to be approachable, so that a Session does not open on the hardest thing I have never seen.
5. As a Candidate, I want questions drawn from the course material, so that I am examined on what I was taught rather than on the model's general knowledge.
6. As a Candidate, I want to be asked one thing at a time, so that the exchange feels like an interview rather than a quiz sheet.
7. As a Candidate, I want a follow-up when my answer is vague, so that a half-answer is probed rather than silently marked down.
8. As a Candidate, I want a hint when I am stuck, so that a Session is a practice session and not an exam I fail in silence.
9. As a Candidate, I want an answer reached after hints to still count as an answer, so that asking for help costs me some score rather than the whole question.
10. As a Candidate, I want the whole exchange on one Topic scored once, so that being probed three times on one concept does not count as three failures.
11. As a Candidate, I want to move on when I genuinely do not know something, so that one blank Topic does not consume the Session.
12. As a Candidate, I want to see the score and the reasoning behind it once the Session is over, so that the grade teaches me something.
13. As a Candidate, I want to be told which grader and provider produced my score, so that a grade is attributable.
14. As a Candidate, I want to never be shown the Answer Key before I have answered, so that the question is worth asking.

> **Amended by ISSUE-0042 (§12–14).** §12 used to promise the score and the
> reasoning *after every Topic Visit*. There is no longer a per-Visit grade to
> show: the plan is fixed before the first question, which removes the loop's
> dependency on a freshly updated posterior, which is what lets grading happen
> once, at the end, against the transcript (ISSUE-0044) and be read in the
> report (ISSUE-0045). §13 is unchanged in substance — a score is still
> attributable to a grader and a Provider — but it is attributable *there*
> rather than turn by turn. §14 is unchanged and is if anything stronger: no
> turn response carries a score, a band or a Visit result at all. The
> consequence outside this repository is deliberate: the surface's
> visit-result screen becomes report-only, and this slice breaks its contract
> on purpose rather than by accident.
15. As a Candidate, I want an interrupted Session to be resumable, so that a dropped connection does not cost me the whole practice.
16. As a Candidate, I want an answer I submitted before an interruption to still be graded, so that work I did is not thrown away.
17. As a Candidate, I want to end a Session early, so that I am not held to a duration I no longer have.
18. As a Candidate, I want a summary at the end covering what I was examined on and where I looked weak, so that the Session tells me what to do next.
19. As a Candidate, I want the summary to distinguish Topics I was not asked about from Topics I answered badly, so that I do not study something I was never tested on.
20. As a Candidate, I want this Session's results to inform the next Session's question choice, so that practice compounds.
21. As a returning Candidate, I want my opening difficulty seeded from prior Sessions, so that I am not restarted from scratch every time.
22. As the Interviewer, I want the Topic handed to me by the selector, so that scope enforcement is not something I have to be trusted with.
23. As the Interviewer, I want the whole Topic dossier in context, so that a follow-up can probe a concept whose explanation would otherwise sit in an unretrieved chunk.
24. As the Interviewer, I want to write a question from an Assignment and its Answer Key where one exists, so that the question comes with a rubric.
25. As the Interviewer, I want to write a question from Topic text where no Answer Key exists, so that a Module without Ground Truth is still examinable.
26. As the Interviewer, I want to fall back to my own knowledge, anchored to the Topic's syllabus and Module order, where no text exists at all, so that DSA is examinable today.
27. As the Interviewer, I want the Grading Mode recorded on the Visit at the moment the question is written, so that the weight reflects how the question was actually grounded.
28. As the Interviewer, I want to decide within a Topic Visit whether to probe, hint, or close, so that the exchange adapts to the answer.
29. As the Interviewer, I want a bound on how long one Topic Visit can run, so that a single evasive exchange cannot consume a Session.
30. As the Judge, I want to receive only the question, the answer, and the grounding, so that I cannot be charmed by a conversation I did not see.
31. As the Judge, I want to return a score and a rationale together, so that the score is explainable to the Candidate.
32. As the Judge, I want to apply a versioned rubric, so that a later change to grading is distinguishable from grader drift.
33. As the Judge, I want to grade against an Answer Key where one exists and against the dossier excerpt where it does not, so that Grading Mode is a fact about the grounding rather than a setting.
34. As the graph, I want the Evidence write to be an edge rather than a tool call, so that it cannot be skipped or repeated.
35. As the graph, I want to park at the Answer Turn and wait to be resumed, so that a different surface can be plugged in without changing the loop.
36. As the graph, I want to treat the Answer Turn as an event rather than a read from a kind of input, so that a surface that cannot say when a turn ended is the one that fails, not the graph.
37. As the graph, I want checkpoints per Session thread, so that resumption is what the checkpointer is for rather than bespoke machinery.
38. As a system operator, I want to replay a Session deterministically against changed prompts, so that grading quality is measurable rather than asserted.
39. As a system operator, I want every model call inside the Session attributable to a Topic Visit, so that metering, Evidence and refunds all key on the same unit.
40. As a system operator, I want a Session's chosen duration recorded, so that Sessions are only compared with Sessions of the same length.
41. As a system operator, I want a Session that errors to end with an error the Candidate can act on, so that failure is a resumable state rather than a lost thread.
42. As a future maintainer, I want the deterministic skeleton to exist before the agentic region grows, so that the seam between them stays visible.

## Implementation Decisions

**Modules built**

- *Session Graph* — the state machine. Nodes call models; models do not choose nodes. Owns the Topic Visit lifecycle boundaries and the Evidence edge.
- *Question Writer* — given a dossier and a Grading Mode ceiling, produces a question and records the mode actually used. Never receives Ground Truth for a Topic it is only teaching from.
- *Topic Visit Region* — the agentic part: probe, hint, close. Bounded in turns. Returns the complete exchange for that Visit.
- *Judge* — separate call, versioned rubric, blind to the conversation. Returns `s` and a rationale.
- *Session Config* — scope (Modules) and duration, both chosen before the Session starts, both immutable afterwards.
- *Session Summary* — end-of-Session reading built from the Session's Visits and the tracker's readings, honouring the Evidence Floor.
- *Text Surface* — the Candidate-facing loop that resumes the graph at each Answer Turn.

**The loop**

`select_topic → load_dossier → generate_question → interrupt → grade →
update_confidence → decide_next`. `decide_next` either opens another Topic Visit
or ends the Session. Nothing after `interrupt` is optional, and nothing between
`grade` and `update_confidence` is a decision.

Agency lives inside the interrupt region and nowhere else. The loop is rigid;
off-script Candidate behaviour gets explicit handling rather than emerging from
the model. Build the deterministic skeleton first — starting hybrid hides the
seam.

**Grading Mode selection at question time**

Mode is decided when the question is written, from what the question was actually
grounded in:

- an Assignment with its Answer Key → Ground-Truth-graded
- Topic text with no Answer Key → Text-grounded
- no text at all → Model judgment

The dossier's ceiling bounds this; it does not set it. A Topic with an Answer Key
may still yield a text-grounded question, and the Visit records what happened.

**Answer Key handling in Managed Mode**

The Question Writer may hold an Answer Key when it is writing a question *from
that Assignment* — it is our own process and the Candidate does not see its
context. The Answer Key is never rendered to the Candidate before grading, and
the interviewing context does not load Answer Keys for Topics it is not currently
examining. This is weaker than the MCP Mode guarantee, and deliberately so: the
structural guarantee of ADR-0006 exists because the host's context sits in front
of the Candidate, which is not true here.

**The Judge**

A dedicated call receiving question, answer, grounding, and rubric version.
Not given conversation history — and anyone later tempted to hand it history "for
nuance" is reintroducing the exact failure ADR-0002 exists to prevent. Returns a
score in 0..1 and a rationale shown to the Candidate. Hint assistance is
expressed in `s`; the weight is the tracker's business and the Judge never sets
it.

**Duration and termination**

Duration is chosen before the Session begins and the deadline is soft: the
Session ends after the current Topic Visit finishes, never inside one. A
truncated Visit would produce either no Evidence or Evidence from a half-examined
answer, and both corrupt the record the Session exists to build. Duration is
recorded on the Session, because Sessions are only comparable to Sessions of the
same chosen duration.

**Resumption**

A Session is a checkpointed thread; resuming is what the checkpointer is for, and
the Answer Turn is already a park. An interrupted Topic Visit stays open until it
is graded and is never partially recorded. Where the answer was submitted but
grading did not complete, the exchange is already stored, so resumption grades it
and closes the Visit — and the idempotency key makes a repeated grade a no-op
rather than a double write. No Evidence is ever written for a Visit that was not
graded.

**Replay**

Determinism is a requirement, not a nice-to-have: it is the only way to measure
whether grading is any good. Every non-deterministic input to the graph —
randomness for selection, the clock for the duration check, model responses — is
injected rather than called, so a recorded Session can be re-run against a changed
prompt or rubric.

**State ownership**

Graph state is checkpointer-held and disposable *after a retention window*; Topic
Confidence and Evidence are ours and permanent (ADR-0003). A checkpoint is
load-bearing until its Session is resumed or abandoned, so a schema migration may
only discard checkpoints outside the resumption window.

**Surface boundary**

The graph waits on an Answer Turn event. It never reads a particular kind of
input. The text surface supplies the turn on submit; voice and a code editor
later supply it their own way, and a surface that cannot say when a turn ended
cannot be plugged in. This is the whole reason the surface question was settled
before the graph was built.

## Testing Decisions

A good test here asserts what a Candidate or an auditor would observe: what
happened to the Session, what was written, what the Judge was given. It does not
assert which node ran in which order, how many model calls happened, or what a
prompt contained.

Model calls are stubbed with scripted responses so the loop is deterministic. The
tests are about the machine around the model, which is exactly what ADR-0001
chose a graph in order to make testable.

**Graph loop — tested through a scripted Session.**

- a Session over one Module produces one Evidence row per completed Topic Visit and no more
- a Topic Visit with four Answer Turns produces exactly one Evidence row
- a Session interrupted mid-Visit writes no Evidence for that Visit
- a Session interrupted after submission but before grading, then resumed, grades the stored exchange and closes the Visit
- resuming a Session that was already fully graded writes nothing new
- a Session ends after the current Visit completes when the duration expires, never inside one
- the opening Topic follows curriculum order; subsequent Topics come from the selector
- no Topic outside the Session's chosen Modules is ever visited
- no Topic is visited twice within one Session
- a Session replayed with the same injected randomness, clock and scripted model responses produces an identical Visit sequence and identical scores
- a Session replayed with a changed rubric version produces different scores against the same exchanges — the property that makes grading measurable
- the Grading Mode recorded on each Visit matches the grounding the question was written from
- a Visit that exceeds the turn bound closes and grades rather than running forever

**Judge contract — tested directly.**

- the Judge is called with question, answer and grounding, and with no conversation history — asserted on what the Judge received
- the same question and answer scored twice with the same rubric version and stubbed model produce the same score
- a Ground-Truth-graded call receives the Answer Key for the Assignment being graded and no other Answer Key
- a text-grounded call receives the dossier excerpt and no Answer Key
- a model-judgment call receives no grounding and is recorded as such
- rubric version is present on every result
- a score outside 0..1 is rejected rather than written

**Not tested.** Whether the questions are good, whether the rationale is
persuasive, whether the hint was well-timed. These are model-quality questions
that replay exists to make measurable over time, not assertions.

**Prior art.** PRD-0002's ledger tests cover idempotency at the store level;
these cover it at the loop level, which is where a duplicated write would
actually originate.

## Out of Scope

- MCP Mode. The same invariants, a different driver — PRD-0004.
- Credits, BYOK, provider selection and metering — PRD-0005. This PRD assumes a working model client and does not care whose key paid.
- Voice and code-editor surfaces. The Answer Turn boundary is built so they can be added; they are not added here.
- An adversarial second-opinion Judge. Deferred in ADR-0002.
- Adaptive termination on information gain. Sessions end on the chosen duration.
- Performance History beyond Topic Confidence. Named, not designed.
- Candidate accounts, auth, onboarding, billing UI.
- Any claim about difficulty. The Corpus records none and derives none.

## Further Notes

The DSA Track runs entirely in Model judgment today — 31 of its Classes are video
with no text, and it carries no Ground Truth. That is a usable Session at weight
0.5, and it is the strongest argument for the code-editor surface later: executable
answers with real test runs would move DSA from the weakest evidence in the system
to something deterministic. That is the single largest available upgrade to
evidence quality, and this loop is built so it lands as an additive Grading Mode
rather than a rewrite.

The AIML Track's 26 Assignment/Answer Key pairs are the only weight-1.0 evidence
that exists. They sit in Modules 1–6. A Session scoped to the GenAI and Advanced
AI agents Modules is a mode-2 Session against roughly 490 KB of material, and it
should feel no different to the Candidate — the difference is in the weight, not
the experience.

One line worth keeping in view during implementation: build the deterministic
skeleton before growing the agentic region. Every guarantee in this PRD is a
property of the skeleton, and a hybrid built from the start hides which half is
holding the guarantee.
