# ISSUE-0046 — The documents catch up

Status: open
Type: **HITL**
Source: this set
Covers: the decision record, after the machine changed underneath it

## What to build

Five slices moved the load-bearing ideas in this repository. A decision record that
still describes the old machine is worse than none, because it is believed.

**Amend ADR-0004** — the unit of Evidence is the Topic within a Session, not the
Topic Visit. Name what did not change: one Beta observation per Topic per Session,
before and after. Name what did: an observation may be assembled from several
questions, and a question may contribute to several observations.

**Amend ADR-0005** — Thompson sampling did not die, it moved. It runs once, before
the first question, over what previous Sessions established, instead of after every
Visit. Name the sentence that changed and the ones that did not.

**Amend ADR-0001** — the node list in the header is now wrong. `build_plan` and
`grade_session` exist; `grade` and `update_confidence` no longer run in the loop.

**Amend ADR-0002** — the Judge is still blind, and now reads two dimensions. The
blindness argument is unchanged; what is new is that a spanning question grades once
per Topic and each grading sees only its own Topic's grounding.

**New ADR — the plan is fixed before the first question.** This is the decision the
whole set turns on, and it is not recorded anywhere: fixing the plan up front is what
removes the loop's dependency on a freshly updated posterior, which is what lets
grading move to the end. Write down that trade, including what was given up —
adaptive selection within a Session — and why the plan being legible to the Candidate
was worth it.

**Amend PRD-0003** §12–14 — no score after each Topic Visit; the score arrives once,
in the report.

**Extend CONTEXT.md** — Plan, Plan Item, Message, and Topic Visit's new meaning. The
glossary is the thing new work is read against, and a Topic Visit that no longer
means what the glossary says is a trap.

## Why HITL

Several of these amendments reverse decisions that were argued carefully the first
time. A reversal nobody signs is indistinguishable from a rule nobody read — which is
the argument ADR-0021 already had to make about ISSUE-0029.

## Acceptance criteria

- [ ] ADR-0004, 0005, 0001 and 0002 amended, each naming what changed and what did not
- [ ] A new ADR records the fixed-plan trade and what it cost
- [ ] PRD-0003 amended
- [ ] CONTEXT.md carries Plan, Plan Item, Message, and the new Topic Visit
- [ ] `docs/issues/README.md` reflects the resolved state of 0039–0046
- [ ] No document still describes in-loop grading as current

## Blocked by

- ISSUE-0045 — the documents describe the machine once it is finished
