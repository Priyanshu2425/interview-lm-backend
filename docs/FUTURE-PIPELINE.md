# Future Pipeline

Work deliberately deferred, with what unblocks it and what has to stay true now
to keep it possible.

Not a backlog of ideas. Everything here was a real fork in a design conversation
where the answer was "later" — recorded so that "later" stays available.

The column that matters is **Keep possible**: cheap to honour today, impossible
to retrofit.

---

## Grading and Evidence

### Provider normaliser
Weights are set by **Grading Mode** alone. Whether a DeepSeek-graded row should
count differently from an Opus-graded one is unanswered, and will be answered
from production data rather than guessed.

- **Unblocks it:** enough graded rows to compare, across providers.
- **Method:** re-judge a sample of stored exchanges with a reference grader and
  read the disagreement distribution. One batch job, no runtime cost.
- **Keep possible:** every Evidence row stores the raw exchange — question,
  answer, grounding reference, Grading Mode, grader, provider, **rubric
  version**. Without rubric version, grader drift is indistinguishable from
  prompt drift and the whole exercise is unreadable.

### Adversarial second-opinion Judge
A second grader that argues the opposite, to catch a generous first pass.
Deferred in ADR-0002: it doubles grading cost against a problem not yet
measurable.

- **Unblocks it:** Session replay showing judge drift.
- **Keep possible:** deterministic replay, per ADR-0001.

### Candidate disputes
"This grade seems wrong" as a signal. Not calibration input — it is biased
toward people marked down — but a real read on perceived fairness.

- **Keep possible:** **Grader Provenance** is already shown to the Candidate, so
  a dispute can name what it disputes.

---

## Surfaces

### Voice
Chosen as a later surface in Q5. Realistic pressure is arguably the product.

- **Hard part:** the **Answer Turn**. Pauses are not endings, and barge-in moves
  the boundary backwards.
- **Keep possible:** the graph waits on an Answer Turn event and never reads a
  particular kind of input. A surface that cannot say when a turn ended cannot
  be plugged in.

### Code editor and sandbox
Executable DSA answers with real test runs.

- **Why it matters more than it looks:** it moves DSA from Grading Mode 3
  (weight 0.5, the weakest evidence in the system) to something deterministic.
  The single largest available upgrade to evidence quality.
- **Keep possible:** same Answer Turn boundary; Grading Mode is a per-Visit
  field, so a new mode is additive.

---

## Corpus

### Lecture Recording transcripts
31 DSA Classes carry video and no text. Blocked: Scaler Academy is a separate
auth realm and its bot protection blocks automated download.

- **Legitimate routes:** ask Scaler for transcripts or captions; or the
  Candidate obtains audio by their own means.
- **Ready and waiting:** `data/pending-transcripts.json` holds all 31 stubs;
  `scripts/ingest-transcripts.mjs` writes any populated transcript into the
  Corpus.
- **Effect if landed:** DSA moves from THIN to usable, and Grading Mode 2
  becomes available to it.

### Contest problems
Out of scope by decision. `contestSyllabus` is kept as curriculum metadata; no
problems are taken.

### Cross-Topic similarity — **landed, 2026-08-22**
ADR-0005 rejected a vector store because there is no query to embed. This entry
said "do not pre-build it", and that held until there was a consumer.

- **What landed:** every shipped Topic carries up to five precomputed
  neighbours (ADR-0018, ISSUE-0029). Centroid against centroid, computed
  offline, so nothing is embedded at question time and the entry's own
  condition — added alongside dossier lookup without disturbing it — is met.
- **What it cost:** a re-scrape obligation, which is why ISSUE-0030 exists. An
  index that no longer matches the Corpus serves nothing rather than something
  wrong.
- **Still deferred:** where a Candidate meets a related Topic (ISSUE-0031). A
  list beside a score reads as "study these next", which is Topic
  recommendation — see *Adaptive Session termination* below, still uncalibrated.

---

## Tracking

### Self-rated confidence
The gap between what a **Candidate** feels confident about and what they are
good at is where interviews actually get failed. A second axis alongside
**Topic Confidence**, not a replacement.

- **Keep possible:** cheap to collect at any point; nothing blocks it.

### Mastery trend across Sessions
Needs Session history that does not exist yet. Additive later at no cost.

### Adaptive Session termination
Stop when the next Topic Visit's expected information gain is low. Thompson
sampling already supplies the machinery; the threshold needs data to calibrate.

- **Note:** Sessions currently end on a Candidate-chosen duration, and are only
  comparable within the same duration.

---

## Not yet designed

Named so they are not mistaken for solved:

- **BYOK key handling** — storage, scoping, revocation
- **Performance History** beyond Topic Confidence — what else a Session records
- **Adapters beyond InterviewLM** — the contract is defined (ADR-0007); no second
  Adapter has been written, so the contract is untested against a source that
  is not a structured course API
- **Margin model** — Credits are exact provider cost, so revenue comes from
  somewhere else and that somewhere is undecided
- **Float sizing** — how far the pre-funded OpenRouter pool runs ahead of
  receipts is working capital, not a technical setting
