# ISSUE-0028 — A deck with no words is still a Corpus

Status: resolved — decided against, and recorded (ADR-0024)
Type: **HITL**
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

## The decision (ADR-0024)

**Answered third question first, as this issue advised: no caption model.** A
dossier assembled from captions is a description a model wrote of the
Candidate's material, and examining somebody on it measures how well they
explain a machine's account of their own slide. Worse where the grading is
strongest: ADR-0002's Judge works against authored spans, and captions are
nobody's material.

That answer makes the first two questions moot rather than concrete, which is
the opposite of what this issue predicted and is the better outcome: no
figure-only Topic is created, so there is nothing to ask about it and no Grading
Mode for it to claim.

What was built is what follows: **the refusal now describes the material rather
than the parser.** A deck says how many figures it holds, says that pictures
alone are not examinable, and says the document is kept — which it is
(ISSUE-0033), so reversing this costs an ingest and nothing else.

Figures keep the job ADR-0017 gave them: attaching to the Topic that
*surrounding prose* drew, so a citation can show the diagram a question came
from. A figure may support a question grounded in text. It may not be the thing
a question is grounded in.

## Why nothing more was built

This slice says, in its own body, that the third open question *"would make this
slice mostly disappear"*. Building the clusterer half first is therefore not a
head start — it is work with a live chance of being deleted by the answer, and
the half-built state it would leave is worse than the stub it replaces:

A Topic made only of figures has no prose, and `corpus_view` composes a Module
from text chunks. Figure-only Topics could be **stored** without answering the
grading question, but they could not be **served** — which is a Topic that
exists in `content`, is keyed on by nothing, and appears nowhere. That is
precisely the orphan state ISSUE-0026's atomicity exists to prevent, arrived at
deliberately rather than by accident.

So the code stops before the first line, and the questions are stated instead.

## What changed under it since it was written

**The document is kept now (ISSUE-0033).** When this was written, a scanned deck
was read once and discarded, so answering the question later would have meant
asking every Candidate to upload their decks again. The bytes are in the object
store under the owner's prefix, content-addressed, and `re_extract` already
re-runs extraction from them.

That converts the cost of waiting from *material lost* to *material idle*, which
is the difference between a decision that has to be made now and one that can be
made well.

**An un-ingested document is a state, not a stub (ISSUE-0035).** `state` is now
`uploaded | ingesting | ready | failed | stub`, and a document that is listed and
not selectable already says why on the surface. Whatever the answer is, it lands
on a column that already carries states rather than needing a new concept.

## The three questions, sharpened

1. **What does an examiner ask about a Topic of pictures?** Not rhetorical: the
   Interviewer composes a question from dossier prose, and there is none. Does a
   figure-only Topic enter Thompson sampling at all, or is it material a
   Candidate can hold and never be examined on?
2. **Which Grading Mode can it honestly claim?** It cannot be Text-grounded in
   the sense ADR-0002's Judge means, because there is no span to ground against.
   `model_judgment` is available and is the weakest reading this product offers.
   Is a Topic gradeable only by model judgment worth examining, or is "not
   examinable" the honest answer?
3. **Does a caption model earn its place?** If figures become prose, the rest of
   the pipeline already knows what to do and questions 1 and 2 do not arise. It
   is a second model in the image, a second cost per ingest, and a second thing
   that can be wrong about a Candidate's material — and it is the only answer
   that makes a figure-only deck a first-class Corpus rather than a tolerated
   one.

Answering 3 first is the cheapest path: yes deletes 1 and 2, no makes them
concrete.
