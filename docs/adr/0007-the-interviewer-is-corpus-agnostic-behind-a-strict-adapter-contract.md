# The Interviewer is corpus-agnostic, behind a strict Adapter contract

The backbone interviews on any subject. A **Corpus Source** — a scraped course,
a textbook, a wiki, authored material — is reached through an **Adapter** that
holds all source-specific knowledge. `scripts/scrape.mjs` is the Cortex Adapter,
not the system.

The contract is strict and validated at ingest. An Adapter must emit:

- a **Module** → **Topic** → leaf hierarchy
- stable ids it can reproduce across re-ingests
- explicit ordering
- **Topic** dossiers under a token budget

**Ground Truth is optional.** **Grading Mode** already expresses its absence, so
that part generalises with no extra machinery.

## Why strict rather than accommodating

**Topic identity is the join key for everything permanent.** `topic_id` keys
**Topic Confidence**, and Beta values accumulate against it for months. Any
scheme that lets Topic boundaries move — a backbone that infers load units at
runtime, auto-splits oversized Topics, or normalises sources with an LLM pass —
silently redefines what a **Candidate**'s **Mastery** refers to. There is no
error, only numbers that stop meaning what they meant.

So the mess goes in Adapters, where it is deliberate, inspectable, and owned by
someone who understands the source.

## The two contract terms that came from measurement

**Token budget per Topic.** Cortex dossiers measured p50 4.9k, max 9.3k tokens,
which is what let ADR-0005 reject chunking and load whole dossiers. A source
with 100k-token Topics breaks that guarantee, and only the Adapter knows what a
meaningful division of its material looks like — so the Adapter divides, never
the backbone.

**Order is required.** Curriculum order is the progression prior, and the
opening question of a **Session** is exempted from Thompson sampling so Sessions
start easy. A source with no natural order — a wiki, a document set — must have
its Adapter supply one, or that opener has nothing to stand on.

## Consequence

The product ships as machinery, not content: the graph, the rubrics, the
tracker, the **Evidence** record. Each deployment brings its own Corpus through
its own Adapter. That is what makes several products viable on one backbone, and
it also means Scaler's material never needs to live on our servers.
