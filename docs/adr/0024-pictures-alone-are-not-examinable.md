# Pictures alone are not examinable, and no caption model is added to pretend otherwise

Decides: ISSUE-0028 (all three of its open questions)
Source: ADR-0017; ADR-0002 §the Judge; ISSUE-0023 §stub Module; PRODUCT.md
Principle 4

## The decision

A Source that extracts no text stays a **stub**. No Topic is minted from
figures, no caption model is introduced, and a Topic whose only material is
pictures does not exist.

What changes is what the refusal says. A deck of slides is not empty — it is
full of pictures — so the stub names what the document actually holds:

> *42 figures and no text. Pictures alone are not examinable here: a Topic is
> something you can be asked to explain, and there is nothing written to ground
> a question in. The document is kept, so it can be re-read if that ever
> changes.*

## Answering the third question first, as ISSUE-0028 advised

**Does a caption model earn its place?** No.

Captioning would turn figures into prose the rest of the pipeline already knows
how to handle, and it is genuinely the only answer that makes a figure-only deck
a first-class Corpus. It is refused because of what would then be measured.

A dossier assembled from captions is a description **a model wrote of the
Candidate's material**. Examining somebody on it measures how well they can
explain a machine's account of their own slide, and reports the result as
Mastery of the Topic. That is a figure this product cannot justify, which is
Principle 4 in its original words.

It gets worse where the grading is best. ADR-0002's Judge is blind and works
against spans of authored text; Ground Truth and Text-grounded modes exist
because that text is the Candidate's own material. Captions would be graded the
same way while being nobody's material, so the strongest reading this product
offers would be attached to text that no author ever wrote. A weaker ceiling
would not fix it — `model_judgment` on generated prose is a model grading its
own description.

## The first two questions, answered by that

**What does an examiner ask about a Topic of pictures?** Nothing, because no
such Topic is created. The Interviewer composes from dossier prose and there is
none; inventing the prose is the answer just refused.

**Which Grading Mode could it claim?** None honestly, which is the same
sentence: not Text-grounded (no authored span), not Ground Truth (no answer
key), and `model_judgment` over generated captions is circular. "Not examinable"
is the honest reading, and this product prefers a stated absence to a weak
figure — the same instinct that makes an untested Topic read *Untested* rather
than zero.

## What figures are still for

ADR-0017 put figures and prose in one embedding space, and that decision stands
and is used. A figure attaches to the Topic its **surrounding prose** drew, so a
citation can show the diagram a question came from. That is attribution, which
is the use ADR-0005 has permitted since its first amendment, and it needs no
Topic made of pictures.

The distinction is the whole ADR: a figure may **support** a question grounded
in text. It may not **be** the thing a question is grounded in.

## Why the cost of waiting is low

ISSUE-0033 keeps the uploaded document, content-addressed, under the owner's
prefix. When this was first raised, a scanned deck was read once and discarded,
so a later reversal would have meant asking every Candidate to upload their
decks again. It would not now: `re_extract` re-runs extraction from the stored
bytes, so reversing this ADR costs an ingest and nothing else.

That is why the stub says *"the document is kept"* rather than only *"not
examinable"*.

## Revisiting

Two things would reopen it, and neither is a model getting better at captions.

A way to grade a **spoken or written explanation of an image against the image
itself**, rather than against prose about it — that is a different Judge, not a
different ingest.

Or a Candidate's own captions: text they wrote about their own slides is their
material, and everything above stops applying.
