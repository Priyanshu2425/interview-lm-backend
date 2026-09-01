# ISSUE-0043 — The Judge reads two dimensions

Status: resolved
Type: AFK
Source: SPEC-0007 §10; amends ADR-0002
Covers: how much of the source was explained, and how close to correct it was

## What to build

One number cannot say both "this answer covered the material" and "this answer was
right". A Candidate who explains the course material faithfully and a Candidate who
answers correctly from elsewhere are different readings, and today they collapse.

Rubric v2 returns three lines:

    SOURCE: <0.0-1.0, how much of the supplied material the answer explained>
    TRUTH:  <0.0-1.0, how close to correct on the subject>
    WHY:    <one or two sentences, addressed to the candidate>

`Verdict` becomes `(source_score: float | None, truth_score: float, rationale,
rubric_version)`. `RUBRIC_VERSION` goes to `v2`.

Evidence gains `source_score` (nullable) and `truth_score`. `score` stays, as the
combination.

## One posterior, and the combination is stated once

Both sub-scores are stored and both are reported. Only one number reaches the Beta
update, and the rule lives in `judge.py` where it can be read:

- `GROUND_TRUTH` and `TEXT_GROUNDED`: `score = 0.5 * source + 0.5 * truth`
- `MODEL_JUDGMENT`: there is no source, so `source_score` is `None` and
  `score = truth_score`

`math.py` is untouched. `evidence_delta(score, mode.weight)` receives the combination
exactly as it receives a score today, so Coverage, the bands and the Evidence Floor
all keep working without knowing this happened.

`GradingMode` is untouched too. It still picks exactly one grounding tier and still
supplies the weight — the trust owed to the grounding, which is a different question
from how well the answer used it.

## Two readings, never fused into one

`source_score` and `truth_score` are reported separately, always. The temptation to
average them into a headline figure is the same temptation `AGENTS.md` already
refuses for Coverage and Mastery, and for the same reason: the average of two
different questions answers neither. The combination that feeds the posterior is an
internal input to the math, not a reading shown as a score.

## Acceptance criteria

- [x] The Judge parses all three lines; a missing `TRUTH` raises rather than defaults
- [x] A sub-score outside 0..1 is rejected, not clamped
- [x] Under `MODEL_JUDGMENT`, `source_score` is null and `score` equals `truth_score`
- [x] Under the grounded modes, `score` is the stated combination
- [x] Both sub-scores reach the Evidence row
- [x] `math.py` is unchanged, and `test_confidence.py` passes untouched
- [x] `Verdict.score` still resolves, so `rejudge.py` and `mcp/server.py` compile
- [x] ADR-0002 amended: the Judge is still blind, and now reads two dimensions

## Blocked by

- ISSUE-0039 — the Evidence columns

## What landed

Rubric v2 asks for SOURCE and TRUTH beside WHY, and `RUBRIC_VERSION` is `v2`.
`Verdict` is `(source_score, truth_score, rationale, rubric_version)` with
`score` a property over the two — which is where the combination is stated, and
why `rejudge.py` and `mcp/server.py` needed no change to keep reading it. Both
sub-scores travel through the graph state and land on the Evidence row beside
`score`. `math.py`, `GradingMode` and `test_confidence.py` are untouched.

`graph/sessions.py` had a second `RUBRIC_VERSION = "v1"` of its own, which the
Session row and every Evidence write read. It re-exports the Judge's constant
now: the rubric's version is the Judge's fact, and a Session that recorded a
rubric the Judge never ran was the bug the duplicate was waiting to become.

## Deviations

**A missing SOURCE raises too, under the grounded modes.** The ticket names only
TRUTH. Defaulting a missing SOURCE would silently turn a grounded reading into
an ungrounded one and the row would not say so — the same argument the ticket
makes for TRUTH.

**The rubric asked of `MODEL_JUDGMENT` has two lines, not three.** There is no
material to have explained, so asking for SOURCE would invite a figure about
nothing. `_parse` keys the SOURCE decision on the grounding the call actually
sent rather than on the mode's name; the two agree wherever a Verdict is
written, and where a dossier has lost the material its mode claims, the answer
was still graded against nothing, so there is still no SOURCE to record.

**The scripted provider's reply changed shape.** `INTERVIEWER_FAKE_MODEL=1` now
returns `SOURCE: 0.8 TRUTH: 0.8 WHY: fine.`; `AGENTS.md` and `README.md` say so.
