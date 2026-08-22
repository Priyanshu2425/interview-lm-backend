# Context

Glossary for the Scaler Cortex scraping project.

## Corpus

The retrievable body of knowledge extracted from Scaler Cortex. Chunked and
embedded for semantic query by an application.

Not "context" — that word is overloaded (agent context window, page context).
When we say what we are building, we say **Corpus**.

## Cortex

The source system: the Scaler dashboard at `cortex.scaler.com`, behind login.
Holds two **Tracks**.

## Track

A top-level division of Cortex. Exactly two exist:
- AI/ML Interview Preparation
- Data Structures and Algorithms Mastery

## Interviewer

The consuming agent. Reads the **Corpus** and conducts a mock interview against
a **Candidate** — asking questions, judging answers, adapting difficulty.

The Corpus exists to serve the Interviewer. It is not browsed by humans and not
queried in natural language by an end user.

## Candidate

The human being interviewed. Distinct from the user who commissioned the scrape,
even when they are the same person.

## Ground Truth

An authoritative answer that came from Cortex itself — an editorial solution,
a model answer, a stated complexity, a test case.

Distinct from an answer the **Interviewer** produces on its own judgment.
Every Corpus item records whether it carries Ground Truth, because grading
against Ground Truth and grading by model judgment are different acts with
different reliability.

Expected asymmetry: the DSA Track likely carries Ground Truth; the AI/ML Track
likely does not.

## Module

A Track's top-level division. AIML has 8; DSA has 7.
Carries a title, description, `order`, and `learningOutcomes`.

## Topic

A Module's subdivision, holding **Classes**. AIML has 57; DSA has 14.
In AIML's own prose a Topic is often called a "Pillar" — we say Topic.

## Class

The leaf unit of Cortex. A Class carries exactly one `contentType`:

- **text** — markdown in `textContent`. Self-contained and scrapeable.
- **video** — a live-session recording at a `videoUrl`. `textContent` is empty.
- **contest** — an external timed test at a `contestUrl`, described only by a
  `contestSyllabus` (topic strings) and `contestQuestions` (a count, not the
  questions). `textContent` is empty.

Only **text** Classes carry retrievable content. This is the boundary of the
Corpus as reachable through the course API.

## Answer Key

A Class whose `textContent` is worked solutions to the **Assignment** Class that
precedes it — the answer, the correct option, and the reasoning.

Answer Keys are the AIML Track's **Ground Truth**. There are 23.

## Assignment

A Class posing graded questions, paired with an **Answer Key**.
Assignment + Answer Key is a ready-made interview question with a rubric — the
single most valuable structure in Cortex for the **Interviewer**.

## Lecture Recording

The artifact behind a **Class** of contentType `video`. It does not live in
Cortex. It lives in Scaler Academy (`www.scaler.com/meetings/...`), a separate
product with its own account and its own sign-in.

Consequence: a Cortex session does not reach a Lecture Recording. The two
systems share a brand, not an identity.

## Contest

The external timed test behind a **Class** of contentType `contest`, hosted on
Scaler Academy. Deliberately out of scope — we keep its `contestSyllabus`
(the topic list) as curriculum metadata and take none of its problems.

## Session

One mock interview from start to finish, conducted by the **Interviewer**
against the **Candidate**.

A Session is scoped to one or more **Modules**, chosen before it begins. Every
question in the Session is drawn from within that scope.

Scope and load are different axes and must not be conflated:
- A Module is the unit of **scope** — what the Session is about.
- A Topic is the unit of **load** — what the Interviewer holds in context to
  ask one question (median ~5k tokens, never above ~10k).

A Session over three Modules still loads one Topic at a time.

A Session runs for a duration the **Candidate** chooses before it begins. The
deadline is soft: it ends the Session after the current **Topic Visit**
finishes, never inside one. A truncated Topic Visit would produce either no
**Evidence** or Evidence from a half-examined answer, and both corrupt the
record the Session exists to build.

Because length varies, Sessions are only comparable to other Sessions of the
same chosen duration. Anything measuring grading quality must group by it.

## Grading Mode

How the **Interviewer** judges a **Candidate**'s answer. Three modes, in
descending order of authority:

1. **Ground-Truth-graded** — the question came from an **Assignment** and is
   marked against its **Answer Key**. 26 pairs exist, all in AIML Modules 1–6.
2. **Text-grounded** — the Interviewer wrote the question from a Class's text
   and marks against that same text, held in the loaded Topic dossier. This is
   the default across the GenAI and Advanced AI agents Modules, which carry no
   Answer Keys but ~490 KB of material.
3. **Model judgment** — no Cortex text behind the question; the Interviewer
   relies on its own knowledge. The DSA Track runs here, anchored to
   `contestSyllabus` and Module ordering for scope.

Absence of an **Answer Key** does not make a Module unusable. It moves the
Session from mode 1 to mode 2.

## Performance History

Named here only because it came up: the **Candidate**'s record across past
**Sessions**. Not designed, not built, out of scope for the scrape.

Recorded so the term is not reinvented later under another name.

---

## A note on scope

The **Corpus** is source material: a read-only, faithful extract of Cortex, and
the truth about what the course contains. It is built and complete for text.

The consuming side — **Interviewer**, **Session**, **Grading Mode**,
**Performance History** — is now in design. Entries below the line were written
as vocabulary during the scrape and are being hardened into a specification.

One rule the Corpus owns and keeps: difficulty is not a property of the Corpus.
Cortex records none and we derive none.

---

## Progress — retired

Do not use this word. **Cortex** owns it: its dashboard means "classes opened"
(`8% overall progress`, `6 of 74 classes completed`) and exposes it at
`/api/progress/user/{id}`.

Cortex Progress says nothing about ability — a Candidate can hold 100% Progress
and answer nothing correctly. Where Cortex's own number is meant, say
**Cortex Progress** and never the bare word.

## Coverage

How much of the **Corpus** a **Candidate** has been examined on. A property of
the interviewing, not of the Candidate.

Measured against **Topics**: "asked about 12 of 57 Topics in the AIML Track".

## Mastery

How well a **Candidate** performs on a **Topic** when examined.

Independent of **Coverage** — they answer different questions. Coverage
distinguishes untouched from touched; Mastery distinguishes strong from weak.
A tracker that conflates them cannot tell an unasked Topic from a failed one,
which is exactly what the **Interviewer** must know to choose what to ask next.

## Topic Confidence

What is stored, per **Candidate** per **Topic**: a Beta distribution, held as
two numbers `α` and `β`.

One structure, three readings:
- **Mastery** is its mean, `α / (α + β)`
- **Coverage** is its evidence count, `α + β`
- **Confidence** proper is its spread — how sure we are of the mean

An untested Topic is not a zero. It is the prior, and it reads as *unknown*
rather than *weak*. This is the distinction a single score cannot make, and the
Interviewer depends on it to tell an unasked Topic from a failed one.

Held at **Topic** granularity — 71 of them. Not per **Class**, which is too
sparse to ever accumulate evidence, and not per **Module**, which is too coarse
to guide a question.

## Evidence

What a graded answer contributes to a **Topic Confidence**.

A **Topic Visit** yields a score `s` in 0..1 from the **Judge**, and carries a
weight `w` set by the **Grading Mode** it was graded under:

| Grading Mode | Weight |
|---|---|
| Ground-Truth-graded | 1.0 |
| Text-grounded | 0.7 |
| Model judgment | 0.5 |

The update is `α += w·s` and `β += w·(1−s)`.

The weights are deliberately coarse. They exist because most of the **Corpus**
grades in the weaker modes — all of DSA, and the two largest AIML Modules — so
equal weighting would inflate **Coverage** fastest exactly where the evidence is
softest. If these constants ever need tuning to three decimals, the model is
wrong, not the numbers.

`s` and `w` measure different things and must not be conflated. `w` is how far
the **Grading Mode** is trusted. `s` is how good the answer was — an answer
reached after two hints is a real answer worth roughly half, scored in `s`, not
discounted in `w`.

Consequence, accepted: `α + β` is no longer a count of questions. It is
effective evidence, and **Coverage** reads as "effective Topic Visits".

## Answer Turn

The boundary at which a **Candidate**'s answer is complete and may be graded.
Exactly one **Evidence** update follows exactly one Answer Turn.

Named because it is the one thing every surface must supply, and the one thing
surfaces disagree about:

- **Text** (the surface being built) — unambiguous; the Candidate submits.
- **Voice** (later) — genuinely hard; pauses are not endings, and barge-in
  means the boundary can move backwards.
- **Code editor** (later) — submission is explicit, but a test run may precede
  the answer being final.

The graph must treat an Answer Turn as an event it waits for, never as a read
from a particular kind of input. A surface that cannot say when a turn ended
cannot be plugged in.

## Judge

The role that scores an answer. Distinct from the **Interviewer**, which
conducts the conversation.

The Judge sees the question, the answer, and the **Ground Truth** or dossier
excerpt behind it. It does not see the conversation. It has no memory of the
**Candidate** having been articulate, likeable, or confident.

Separating the roles is not an optimisation. The Interviewer builds rapport
because that is its job; a grader holding that rapport is the definition of a
sycophantic one. The Judge produces the score `s` that becomes **Evidence**, and
Evidence is permanent.

## Topic Visit

One examination of one **Topic** within a **Session**: the opening question,
any follow-ups, hints, and probing, taken together.

A Topic Visit is the unit of **Evidence** — one visit produces exactly one
score and exactly one write to that Topic's **Topic Confidence**, however many
**Answer Turns** it contained.

Follow-ups are not independent trials. Probing the same concept three times is
one observation examined closely, not three observations.

## Evidence Floor

The amount of **Evidence** a **Topic** needs before the tracker will make a
claim about it.

Below the floor the tracker says *Untested* and nothing more. Above it, a
hedged reading. Above a higher floor, a firm one. The bands are read off the
posterior as a credible interval, not chosen by hand.

The floor exists because **Topic Confidence** was modelled as a distribution
precisely so that untested and weak are distinguishable. Rendering the mean as
a percentage would discard that at the last step — and a **Candidate** shown
"38%" after one bad answer will study to a number that is barely a guess.

**Coverage** and **Mastery** are reported as separate readings, never fused
into one figure. "Examined on 12 of 57 Topics" and "3 of those look weak" are
different facts, and a single percentage that merges them means nothing.

## Managed Mode

The **Session** runs on our own agent — the graph of ADR-0001 — with model
calls paid for either by the Candidate's own key or by our credit system.
We control the loop end to end.

## MCP Mode

The Session runs inside someone's Claude session. Our system is an MCP server;
the host Claude drives it through our tools, steered by prompts we supply.

The host is a ReAct agent we do not control. Prompts steer it; they do not
constrain it. Any invariant that matters must therefore be enforced by the
server, never asked for in a prompt.

Two invariants survive both modes:

1. **Evidence is written once per Topic Visit.** Not because the host is asked
   to behave, but because the write is idempotent on a server-issued Topic Visit
   id, and the Session will not advance while a Visit is unresolved.
2. **No Answer Key enters the interviewing context.** The host holds its
   context in front of the Candidate, so an **Answer Key** reaching the host is
   leaked by construction — and no prompt can unsee it. Grading material is
   redeemed directly by the **Judge Subagent** against a Topic Visit id, and
   never passes through the host.

## Judge Subagent

In **MCP Mode**, the **Judge** runs as a subagent dispatched by the host — not
as the host itself.

This satisfies the blindness requirement, because blindness was never about
which machine grades. It is context isolation. A subagent starts fresh, receives
only the question, the answer, and the grounding, applies the same rubric, and
ends. It never held the conversation, so it cannot be charmed by it.

The Judge Subagent redeems grading material from the server itself against a
Topic Visit id. The host orchestrates and never sees an **Answer Key**.

## Grader Provenance

Recorded on every **Evidence** row: which grader produced the score — our server
Judge, or a Judge Subagent — along with the raw exchange behind it.

Provenance carries the grader's identity and its provider — our server Judge, a
**Judge Subagent**, DeepSeek, Gemini, Claude — and it is shown to the
**Candidate**. Who marked your answer is not hidden.

Weights are set by **Grading Mode** alone. No provider normaliser exists yet,
and none will be invented: a fitted constant with no data behind it would make
`α + β` uninterpretable in exactly the way the Grading Mode weights are
deliberately not. Normalisers get derived from production data or not at all.

This is affordable because the raw exchange is stored with every row. Any
Evidence can be re-judged later by any grader, so a normaliser can be measured
retroactively rather than guessed in advance, and mis-weighted history can be
rebuilt rather than written off.

## Credit

A unit of provider cost, not a unit of value. One Credit is one US cent of what
OpenRouter charges us: a $9.70 call spends 970 Credits.

Credits therefore float with the provider. The same **Topic Visit** costs
different Credits on DeepSeek, Gemini and Claude, and the **Candidate** sees
that — choosing a cheaper provider visibly stretches a balance.

Consequences that follow from the definition:

- The cost of a Session is not knowable before it runs. Topic dossiers vary
  4.3× across Modules, and the Candidate chooses the duration.
- Metering must be per call and attributable to a **Topic Visit**, since that
  is the unit Evidence, idempotency and refunds all key on.
- Credits meter our key only. Under **BYOK** the Candidate pays their provider
  directly and spends no Credits.

## Session Resumption

An interrupted **Session** ends with an error and can be picked up from where it
stopped, rather than being lost.

The mechanism already exists: a Session is a checkpointed thread, so resuming is
what the checkpointer is for. The **Answer Turn** is a park, and resumption is
another caller of resume.

An interrupted **Topic Visit** stays open until it is graded — never partially
recorded. Where the answer was submitted but grading did not complete, the
exchange is already stored, so resumption grades it and closes the Visit. The
idempotency key makes a repeated grade a no-op rather than a double write.

No **Evidence** is ever written for a Visit that was not graded.

## Credit Funding

**Credits** are pass-through. A **Candidate** buying credits funds the
OpenRouter pool those credits will be spent from, so a candidate balance and the
pool are one thing, and running out is one user-facing event.

`pool ≥ sum(candidate balances)` is maintained by **pre-funding**, not by
reconciliation. The OpenRouter pool is topped up from our own bank account
ahead of receipts, so settlement lag, a failed payment, or a refund can never
starve the pool — credits are granted only once payment clears, and pool money
already placed is spent by someone eventually.

This removes the failure rather than detecting it: a Candidate with a positive
balance is never blocked by an empty pool.

Its cost is working capital. Pool balance is a one-way float — recoverable as
service, not as cash — so how large that float runs is a live decision even
though the failure mode is gone. Promotional credits spend from it too, which
makes them a margin question rather than an availability one.

**BYOK failure is a different event.** A revoked, rate-limited or unfunded
Candidate key is their problem at their provider. It must name the provider and
the reason, and must never mention Credits — they are not spending any.

## Provider

The model vendor a **Session** runs on — DeepSeek, Gemini or Claude, reached
through OpenRouter.

The **Candidate** chooses one per Session. Because **Credits** are exact
provider cost, this is a price choice and is theirs to make and to see, in
keeping with **Grader Provenance** already being visible.

**A Provider is fixed for the duration of a Topic Visit.** It may change between
Visits — an outage failover, or the Candidate switching — and is recorded per
Visit. It may never change inside one: that would split a single score across
two graders and corrupt the provenance record the future normaliser depends on.

A provider failure mid-Visit is therefore handled exactly like a credit failure:
the Session parks, errors, and resumes. The retry runs on whichever Provider is
live when the next Visit opens.

---

# Backbone and Adapters

The **Interviewer** is subject-agnostic. Scaler Cortex is one **Corpus Source**,
not the system. The same backbone must interview on any subject, so the terms
above divide into two kinds and must not be mixed.

## Backbone vocabulary

True of every product built on this: **Corpus**, **Module**, **Topic**,
**Interviewer**, **Judge**, **Judge Subagent**, **Candidate**, **Session**,
**Topic Visit**, **Answer Turn**, **Grading Mode**, **Ground Truth**,
**Evidence**, **Topic Confidence**, **Coverage**, **Mastery**, **Evidence
Floor**, **Grader Provenance**, **Session Resumption**, **Credit**, **Provider**,
**Managed Mode**, **MCP Mode**.

## Adapter vocabulary

True only of the Cortex adapter: **Cortex**, **Track**, **Class**,
**Assignment**, **Answer Key**, **Lecture Recording**, **Contest**,
**Cortex Progress**.

These name artefacts of one source. A different Corpus Source will have its own,
and will map them onto backbone terms — an **Answer Key** is one way a source
supplies **Ground Truth**, not the only way.

## Corpus Source

Anything that can produce a **Corpus**: a scraped course, a textbook, an
internal wiki, a set of specifications, authored material.

A Source is reached through an **Adapter**, which is the only part that knows
the source's shape. `scripts/scrape.mjs` is the Cortex Adapter.

## Adapter

The component that turns a **Corpus Source** into a Corpus satisfying the
backbone's contract. All source-specific knowledge lives here and nowhere else.

An Adapter is responsible for the mapping the backbone refuses to guess: what
counts as a **Module**, what counts as a **Topic**, which text is **Ground
Truth**, and how the source's own units collapse into that shape.

## BYOK

A **Candidate** paying their own inference costs, using an OpenRouter key they
supply. Raw vendor keys are never accepted — only OpenRouter keys, which carry
their own spend cap and can be revoked without touching the Candidate's accounts
at Anthropic, Google or DeepSeek.

BYOK and the **Credit** path differ in exactly one respect: which key pays, and
whether Credits decrement. Routing, **Provider** selection and per-**Topic
Visit** metering are identical.

BYOK applies to **Managed Mode** only. In **MCP Mode** the host's own Claude
subscription pays for both the interviewing and the **Judge Subagent**, so there
is no key to hold and nothing to meter.
