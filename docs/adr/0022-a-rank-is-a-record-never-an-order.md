# A rank appears in the record, one Topic at a time, and never as an order

Decides: ISSUE-0036 (the placement it was waiting for)
Source: SPEC-0006 §Comparison; PRODUCT.md Principle 4;
FUTURE-PIPELINE §Topic recommendation

## The decision

A Candidate's standing on a Topic appears **inside the Evidence drawer**, for
the one Topic whose drawer they opened, on the Session record. It appears
nowhere else: not as a column, not on the Mastery map, not beside a Band, and
not in any list.

Coverage is compared separately, as Coverage, on the Mastery screen beside the
other Coverage readings.

## Why the drawer, and not the row

The reading itself is safe. `#7= of 340 Candidates examined on this Topic` fuses
nothing: inside one Topic Mastery means one thing, so ordering it costs nothing
Principle 4 protects.

What is not safe is **many of them at once**. A rank in the Evidence table is a
column; a column can be read down the page; and a page of Topics that can be
read in rank order is a list of what to study next — which is Topic
recommendation, which does not exist here and is deferred in FUTURE-PIPELINE for
want of calibration data.

So the placement carries the constraint that the data cannot: **one Topic, on
request.** A Candidate opens a drawer to see what grounded a question, and the
standing is there beside the reading that Visit produced. Getting a second one
means closing this drawer and opening another, which is exactly the friction
that stops a set of ranks becoming a ranking.

The fetch is gated on the drawer being open, and that is the placement rather
than an optimisation: a request that fires per row would produce the column this
ADR exists to prevent, whether or not anything rendered it.

## What was rejected

**A column in the Evidence table.** The useful version, and the one that becomes
an order the moment there are three rows.

**The Mastery map.** Worse: it is already a grid of every Topic, sorted and
filtered, and a rank there is a leaderboard with extra steps.

**Anywhere near a Topic Visit result.** The same reasoning as ADR-0023: a figure
about the person, delivered at the moment of scoring, reads as a verdict and
then as remediation.

## What holds it there

- Below the Evidence Floor, below the Cohort Floor, and a Library nobody else
  holds are three different facts, and the surface renders the API's own
  sentence for each rather than composing one.
- A shared position renders `#7=` and says why: the posteriors overlap and the
  measurement cannot separate two Candidates.
- Coverage's comparison is a different hook, a different route and a different
  place on a different screen. No function anywhere takes both, and a test walks
  the OpenAPI document to assert no path returns a position across Topics.
- The Cohort Floor of 10 is a privacy judgement rather than a measurement, and
  it is labelled as provisional where it is set.

## Revisiting

Two things would reopen this. Calibration data that justified saying what a
Candidate should study — then the column becomes a design question rather than a
refusal. And real cohort sizes: a floor of ten that is never reached is a feature
that does not exist, and the number was a guess.
