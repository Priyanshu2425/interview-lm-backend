# PRD-0001 — Corpus Adapter Contract and Dossier Loader

Status: ready-for-agent
Depends on: ADR-0005, ADR-0007

## Problem Statement

The Corpus exists, and nothing can read it safely.

A InterviewLM extract sits on disk — a Track → Module → Topic → Class hierarchy with
markdown for every Class that carries text. But every consumer that wants to use
it has to re-derive the same facts by hand: which files belong to a Topic, how
large that Topic is once assembled, whether a Class is Ground Truth or an
ordinary explanation, and whether an Answer Key is safe to hand to the thing
that is about to ask the question.

That is the immediate problem. The structural one is worse. The backbone is
meant to interview on any subject, and today the only thing standing between it
and a second Corpus Source is an unwritten agreement about shape. A Source that
supplies no ordering, or Topics ten times too large, or ids that change between
ingests, would be accepted silently — and the failure would not appear as an
error. It would appear months later as Topic Confidence values that no longer
refer to what they used to refer to.

The Interviewer must not be the place where that is discovered.

## Solution

Two things, sharply separated.

**A contract, validated at ingest.** An Adapter emits a Corpus; the backbone
refuses to load one that does not satisfy the contract. Validation happens once,
at ingest, and produces a report a human reads — not a runtime exception three
weeks into a Session. A Corpus that passes is a Corpus every other module in the
system may assume is well-formed.

**A dossier loader.** The Interviewer asks for a Topic by id and receives a
Topic dossier: the whole Topic, assembled, ordered, with its Ground Truth
separated from its teaching material and never merged into it. No query, no
embedding, no retriever — a lookup by id, as ADR-0005 requires.

The InterviewLM Adapter already exists as a scraper. This PRD does not rewrite it; it
defines what it must emit, adds the validation that proves it did, and builds the
loader every consumer reads through.

## User Stories

1. As the Interviewer, I want to request a Topic dossier by `topic_id`, so that I never have to know which Corpus Source produced it.
2. As the Interviewer, I want a dossier to arrive whole rather than chunked, so that a follow-up question can probe a concept whose explanation would have sat in an unretrieved chunk.
3. As the Interviewer, I want the dossier to state its own token count, so that I can trust the load figure rather than measure it myself.
4. As the Interviewer, I want teaching material and Ground Truth returned as separate fields, so that I can be given one without the other.
5. As the Interviewer, I want a dossier to tell me which Grading Mode it can support, so that I do not have to infer trust from the presence or absence of a file.
6. As the Interviewer, I want Classes within a Topic to arrive in curriculum order, so that an opening question can follow the order the material was taught in.
7. As the Interviewer, I want Modules and Topics to expose their order, so that a Session's opening question can be drawn from early material rather than sampled.
8. As the Judge, I want to receive only the grounding excerpt for the question I am scoring, so that I cannot be influenced by material I was not asked about.
9. As the Judge, I want an Assignment's Answer Key retrievable by the Assignment's id, so that Ground-Truth-graded scoring has exactly one authoritative source.
10. As a system operator, I want ingest to fail loudly when a Corpus violates the contract, so that a malformed Source never reaches a Candidate.
11. As a system operator, I want the validation report to name every violation rather than the first one, so that fixing an Adapter is one pass rather than ten.
12. As a system operator, I want a report of Topic dossier sizes at ingest, so that I can see before shipping whether a Source respects the token budget.
13. As a system operator, I want ingest to record the Corpus's provenance — Source, extraction time, Adapter identity — so that I can tell which extract a Session ran against.
14. As a system operator, I want re-ingesting an unchanged Source to produce identical ids, so that accumulated Topic Confidence still refers to the same Topics.
15. As a system operator, I want a re-ingest that changes Topic boundaries to be reported as such, so that a silent redefinition of Mastery is impossible.
16. As a system operator, I want Classes with no retrievable content to be recorded as stubs rather than omitted, so that Coverage is measured against the real curriculum and not against what happened to scrape.
17. As a system operator, I want a Topic whose Classes are all stubs to be flagged, so that I know it can only ever be examined under Model judgment.
18. As an Adapter author, I want the contract stated as a schema I can validate against locally, so that I can iterate without running the whole system.
19. As an Adapter author, I want to declare that my Source carries no Ground Truth, so that absence is a supported case rather than a validation failure.
20. As an Adapter author, I want to supply my own ordering when my Source has no natural one, so that a wiki or document set can still back a Session.
21. As an Adapter author, I want to be the one that splits oversized material into Topics, so that the backbone never invents load units I did not intend.
22. As an Adapter author, I want a fixture Corpus and a conformance check I can run, so that "does my Adapter work" has an answer that is not "try it in production".
23. As the Session, I want to ask for every Topic within a chosen set of Modules, so that scope can be selected before the first question is asked.
24. As the Session, I want Topic listing to be cheap and content loading to be separate, so that scoping a Session does not load the material of 57 Topics.
25. As a Candidate, I want to choose a Session's scope by Module, so that I can prepare for the part of the course I am actually being interviewed on.
26. As a Candidate, I want a Module with no Answer Keys to still be selectable, so that the absence of Ground Truth reduces the weight of my evidence rather than removing the Module.
27. As the tracker, I want the canonical list of Topic ids for a Corpus, so that Topic Confidence rows can be created against a known universe rather than discovered.
28. As a future maintainer, I want all InterviewLM-specific vocabulary confined to the Adapter, so that adding a second Source does not mean unpicking Track and Class from the backbone.
29. As a future maintainer, I want a second Adapter to be implementable against the contract alone, so that the contract's untestedness is a fact I can fix rather than a guess.

## Implementation Decisions

**Modules built**

- *Corpus Contract* — the schema and the vocabulary of what an Adapter must emit. Declarative, no behaviour. Backbone terms only: Module, Topic, leaf content unit, Ground Truth, order, ids.
- *Corpus Validator* — takes a candidate Corpus, returns a report. Pure: no I/O beyond being handed content, no network, no model calls. Collects all violations rather than throwing on the first.
- *Dossier Loader* — takes a `topic_id`, returns a Topic dossier. The only module in the system that knows how Corpus content is stored on disk. Deep by construction: one method of consequence, an interface that should not change when the storage does.
- *InterviewLM Adapter* — the existing scraper, brought under the contract. It gains an emit step that produces contract-shaped output and a conformance run; its scraping behaviour is unchanged.

**The contract's required terms**

- A Module → Topic → leaf hierarchy, exactly three levels. Deeper source structures are collapsed by the Adapter.
- Stable ids at Module and Topic level, reproducible across re-ingests of unchanged material. `topic_id` is the permanent join key and is treated as such everywhere.
- Explicit integer ordering at Module, Topic and leaf level. Order is required, not optional — the opening question of a Session depends on it (ADR-0007).
- A per-Topic token budget. Dossiers must fit whole in context; a Source that cannot must divide in its Adapter.
- Ground Truth is optional and explicitly declared per leaf. Its absence is expressed as Grading Mode, not as a validation failure.
- Provenance: Source identity, Adapter identity, extraction timestamp.

**Budget enforcement**

The measured InterviewLM figures (p50 ~4.9k tokens, max ~9.3k) are the reason ADR-0005
could reject chunking, so the budget is a hard ceiling with a warning band below
it. A Topic over the ceiling fails validation. A Topic in the warning band passes
and is reported. The backbone never splits, never summarises, never
auto-normalises — the Adapter divides or the Corpus is rejected.

**Dossier shape**

A dossier separates what may be shown from what may not:

- *teaching content* — the ordered text of the Topic's content-bearing leaves, safe to place in the interviewing context.
- *ground truth* — Answer-Key-equivalent material, keyed by the leaf it answers, never merged into teaching content and never returned by the default load path.
- *metadata* — Topic id, title, Module, order, token count, and the highest Grading Mode this Topic can support.

Two load paths exist and are distinct calls: one for interviewing, one for
grading. The interviewing path cannot return Ground Truth. This is the file-level
half of the guarantee ADR-0006 enforces at the protocol level; both halves are
required, because a single call with a boolean flag is one wrong argument away
from leaking.

**Grading Mode derivation**

The loader derives the *ceiling* — the strongest mode a Topic can support: Ground
Truth present → 1, teaching text present → 2, neither → 3. It does not decide the
mode used for a given question. That is a property of how the question was
actually written and is recorded per Topic Visit (PRD-0002).

**Stub handling**

Leaves with no retrievable content are carried with a status naming why (video
behind a separate auth realm, external contest, empty). They count toward
curriculum totals and Coverage denominators, and they contribute no text. A Topic
of only stubs is valid and loads with a mode-3 ceiling — DSA depends on this.

**Re-ingest**

Re-ingest is a diff, not a replace. The report names Topics added, removed, and
changed, and flags any change to the Topic set as affecting accumulated Topic
Confidence. Applying a re-ingest that removes or re-keys Topics requires an
explicit operator decision; it is never a side effect of running the scraper.

**Ownership boundary**

Everything that knows the word Track, Class, Assignment, Answer Key or Contest
lives in the InterviewLM Adapter. The backbone knows Module, Topic, leaf, Ground
Truth. Where the Adapter maps one to the other, the mapping is recorded in the
Adapter and nowhere else.

## Testing Decisions

A good test here states a fact about the Corpus contract that a future change
could break, in terms an Adapter author would recognise. It asserts on returned
dossiers and validation reports — never on how a file was found, how many reads
happened, or what the loader cached.

**Corpus Validator — tested thoroughly.** It is the highest-value test target in
this PRD: pure, deterministic, fixture-driven, and the module whose failure is
otherwise silent. Fixtures are small hand-written Corpora, each violating exactly
one term:

- valid minimal Corpus passes with no violations
- missing order at Module, Topic and leaf level, each reported
- duplicate ids within a level
- ids that change between two ingests of identical material
- a Topic over the token ceiling fails; one in the warning band passes and is reported
- a Corpus with no Ground Truth anywhere passes, and every Topic reports a mode-2 or mode-3 ceiling
- a Topic of only stubs passes with a mode-3 ceiling
- a Corpus with three violations reports three, not one
- hierarchy that is two levels or four levels deep is rejected

**Dossier Loader — tested on behaviour, against a fixture Corpus.**

- loading a known `topic_id` returns every content-bearing leaf of that Topic, in order
- the interviewing load path never returns Ground Truth, for a Topic that has Ground Truth
- the grading load path returns the Ground Truth for the requested leaf and no other leaf's
- an unknown `topic_id` is an explicit not-found, not an empty dossier
- reported token count matches the returned content
- the Grading Mode ceiling is derived correctly for a Ground-Truth Topic, a text-only Topic, and a stub-only Topic
- listing Topics for a set of Modules returns the right ids without loading content

**InterviewLM Adapter — one conformance test.** Its real output, or a trimmed slice of
it, passes the validator. This is the test that would have caught a scraper change
that broke the contract. Its scraping internals are not unit-tested; it is I/O
against a live system and the conformance check is the meaningful assertion.

**Prior art.** None — this is the first tested module in the repo, so this PRD
establishes the pattern: fixtures as data files, assertions on returned values,
no mocking of the module under test.

## Out of Scope

- Embeddings, vector storage, retrieval, similarity search. Rejected in ADR-0005 and not reopened here.
- Chunking or summarising Topics. The Adapter divides; the backbone does not.
- A second Adapter. The contract is written so one can be built; building one is separate work.
- Lecture Recording transcripts. The stub list and ingest path already exist; obtaining the audio is blocked elsewhere.
- Contest problems. Out of scope by decision; the syllabus is kept as curriculum metadata.
- Difficulty. The Corpus records none and derives none. This is not a gap to be filled later.
- Serving the Corpus over a network. Local read is the whole story for now.

## Further Notes

The measured InterviewLM shape, as scraped: AIML — 8 Modules, 57 Topics, 356 Classes,
26 Assignment/Answer Key pairs, one empty stub. DSA — 7 Modules, 14 Topics, 74
Classes, 31 video stubs, 11 contest stubs, no Ground Truth. 71 Topics total,
which is the size of the Topic Confidence table per Candidate.

The asymmetry between the Tracks is the best available test of the contract's
Ground-Truth-optionality: AIML exercises mode 1, DSA exercises mode 3, and the
GenAI Modules exercise mode 2. A contract that handles all three across one
Corpus is more likely to survive a second Source.

The reason Ground Truth is a separate field rather than a flagged leaf is
ADR-0006. A leaked Answer Key cannot be unseen, so the safe path must be the
default path and the unsafe one must be a different call with a different name.
