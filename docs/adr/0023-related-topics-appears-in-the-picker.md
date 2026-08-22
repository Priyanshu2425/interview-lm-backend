# Related Topics appears in the Module picker, and nowhere a score is

Decides: ISSUE-0031 (the placement it was waiting for)
Source: ISSUE-0031 §three placements; PRODUCT.md Principle 4;
FUTURE-PIPELINE §Topic recommendation

## The decision

**Placement C.** Related Topics is rendered on the Session setup screen, under
the Module picker, as *"Modules this scope touches"*. It appears nowhere else —
not on a Topic Visit result, not in the Session summary, not beside any figure
about a Candidate.

## Why the placement is the whole decision

The reading is the same in all three places. What changes is what a Candidate
reads it as.

Related Topics is a claim about the **material**: these Topics are near each
other in the embedding space. Put it beside a score and it becomes a claim about
the **person** — *and you should do these next* — which is Topic recommendation,
which does not exist here and is deferred in FUTURE-PIPELINE for want of
calibration data. Nothing in the rendering distinguishes the two readings. Only
the placement does.

**In the picker nothing has been measured yet.** There is no score for the list
to sit beside, no Band, no Coverage, no posterior — the Candidate has not been
examined at all. A list of Modules there can only be read as what it is: scope,
and what scope touches. That is why C is not merely the safest of the three but
the only one where the claim cannot slip.

**B was rejected outright**, and it is the placement that would have been most
*useful*. On a Topic Visit result the list appears at the exact moment a
Candidate has just been scored, and the most natural reading of "related to what
you just got wrong" is remediation. That is a study recommendation wearing a
statistic, and the product refuses it.

**A was rejected as second-best rather than as wrong.** The Session summary is
far from the moment of scoring and could carry a map of the material honestly.
It was not chosen because the summary is dense with the Candidate's own figures
— Coverage, Mastery, bands, per-Topic readings — and a list of Topics among them
inherits their frame whatever the copy says. C has no such neighbours.

## What the placement costs

The connection is shown before the Candidate knows which Topics they are weak
on, which is when it is least *interesting* to them. That is accepted. A reading
that is interesting because it arrives beside a failure is interesting for the
reason this ADR refuses.

## What holds it there

- The route takes **no `candidate_id`** and could not be made personal without a
  visible change. A test asserts the parameter is absent.
- The response carries no Coverage, no Mastery and no band. A test greps the
  response for them.
- Ordering and aggregation are the server's; the surface renders and sorts
  nothing (ADR-0009).
- The copy says *"a reading of the Corpus, not of you"* and a test asserts the
  words *should*, *recommend* and *improve* do not appear.
- A Topic with no neighbours, a Library too small to have any, and a deployment
  holding none all render as **nothing at all** — no empty state, no explanatory
  copy. All three are honest and all three look identical.

## Revisiting

If Topic recommendation is ever built — that is, once there is calibration data
to justify saying what a Candidate should study — this ADR is what has to be
reopened, and B becomes available in the same breath. Not before.
