# ISSUE-0024 — Ground Truth mined from the notebook

Status: resolved
Type: AFK
Source: SPEC 2026-08-21 Notebook Adapter; PRD-0001 §4, §8, §9, §19; ADR-0002
Covers: spec §Decisions/Ground Truth

## What to build

The notebook's own answer keys, found rather than invented.

At label time, a cluster is also asked whether its chunks are **question and
answer shaped** — exercises with worked solutions, a quiz with an answer section,
an FAQ. Where they are, those chunks become `LeafKind.GROUND_TRUTH` leaves,
paired to the `LeafKind.PROMPT` leaf they answer, and that Topic reports
**Ground-Truth** grading. Everything else reports **Text-grounded**.

Nothing is generated. A Topic with no question/answer material does not receive a
model-written answer key, because a generated answer is model judgment wearing a
Ground Truth badge and Principle 4 refuses the number it cannot justify.

Ground Truth is stored in a **separate field** from teaching material and is never
merged into it. The question-asker receives the teaching material; the Judge
receives the grounding excerpt and, for a Ground-Truth Topic, the key retrievable
by the prompt leaf's id. The Judge's blindness (ADR-0002) is unchanged.

A notebook with no minable Ground Truth at all is valid and fully examinable at
Text-grounded weight, exactly as the DSA Track is today.

## Acceptance criteria

- [ ] A fixture source containing exercises with worked solutions yields paired PROMPT and GROUND_TRUTH leaves
- [ ] A Topic with mined Ground Truth reports `GradingMode.GROUND_TRUTH`; every other Topic reports `TEXT_GROUNDED`
- [ ] No Topic in a notebook Corpus ever reports Ground Truth without a GROUND_TRUTH leaf backing it
- [ ] Ground Truth text never appears in the teaching field handed to the question-asker, enforced by test over every fixture
- [ ] A Ground Truth leaf is retrievable by the id of the PROMPT leaf it answers
- [ ] Nothing in the pipeline writes a GROUND_TRUTH leaf whose text did not come from the source, enforced by comparing every key's text against source spans
- [ ] A notebook with no question/answer material ingests, validates, and is examinable at 0.7
- [ ] The Judge receives grounding and key only, never the conversation

## Blocked by

- ISSUE-0021 — labelling is where mining happens
