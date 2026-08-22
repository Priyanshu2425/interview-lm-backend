# Questhiring — Deutsche Telekom Digital Labs, AI Backend Engineer

Answers drawn from the Scaler Cortex Interviewer (LangGraph + FastAPI + Postgres).

---

## 1. Describe a production-grade agentic AI system you have built.

I built an AI interviewer that examines a candidate on a scraped course corpus
(2 tracks, 15 modules, 71 topics) and builds a permanent, honest record of what
they can actually explain.

The core decision was that it is a **LangGraph state machine, not a ReAct
agent**. A session runs `select_topic → load_dossier → generate_question →
interrupt → grade → update_confidence → decide_next`. Model calls happen inside
nodes; the model never chooses which node runs next. Agency is confined to one
region — probing a vague answer, offering a hint, deciding an exchange is
finished. I did it this way because a graded answer updates a Beta posterior
exactly once, and a graph edge cannot not run, whereas a tool call can be
skipped, repeated, or fired with the wrong weight — and a silently doubled `β`
is invisible until mastery is wrong weeks later.

The production surface is the part I care most about. `interrupt()` is the
answer turn, so the graph parks and any surface resumes it. Resumption runs off
a Postgres checkpointer, with our own `core` schema alongside it on an opposite
lifecycle. Nothing reaches for the clock or randomness outside the ports module,
so a session replays exactly. Every model call — interviewer, question writer,
judge — passes through one metered client that attributes cost to a topic visit;
a static architecture test fails the build if any module outside `metering/`
imports an HTTP client. Keys are envelope-encrypted, BYOK is accepted at the
OpenRouter layer only, and provider failures are classified so a BYOK candidate
never sees a credits message.

Guarantees live in the database rather than in conventions: one evidence row per
visit is a unique constraint, "no session advances while a visit is unresolved"
is a partial unique index, evidence is append-only, and a posterior cannot fall
below its prior. 462 tests, and a story-coverage map tying all 191 user stories
to a module and a test, checked on every run.

---

## 2. Explain the end-to-end RAG pipeline you have designed or worked on.

End to end it runs: authenticated ingestion → classification → normalisation →
a validated contract → dossier assembly → grounded prompting → provenance-linked
grading.

Ingestion is a Playwright-authenticated crawl of the course API. Every leaf
carries exactly one content type, and only text leaves are retrievable — video
and contest leaves are recorded as stubs rather than silently dropped, because
"this topic has no material" is a fact the interviewer needs. I classify each
leaf on ingest into assignment, answer key, key-concepts, interview-insight or
revision, then write markdown with YAML frontmatter alongside a corpus manifest.
Assignment + answer-key pairs are the highest-value structure in the source —
26 of them — because they are a question with a rubric already attached.

Everything downstream sits behind a strict adapter contract with a conformance
validator, so a second corpus can be plugged in without touching the interview
loop. The dossier loader is the only module that knows how content is stored: it
returns one topic's content, its ground-truth pairs, its syllabus and its
**grading-mode ceiling**. Grounding is then assembled per call, and this is
where retrieval quality actually shows up: answer-key text is suppressed from
the interviewing context whenever the question is not being written from that
assignment, and the judge is handed either the authoritative answer or a
course-material excerpt — never the conversation. The mode is a fact about which
grounding was used, and it sets the evidence weight (1.0 / 0.7 / 0.5).

I deliberately shipped **no embedding model, no vector store and no retriever**,
and wrote an ADR so a future reader knows it is absent by choice. Topic
selection happens by Thompson sampling before any content is needed, so there is
no query to embed — the interviewer says "give me this topic id", which is a
lookup. And I measured the corpus: dossiers are ~5k tokens at the median, 9.3k
at the max, so the whole topic fits. Chunking would have hurt, because follow-up
questions need the entire topic and top-k retrieval is precisely how a concept
gets probed while its explanation sits in an unretrieved chunk. The revisit
trigger is written down too: the moment we want cross-topic similarity — "what
else relates to this?" — that genuinely is a vector problem, and it can be added
beside dossier lookup rather than replacing it.

---

## 3. How have you implemented multi-agent orchestration in your projects?

Four model roles with separate prompts and separate contexts: a **question
writer**, an **interviewer** that decides probe / hint / close, a **judge**, and
a **re-judge** reference grader that runs offline over stored exchanges.

The important one is the judge, and the rule is that **the grader never held the
conversation**. It receives the question, the candidate's words, and the
grounding — no history, no hints, no signal about how the candidate came across.
The model that has just spent twenty minutes building rapport is the worst
available grader of that conversation; sycophancy there is not a prompt defect,
it is conversational context working as intended. Separating the roles is what
removes it.

Orchestration between them is deterministic — graph edges, not model-chosen
handoffs — for the reasons in answer 1. The agentic region is bounded rather
than open-ended: at most six turns per visit, and two cases I refuse to leave to
the model — a candidate who says "I don't know" is taken at their word, and a
candidate who asks for help gets a hint whatever the model chose.

The genuinely multi-agent path is MCP mode, where the whole tool surface is
exposed to a host Claude that drives the session itself. There, grading is
dispatched to a **judge subagent** that calls the server directly and redeems
grading material against a topic-visit ticket, rather than the host fetching an
answer key and passing it down. That is a structural fix, not a prompt: material
handed through the host stays in the interviewing context for the rest of the
session, possibly the key to a topic not yet asked, and no prompt removes text
that is already present. Both cross-mode invariants then hold without asking the
host to cooperate — the host cannot see an answer key, and the score write is
idempotent on the visit id, so it cannot write evidence twice.

---

## 4. How do you measure and improve the quality of AI outputs?

Three layers: what gets stored, what can be replayed, and what is refused.

**Stored.** Each candidate-topic pair is a Beta distribution, not a score.
Mastery is its mean, coverage is its evidence count, confidence is its spread.
That one structure is what lets the system tell an unasked topic from a failed
one — a product storing a single number cannot, which is exactly the question
"what do I ask next?" needs answered. Reporting bands are read off an 80%
credible interval width rather than hand-picked thresholds, and below the
evidence floor the API has no call that returns a bare mastery percentage. Every
evidence row records the question, the answer, the grounding reference, the
grading mode, the rubric version, and the grader's identity and provider.

**Replayed.** Because evidence is append-only and self-describing, I can re-grade
any historical exchange with a different grader or a changed rubric and report
the mean delta, bucketed by provider. That is how I intend to find grader drift
and decide whether a cross-provider normaliser is justified — I refused to invent
one in advance, because it would have been a constant chosen from intuition. The
re-judge run writes nothing: it is a measurement of the grader, not a correction
of the record. The same property makes prompt changes evaluable at all —
determinism is enforced (no clock or randomness outside the ports module), so a
session replays exactly and two rubrics can be compared on identical input.

**Refused.** A judge score outside 0..1 raises instead of being clamped, because
clamping writes a grader's misunderstanding into a permanent record. Coverage
and mastery are never fused into one figure — the rule is enforced as an absent
API, not a code-review convention. No difficulty label is ever produced, because
the corpus records none and deriving one would be a number I could not justify.

The honest gap, and my next step: I have the mechanism but not yet a
human-labelled gold set. I am building one from the 26 assignment/answer-key
pairs so I can quote judge-versus-human agreement as a number rather than
describing the harness that would produce it.
