# ISSUE-0036 — Where you stand on a Topic

Status: resolved
Type: **HITL**
Source: SPEC-0006 §Comparison; PRODUCT.md Principle 4; AGENTS.md §refusals
Covers: comparison that does not become a recommendation

## Why this one needs a human

The reading is mechanical. Where it *appears* is not.

A rank shown beside a score reads as *"study these next"* — which is Topic
recommendation, deferred in FUTURE-PIPELINE for want of calibration data, and a
claim about a person this measurement cannot support. The same trap ISSUE-0025
and ISSUE-0031 stopped in front of: the design system never drew this screen,
and inventing one is how a surface ships a control nobody sanctioned.

Build the reading and the route. Stop before the placement.

## What to build

A Candidate can see where they stand against everyone else examined on the same
shared Topic — as a rank within that Topic, never as a position in a list.

Ordering within one Topic uses Mastery alone and fuses nothing, so `#7 of 340`
is available and Principle 4 is untouched. What is not available is separating
two Candidates the mathematics cannot separate: Mastery is the mean of a Beta
posterior and carries a spread, so overlapping posteriors **share a position** —
`#7= of 340`.

Three rules hold it honest, and two are existing rules applied again:

**Only tested Candidates are in the cohort.** A Candidate whose Band is
`UNTESTED` is not counted as zero — that is the fabrication *untested is not
zero* exists to prevent, and it would drag every median down in proportion to
how many people had not got there yet. The gate is `Band.tells()`, already
written and already under test.

**A Cohort Floor, provisionally 10.** Below it, no rank: it reads *not enough
Candidates yet* and shows no number, the same shape and reasoning as *Untested*.
With exact ranks the argument is privacy rather than precision — `#1 of 2`
discloses the other Candidate completely. Unlike the Evidence Floor this number
is derived from nothing and is labelled a guess.

**Coverage is compared as Coverage**, separately, and never combined into a
position. No function returns the combination.

No new storage: `core.topic_confidence` is already keyed
`(candidate_id, topic_id)`.

## Acceptance criteria

- [x] A rank is returned for a Topic in a shared Corpus the Candidate has been examined on
- [x] Candidates below the Evidence Floor are excluded, never counted as zero
- [x] Overlapping posteriors share a position, and the response says the position is shared
- [x] Fewer than the Cohort Floor of tested Candidates yields no rank and a stated reason
- [x] A Topic the Candidate has not been examined on yields no rank
- [x] A personal Corpus never yields a rank
- [x] No endpoint returns a Candidate's overall position, or any figure combining Coverage and Mastery
- [x] The Cohort Floor is one named constant, documented as provisional
- [x] The placement is chosen and recorded, with the reason it does not read as a recommendation — **ADR-0022**

## Blocked by

- ISSUE-0034 — without shared `topic_id`s there is nothing to compare

## The placement, decided (ADR-0022)

**Inside the Evidence drawer, one Topic at a time, on request.** Not a column,
not the Mastery map, not the Topic Visit result.

The reading itself was never the danger. Many of them at once was: a rank in the
Evidence table is a column, a column can be read down the page, and a page of
Topics readable in rank order is a list of what to study next. So the placement
carries the constraint the data cannot — and the API's shape holds it, because
no route takes a list of Topics and none can be made to answer the column's
question. The fetch is gated on the drawer being open for the same reason: a
request per row would build the column whether or not anything rendered it.

Coverage is compared as Coverage, by a different hook, on a different screen,
beside the other Coverage readings. Nothing takes both.

This was decided rather than deferred because the goal for this session directed
it. It is written down so it can be argued with, and ADR-0022 names the two
things that would reopen it.

## How a shared position is decided

A Candidate is ranked by how many others are **definitely** above them — whose
credible interval sits entirely above theirs. Anyone merely probably above shares
the position instead.

That definition was chosen because overlap is not transitive: A can overlap B
and B overlap C while A and C are plainly apart. Counting only the unambiguously
higher is well defined whether or not the middle of the field forms a chain,
where "group the ties" is not.

## Two floors, and only one of them is derived

The Evidence Floor is a property of the posterior's spread and is measured. The
Cohort Floor is a privacy judgement and is a guess: `#1 of 2` discloses the other
Candidate completely, and ten is the smallest cohort in which one person's
position does not describe everybody else's. It is one constant, in one place,
labelled as provisional, and it takes a parameter so a deployment can state its
own without a second implementation appearing.

## The refusal, kept by absence

Coverage is compared by a different function returning a different shape, on its
own route. There is no function that takes both, no `overall_position`, and a
test walks the OpenAPI document to assert no path carries a rank across Topics.

`Band.tells()` is what SPEC-0006 calls the gate; in this codebase it is
`Band.reportable`, and that is what the cohort filter uses.
