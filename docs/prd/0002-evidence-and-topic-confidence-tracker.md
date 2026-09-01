# PRD-0002 — Evidence and Topic Confidence Tracker

Status: ready-for-agent
Depends on: PRD-0001; ADR-0003, ADR-0004

## Problem Statement

A Candidate finishes a mock interview and learns nothing durable from it.

The Session produced graded answers, and the moment it ended those answers became
a transcript — readable, unaggregatable, and useless for choosing what to ask
next time. Nothing in the system can answer the two questions that make repeated
practice worth more than isolated practice: *what have I been examined on*, and
*where am I weak*.

Those are different questions, and the obvious implementation answers neither.
A single score per Topic cannot distinguish a Topic never asked about from one
asked about and failed — which is exactly the distinction the Interviewer needs
to pick its next question. And a Candidate shown "38%" after one bad answer will
study to a number that is barely a guess.

There is a second failure, quieter and permanent. Evidence is a write that cannot
be taken back: it moves a distribution that every future question choice reads.
If a Topic Visit writes twice, or writes at the wrong weight, or writes for an
answer that was never graded, nothing errors. The numbers simply stop meaning
what they mean, and it becomes visible weeks later as a Topic that stopped being
asked about while the Candidate still could not answer it.

## Solution

Store, per Candidate per Topic, a Beta distribution as two numbers — and read
three different things off it.

Mastery is its mean. Coverage is its evidence count. Confidence proper is its
spread. An untested Topic is the prior, and it reads as *unknown* rather than
*weak*, which is the distinction a single score cannot make.

Around that sits the machinery that keeps it honest: a Topic Visit ledger where
every graded exchange is recorded once, idempotently, with the Grading Mode
weight, the grader's provenance and the raw exchange behind it; a selector that
chooses the next Topic by sampling those posteriors; and a reporting layer that
refuses to state a claim about a Topic until it has enough evidence to make one,
and reports Coverage and Mastery as two separate readings that are never fused
into one figure.

The tracker is deliberately the most boring, most tested module in the system.
Everything else can be rewritten. These numbers have to survive it.

## User Stories

1. As a Candidate, I want a Topic I have never been asked about to read as *Untested*, so that I am not told I am weak at something nobody examined me on.
2. As a Candidate, I want to see how much of a Track I have been examined on, so that I know what my practice has and has not touched.
3. As a Candidate, I want Coverage and Mastery reported separately, so that "examined on 12 of 57 Topics" and "3 of those look weak" stay two distinct facts.
4. As a Candidate, I want a reading based on one answer to be hedged, so that I do not reorganise a week of study around a single bad morning.
5. As a Candidate, I want a Topic's reading to firm up as I am examined on it repeatedly, so that confidence in the claim tracks the evidence behind it.
6. As a Candidate, I want to see which Topics look weakest, so that I know where to spend study time.
7. As a Candidate, I want to know that answering after a hint still counts as an answer, so that asking for help does not feel like forfeiting the question.
8. As a Candidate, I want to see who graded each answer and on what provider, so that a score is attributable rather than anonymous.
9. As a Candidate, I want an answer graded against an authoritative Answer Key to carry more weight than one graded on a model's judgment, so that my record reflects how reliably it was measured.
10. As a Candidate, I want my Topic Confidence to survive across Sessions, so that practice accumulates rather than resetting.
11. As a Candidate, I want my record to survive a rewrite of the interview engine, so that months of practice are not discarded by a deploy.
12. As the Interviewer, I want to be handed the next Topic to examine, so that selection is a decision the system makes rather than a prompt the model improvises.
13. As the Interviewer, I want Topic selection to favour Topics that are weak or untested, so that a Session spends its time where it is most informative.
14. As the Interviewer, I want selection to be stochastic rather than always-the-weakest, so that two Sessions in a row are not identical.
15. As the Interviewer, I want an already-visited Topic excluded within the same Session, so that one Session does not examine the same Topic twice.
16. As the Interviewer, I want the opening question of a Session to be the first item of a plan ranked before the Session began, so that a Session starts where the ranking says it should rather than wherever a mid-Session draw lands.
17. As the Interviewer, I want selection confined to the Session's chosen Modules, so that scope is enforced by the selector and not by asking the model nicely.

> **Amended by ISSUE-0042 (§16).** The curriculum-order exemption existed
> because the sampler ran *inside* the loop: the opening Topic had to be spared
> it, or a Session could open on the hardest thing the Candidate had never seen.
> The sampler now runs once, before the first question, over the whole scope,
> and the ranking it produces *is* the order the Session asks in — so there is
> no mid-Session draw left to exempt the opening from. §12–15 and §17 hold
> unchanged; what hands the Interviewer its next Topic is the plan rather than
> a call to the selector.
18. As the Interviewer, I want to seed a Session's opening difficulty from prior Topic Confidence, so that a returning Candidate is not restarted from scratch.
19. As the graph, I want to open a Topic Visit and receive an id for it, so that everything that follows — grading, metering, evidence — keys on one identifier.
20. As the graph, I want an Evidence write to be idempotent on the Topic Visit id, so that a retry, a resume, or a confused host cannot double-count.
21. As the graph, I want a Topic Visit to produce exactly one Evidence row however many Answer Turns it contained, so that probing one concept three times is one observation and not three.
22. As the graph, I want an ungraded Topic Visit to write no Evidence at all, so that an interrupted Session leaves no half-observation behind.
23. As the graph, I want an interrupted Topic Visit to stay open until it is graded, so that resumption can finish it rather than skip it.
24. As the graph, I want the weight applied automatically from the Grading Mode recorded on the Visit, so that a weight cannot be attached by hand or by a model.
25. As the Judge, I want to submit a score and have the tracker decide the weight, so that scoring and trust stay separate concerns.
26. As a system operator, I want every Evidence row to store the raw exchange behind it, so that any score can be re-judged later.
27. As a system operator, I want every Evidence row to record its rubric version, so that grader drift is distinguishable from prompt drift.
28. As a system operator, I want every Evidence row to record grader identity and provider, so that a future normaliser can be measured from production data rather than guessed.
29. As a system operator, I want to re-judge a batch of stored exchanges with a reference grader, so that mis-weighted history can be rebuilt rather than written off.
30. As a system operator, I want Topic Confidence stored in a table I own rather than inside a framework's state, so that reading it does not require instantiating a graph.
31. As a system operator, I want Topic Confidence to be readable outside a Session, so that reporting and Session seeding do not depend on the interview engine.
32. As a system operator, I want a Topic Confidence row to be created lazily at first Evidence, so that 71 empty rows per Candidate are not written before anyone is examined.
33. As a system operator, I want Evidence rows to be append-only, so that the permanence the design assumes is enforced by the store rather than by convention.
34. As a system operator, I want to know the effective evidence behind a Topic rather than a question count, so that `α + β` keeps the meaning the weighting scheme gave it.
35. As a reporting surface, I want the Evidence Floor bands read off the posterior as a credible interval, so that the boundary between *untested*, *hedged* and *firm* is derived rather than hand-picked.
36. As a reporting surface, I want to be refused a Mastery percentage below the floor, so that a number that is barely a guess cannot be rendered as one that isn't.
37. As a future maintainer, I want the Grading Mode weights held as three named constants in one place, so that changing them is a visible decision.
38. As a future maintainer, I want no provider normaliser to exist until data supports one, so that a fitted constant with nothing behind it never makes `α + β` uninterpretable.

## Implementation Decisions

**Modules built**

- *Confidence Math* — pure functions over `(α, β)`: apply Evidence, read Mastery, read Coverage, read the credible interval, band a Topic against the Evidence Floor, sample a posterior. No storage, no clock, no randomness it does not receive. The deepest module in the system and the one everything else depends on being right.
- *Topic Confidence Store* — the table we own, `(candidate_id, topic_id, alpha, beta, updated_at)`. Read and written by graph nodes, owned by neither the graph nor a framework abstraction (ADR-0003).
- *Evidence Ledger* — append-only record of every graded Topic Visit: score, Grading Mode, weight applied, grader provenance, provider, rubric version, and the raw exchange. Idempotent on `topic_visit_id`.
- *Topic Visit Lifecycle* — opens a Visit, holds it open until graded, closes it on the Evidence write. The single place where "one Visit, one Evidence row" is enforced.
- *Topic Selector* — Thompson sampling over the in-scope Topics, with the Session's already-visited set excluded and the opening question exempted.
- *Confidence Reporting* — turns stored posteriors into the readings a Candidate or a Session sees. Coverage and Mastery are separate outputs; there is no combined figure to accidentally use.

**The update rule**

A Topic Visit yields a score `s` in 0..1 from the Judge and carries a weight `w`
set by its Grading Mode:

| Grading Mode | Weight |
|---|---|
| Ground-Truth-graded | 1.0 |
| Text-grounded | 0.7 |
| Model judgment | 0.5 |

The update is `α += w·s` and `β += w·(1−s)`.

`s` and `w` are never conflated. `w` is trust in the Grading Mode; `s` is quality
of the answer. Hint assistance is expressed in `s` — an answer reached after two
hints is a real answer worth roughly half — and never as a reduced weight.

The weights are deliberately coarse and are three named constants. If they ever
need tuning to three decimals, the model is wrong, not the numbers.

**Consequence accepted:** `α + β` is not a count of questions. It is effective
evidence, and Coverage reads as "effective Topic Visits". Everything that reports
Coverage says so.

**The prior**

A uniform prior, `α = β = 1`, held as one named constant. It is what makes an
untested Topic read as *unknown* rather than as zero. Rows are created lazily at
first Evidence; a missing row and a prior row are the same thing to every reader.

**Idempotency**

The Evidence write keys on a server-issued `topic_visit_id`. A second write for
the same id is a no-op that returns the existing row, not an error and not a
second update. This is the invariant that survives MCP Mode, where the caller is
a ReAct agent we do not control — so it is enforced in the store, never asked for
in a prompt.

**Grading Mode is per Visit, not per Topic**

The dossier reports the strongest mode a Topic *can* support; the Visit records
the mode the question was actually written and graded under. A future code-editor
surface adds a deterministic mode as an additive field rather than a migration.

**Selection**

Thompson sampling: draw one sample from each in-scope Topic's posterior, examine
the highest. Untested Topics sample widely, so they are naturally explored
without a separate exploration rule. Two exemptions, both explicit: the Session's
opening Topic is chosen by curriculum order, and Topics already visited in the
Session are excluded from the draw.

Randomness is injected, not called. The selector receives its source of
randomness so that a Session can be replayed deterministically (ADR-0001).

**Evidence Floor**

Bands are read off the posterior's credible interval, not chosen by hand. Below
the floor the tracker reports *Untested* and nothing more; above it, a hedged
reading; above a higher floor, a firm one. The reporting module cannot be asked
for a bare Mastery percentage on a Topic below the floor — that call does not
exist.

**Persistence**

Topic Confidence and Evidence live in tables we own. Graph checkpoints do not
(ADR-0003): they have opposite lifecycles, and a schema migration may discard
checkpoints outside the resumption window but may never touch these.

**Re-judgeability**

Every Evidence row stores enough to be re-scored by a different grader later:
question, answer, grounding reference, Grading Mode, grader identity, provider,
rubric version. This is what makes a provider normaliser derivable from
production data rather than guessed — and it is why no normaliser is built now.

## Testing Decisions

This is the module the PRD set is most confident about testing, because it is
almost entirely pure. A good test states a property of the record — what a
Candidate would notice if it broke — and asserts on returned readings, not on how
a posterior was computed or which query ran.

**Confidence Math — exhaustively tested.**

- an untested Topic reads as Untested, not as 0% Mastery
- a Topic below the Evidence Floor cannot be rendered as a bare percentage
- one perfect Ground-Truth-graded answer and one perfect Model-judgment answer produce different evidence counts and different interval widths
- repeated identical evidence narrows the credible interval while leaving the mean stable
- `s` and `w` are independently varied: a half-score at weight 1.0 and a full score at weight 0.5 are distinguishable in the resulting posterior
- Mastery and Coverage move independently — a Topic can be well-covered and weak, or barely covered and strong
- boundary scores 0 and 1 are handled without producing a degenerate distribution
- Evidence Floor bands are monotone: more evidence never moves a Topic from firm back to hedged at the same mean

**Evidence Ledger and Topic Visit lifecycle — tested on behaviour.**

- one Topic Visit with four Answer Turns produces exactly one Evidence row
- writing Evidence twice for the same `topic_visit_id` leaves the posterior unchanged and returns the existing row
- a Topic Visit that is opened and never graded writes no Evidence
- an interrupted Visit remains open and is closeable on resumption
- the weight applied is derived from the Visit's recorded Grading Mode; a weight cannot be supplied by the caller
- provenance, provider and rubric version are present on every row
- the raw exchange stored round-trips well enough to re-judge from
- rows are append-only: an attempt to mutate one is rejected

**Topic Selector — tested with injected randomness, so it is deterministic.**

- selection never returns a Topic outside the Session's chosen Modules
- selection never returns a Topic already visited in this Session
- the opening Topic follows curriculum order and ignores the posteriors
- given a fixed random source, an all-untested Candidate's selection sequence is reproducible
- a Topic with strong evidence of mastery is selected less often than a weak one, over a large fixed-seed sample
- a Session scoped to a Module whose Topics are all visited terminates rather than looping

**What is deliberately not tested.** Whether the weights are the *right* weights.
That is unanswerable without production data, which is why the constants are
coarse and named.

**Prior art.** PRD-0001's validator tests establish the pattern: fixtures as
data, assertions on returned values, no mocking of the module under test. The
math module needs no fixtures beyond literal numbers.

## Out of Scope

- A provider normaliser. Explicitly deferred until enough graded rows exist to measure one; storing provenance is what keeps it possible.
- An adversarial second-opinion Judge. Deferred in ADR-0002 pending measurable drift.
- Self-rated confidence as a second axis. Cheap to add later, nothing blocks it, not now.
- Mastery trend across Sessions. Requires Session history that does not exist yet; additive at no cost.
- Adaptive Session termination on expected information gain. The sampling machinery supports it; the threshold needs data.
- Difficulty as a stored property. The Corpus records none and derives none.
- Candidate-facing charts and dashboards. Reporting here produces readings, not pixels.
- Cross-Candidate aggregation, cohort comparison, leaderboards.

## Further Notes

71 Topics is the size of the table per Candidate — small enough that Thompson
sampling over the whole in-scope set is a trivial computation and no index
strategy is interesting.

The single most consequential line in this PRD is that Evidence is append-only
and idempotent on a server-issued id. Every other guarantee in the system —
replayability, resumption, MCP Mode's cross-mode invariant, the future
normaliser — is downstream of it.

The reason Coverage and Mastery are never fused is worth restating for whoever
is later asked for "one number": a tracker that conflates them cannot tell an
unasked Topic from a failed one, which is precisely what the Interviewer must
know to choose what to ask next. A single percentage is not a simplification of
this record. It is a different, worse record.
