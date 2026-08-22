# ISSUE-0032 — A Corpus has an owner, and a shared one cannot be deleted

Status: open
Type: AFK
Source: SPEC-0006 §Ownership; ADR-0010; ISSUE-0027
Covers: the split between shared and personal, and the guard that makes it safe

## What to build

A Corpus is owned by the platform or by a Candidate, and the difference shows in
exactly two places: who may write to it, and whether it can produce a comparison.

**Shared** is imported once by an operator and read-only to every Candidate. All
of them get the same `topic_id`s, which is the entire reason it exists — Topic
Confidence is keyed on `topic_id`, so a shared Corpus is what makes two people's
Mastery on a Topic the same measurement rather than two unrelated ones.

**Personal** is a Candidate's own uploads, exactly as notebooks behave today:
theirs, private, deletable, never compared to anyone. Their cohort is one by
construction, so no rule is needed to stop a comparison — but say so in a test,
because the absence of a rule is not obvious to the next reader.

**The delete guard is the point of this slice.** ADR-0010 defines `content` as
"the Candidate's, and deleted when they say so". A shared Corpus is not that, and
ISSUE-0027's retire path must refuse one. Without the guard, a Candidate deleting
a Corpus they did not create retires the Topic ids that every other Candidate's
Evidence points at — and nothing errors. The damage surfaces when somebody asks
why their record looks thinner than it did.

Personal remains the default. A deployment that never creates a shared Corpus
behaves exactly as today.

## Acceptance criteria

- [ ] A Corpus carries an owner and a visibility, and existing rows migrate to personal
- [ ] A Candidate may add Sources to their own Corpus and not to a shared one
- [ ] Deleting a shared Corpus is refused with a named code the surface can render
- [ ] The refusal is proved by a test, not left to the absence of a route
- [ ] Deleting a personal Corpus behaves exactly as ISSUE-0027 already requires, Evidence surviving
- [ ] An operator can create a shared Corpus and a Candidate cannot
- [ ] A shared Corpus is visible to every Candidate and appears in the picker
- [ ] Two Candidates examined on one shared Topic hold the same `topic_id`
- [ ] A personal Corpus yields no comparison, and a test says so

## Blocked by

- None — can start immediately
