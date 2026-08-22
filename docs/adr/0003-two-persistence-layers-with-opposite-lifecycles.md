# Session checkpoints and Topic Confidence are stored separately

Graph state uses a LangGraph checkpointer, keyed per thread, where one thread is
one **Session**. **Topic Confidence** lives in a table we own —
`(candidate_id, topic_id, alpha, beta, updated_at)` — read and written by graph
nodes but not owned by the graph.

## Why

The two have opposite lifecycles. Checkpoints are disposable: an abandoned
Session's graph state is worthless next month, and it will be wiped every time
the graph's schema changes. Beta values are the opposite — 71 rows per
**Candidate** that must survive every rewrite of the graph, every prompt change,
and plausibly LangGraph itself. **Evidence** was made irreversible by design
(see the Evidence entry in CONTEXT.md); storing it in a structure we expect to
discard contradicts that.

Topic Confidence is also read from outside the graph: showing weak Topics,
seeding a Session's opening difficulty from history, any reporting at all. None
of that should require instantiating a graph to read a framework's KV namespace.

## Considered and rejected

**Checkpointer alone** — the easy mistake, because the checkpointer is present
and does persist things. A thread is a Session, so per-thread state cannot span
Sessions, which is the whole point of Topic Confidence.

**LangGraph `BaseStore` alone** — correct in shape, and rejected only on
coupling: it puts the one long-lived domain record inside a framework
abstraction. `topic_id` is already a stable Cortex cuid carried in
`corpus.json`, so a plain table costs almost nothing and owes nothing.

## Amendment — checkpoints are disposable only after a retention window

Sessions are resumable: an interrupted Session ends with an error and can be
picked up where it stopped. That makes a live checkpoint load-bearing, not
worthless, and it constrains what "wipe on schema change" is allowed to mean.

The lifecycles still differ, which is why the split stands — but the difference
is now *retention window* rather than *disposable versus permanent*. A
checkpoint must survive until its Session is resumed or abandoned; **Topic
Confidence** must survive forever. A schema migration may only discard
checkpoints outside the resumption window.
