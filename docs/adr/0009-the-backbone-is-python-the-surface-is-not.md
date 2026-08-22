# The backbone is Python; the Candidate surface is not

The **Interviewer** graph, the **Judge**, the stores, the **Adapter** contract
and the MCP server are Python. The Candidate-facing web surface is a separate
deployable in whatever language suits it, reached over an HTTP contract.

## Why

**Resumption is load-bearing, and it is the checkpointer's job.** ADR-0003 puts
graph state in a LangGraph checkpointer and PRD-0003 builds **Session
Resumption** entirely on top of it: the **Answer Turn** is a park, resuming is
another caller of resume, and an interrupted **Topic Visit** stays open until it
is graded. That machinery — `interrupt`, resume-with-value, the Postgres
checkpointer, deterministic replay of a recorded thread — is most mature on
LangGraph's Python line. Choosing a runtime means choosing which implementation
of the one mechanism the design leans hardest on.

**The invariants are server-side or they do not exist.** ADR-0006 requires the
MCP server to enforce single-write-per-Visit against a host we do not control,
and to hand grading material only to a **Judge Subagent**. That server shares
the stores and the **Topic Visit Lifecycle** with the graph. Putting it in a
different language would mean two implementations of the same invariant, which
is how invariants diverge.

## Why not TypeScript everywhere

It is the better answer to a different question. One language across graph,
server, surface and adapter is a real and ongoing benefit, and if the graph were
incidental it would win. But what it trades away is maturity in exactly the
mechanism — park, resume, replay — that every guarantee in PRD-0003 rests on.
The saving is felt every week; the cost is felt the first time a Session cannot
be resumed and the record is gone.

## Why not a split with the MCP server in TypeScript

The web surface may be any language because it holds no invariant: it supplies
an Answer Turn and renders what it is given. The MCP server is the opposite. It
is the thing standing between a ReAct agent and a permanent write.

## Consequence

`scripts/scrape.mjs` stays Node and is not ported. ADR-0007 already says the
Cortex Adapter is one **Corpus Source**'s adapter and not the system; it is a
build-time producer whose output — a Corpus satisfying the contract — is the
only thing the backbone sees. A future adapter may be written in anything.

The contract between backbone and surface becomes a real interface with a real
version, rather than a function call. That is a cost, and it is also what makes
the voice and code-editor surfaces additive later (PRD-0003).
