# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Candidate** — the person being interviewed. Preparing for an AI/ML or DSA
engineering interview, working from 1.9 MB of Scaler Cortex course material they
have already read. Their failure mode is recognition mistaken for the ability to
explain under questioning. They practise in sessions of a duration they choose,
at a desk, alongside the course material, in daylight.

**Operator** — us. Watches pool funding, per-Provider spend and metering health.
A small internal audience, but a real one with its own surface (PRD-0005 §7).

Distinct from the user who commissioned the Corpus scrape, even when they are the
same person.

## Product Purpose

Examine a Candidate on a Corpus and build a durable, honest record of what they
can actually explain. Reading is not preparation; the examination is the product.
Success is a Candidate who knows which Topics they were tested on, which look
weak, and — critically — which they have never been asked about at all.

## Positioning

Two things a neighbouring product could not truthfully copy:

1. **Untested and weak are different facts, and stay different all the way to the
   screen.** Topic Confidence is a Beta distribution (`α`, `β`) per Candidate per
   Topic. Mastery is its mean, Coverage its evidence count, Confidence its
   spread. A product storing one score cannot tell an unasked Topic from a failed
   one, which is exactly what choosing the next question requires.
2. **The grader never held the conversation.** The Judge is a separate, blind
   call — it sees the question, the answer and the grounding, and has no memory of
   the Candidate having been articulate or likeable. Sycophancy here is not a
   prompt defect; it is conversational context working as intended.

## Operating Context

A **Session** is scoped to chosen Modules and a chosen duration, both fixed
before it starts. It proceeds as **Topic Visits** — one Topic examined through an
opening question, follow-ups, hints and probing, taken together. One Visit yields
exactly one score and exactly one write to that Topic's Topic Confidence, however
many Answer Turns it contained.

The deadline is soft: a Session ends *after* the current Topic Visit finishes,
never inside one. Sessions are resumable; an interrupted Visit stays open until
graded.

Surfaces: **text** is what ships (the Answer Turn is unambiguous — the Candidate
submits). **Voice** and **code editor** are named, designed for, and not built —
voice because pauses are not endings and barge-in moves the boundary backwards;
the code editor because a test run may precede the answer being final.

## Capabilities and Constraints

- Corpus: 2 Tracks, 15 Modules, 71 Topics. AIML carries 26 Assignment/Answer Key pairs (Modules 1–6); DSA carries no Ground Truth at all.
- Three **Grading Modes**, weighted 1.0 / 0.7 / 0.5 — Ground-Truth-graded, Text-grounded, Model judgment. Absence of an Answer Key moves a Module down a mode; it never makes it unusable.
- **Evidence Floor** — below it the tracker reports *Untested* and nothing more. There is no call that returns a bare Mastery percentage for a Topic below the floor.
- **Coverage and Mastery are reported separately, never fused into one figure.**
- **Difficulty is not a property of the Corpus.** Cortex records none and we derive none. No screen may label a question easy or hard.
- **"Progress" is a retired word.** Cortex owns it and means "classes opened". Where Cortex's own number is meant, say *Cortex Progress*; otherwise say Coverage.
- **Credit** = one US cent of OpenRouter cost. Session cost is not knowable in advance and is never quoted. BYOK Candidates spend no Credits and must never be shown a Credit message.
- **Grader Provenance** — grader identity and provider are recorded on every Evidence row and shown to the Candidate.
- Two run modes: **Managed** (our graph) and **MCP** (inside someone's Claude session).

## Brand Commitments

Scaler. Palette taken from Scaler's own shipped stylesheet, not from a marketing
screenshot: ink `#021028`, primary `#0041c9`, bright `#0080ff`, tint `#f6faff`,
success `#56c68e`, warning `#ffc834`, danger `#d0021b`, secondary violet
`#4c46d6`. Type: Source Sans Pro, Scaler's own face.

Layout structure is pinned by two reference images the user supplied: a mobile
app shell built around a single conversation, and a desktop working surface with
a persistent right rail of numbered questions. **Layout only** — the references
are video-call products; this one is text-first, with no video, no avatar, and no
face on screen.

## Evidence on Hand

- `data/corpus.json` (622 KB) and `data/markdown/**` — the real, scraped Corpus. Real Module, Topic and Class titles, real cuid ids.
- `CONTEXT.md` — the domain glossary, authoritative on vocabulary.
- `docs/adr/0001`–`0008`, `docs/prd/0001`–`0005`, `docs/spec/0005`.
- **No real Candidate data exists.** Every score, balance, transcript and posterior in a prototype is synthetic and must be labelled as such.
- No pricing, customers, benchmarks or launch claims exist. None may be invented.

## Product Principles

1. **Untested is not zero.** Every reading preserves the distinction, to the last pixel.
2. **Evidence outranks billing.** When they conflict, the permanent write wins — a Visit runs to completion on an exhausted balance rather than being truncated.
3. **Say which ledger you are on.** Provenance, provider and cost are shown, not hidden; a BYOK failure names the provider and never mentions Credits.
4. **Refuse the number you cannot justify.** No difficulty label, no fused Coverage-and-Mastery percentage, no Session price quoted in advance, no provider normaliser.
5. **The examination is the product.** Everything else is scaffolding around one conversation.

## Accessibility & Inclusion

Standard web accessibility. Two product-specific requirements: score and state
must never be carried by colour alone (the Evidence Floor bands are semantic, not
decorative), and the exchange surface must be fully keyboard-operable, since the
Answer Turn is a submit event.
