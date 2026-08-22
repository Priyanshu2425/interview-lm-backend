# ISSUE-0028 — A deck with no words is still a Corpus

Status: open
Type: AFK
Source: ADR-0017; ISSUE-0023 §stub Module; ISSUE-0025

## Why this exists now

ADR-0017 put figures and prose in one embedding space and one table. A PDF that
extracts no text still becomes a **stub** (ISSUE-0023), because Topics are drawn
by clustering text and an image-only source has nothing for a figure to attach
to.

That is the right call for the slice that just landed and the wrong one for the
product. A scanned lecture handout and an exported slide deck are exactly the
material Candidates have, and both currently arrive as a Module that exists,
is visible, and says it carries nothing.

The shared space is what makes the fix possible: figures can be clustered into
Topics the same way chunks are, because they are vectors of the same width in
the same geometry.

## What to build

Cluster **figures** into Topics when a Source yields no text, using the existing
clusterer over the existing centroids. The Topic order rule still comes from
position — page, then figure index — never from the clusterer.

Open questions a human should settle before this starts:

- A Topic of pictures has no dossier text. What does the examiner ask about it,
  and does a Topic with no prose belong in Thompson sampling at all?
- Grading Mode: a figure-only Topic cannot be Text-grounded in the sense
  ADR-0002's Judge means. Is it `model_judgment`, or is it not examinable?
- Does a caption model earn its place here, turning figures into prose that the
  rest of the pipeline already knows how to handle?

The third would make this slice mostly disappear, which is a reason to ask
before building the first two.

## Blocked by

- Not blocked to *start*; blocked to *finish* on the grading question above.
