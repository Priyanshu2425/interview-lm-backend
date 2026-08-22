# ISSUE-0036 — Where you stand on a Topic

Status: open
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

- [ ] A rank is returned for a Topic in a shared Corpus the Candidate has been examined on
- [ ] Candidates below the Evidence Floor are excluded, never counted as zero
- [ ] Overlapping posteriors share a position, and the response says the position is shared
- [ ] Fewer than the Cohort Floor of tested Candidates yields no rank and a stated reason
- [ ] A Topic the Candidate has not been examined on yields no rank
- [ ] A personal Corpus never yields a rank
- [ ] No endpoint returns a Candidate's overall position, or any figure combining Coverage and Mastery
- [ ] The Cohort Floor is one named constant, documented as provisional
- [ ] The placement is chosen by a human and recorded, with the reason it does not read as a recommendation

## Blocked by

- ISSUE-0034 — without shared `topic_id`s there is nothing to compare
