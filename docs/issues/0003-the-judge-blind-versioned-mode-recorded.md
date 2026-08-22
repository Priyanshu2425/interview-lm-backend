# ISSUE-0003 — The Judge: blind, versioned, mode-recorded

Status: ready-for-agent
Type: AFK
Source: PRD-0002, PRD-0003; ADR-0002
Covers: PRD-0003 §12, §13, §24, §25, §26, §27, §30–§33

## What to build

Replace the stubbed grade with a real **Judge**: a dedicated call that receives
the question, the answer, and the grounding behind it — and nothing else.

The Judge is not given conversation history and is not the call that conducted
the interview. The model that has just spent twenty minutes building rapport is
the worst available grader of that conversation, and a systematically generous
judge is the one failure that is invisible on reading a transcript. It returns a
score in 0..1 and a rationale, under a versioned rubric.

The **Question Writer** decides **Grading Mode** at the moment the question is
written, from what the question was actually grounded in: an Assignment with its
**Answer Key** → Ground-Truth-graded; Topic text with no Answer Key →
Text-grounded; no text at all → Model judgment. The dossier's ceiling bounds this
but does not set it, and the Visit records what actually happened.

**Grader Provenance** — grader identity, provider and rubric version — is
recorded on the Evidence row and shown to the Candidate. Screen 03 renders the
score with its rationale and that provenance directly beneath it.

## Acceptance criteria

- [ ] The Judge is called with question, answer and grounding, and with no conversation history — asserted on what the Judge received, not on the prompt text
- [ ] A Ground-Truth-graded call receives the Answer Key for the Assignment being graded and no other Answer Key
- [ ] A text-grounded call receives the dossier excerpt and no Answer Key
- [ ] A model-judgment call receives no grounding and is recorded as such
- [ ] The Grading Mode recorded on each Visit matches the grounding the question was written from
- [ ] The same question and answer scored twice with the same rubric version and stubbed model produce the same score
- [ ] Rubric version is present on every Evidence row
- [ ] A score outside 0..1 is rejected rather than written
- [ ] Grader identity and provider are present on every Evidence row
- [ ] No Answer Key is reachable through any Candidate-facing endpoint for an ungraded Visit
- [ ] Screen 03 shows score, rationale and provenance; the Answer Key appears only after grading
- [ ] The DSA Track is examinable end-to-end in Model judgment mode, anchored to the Topic's syllabus

## Blocked by

- ISSUE-0002 — the Judge replaces the skeleton's stubbed grade
