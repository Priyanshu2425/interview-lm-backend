# In MCP Mode the Judge Subagent fetches its own grading material

**MCP Mode** exposes the full tool surface to the host Claude, which drives the
**Session** freely. Grading is dispatched by the host to a **Judge Subagent**,
which calls the server directly to redeem grading material against a Topic Visit
id. The host orchestrates and never holds an **Answer Key**.

## Why not simply hand the material down

The obvious route — host fetches the dossier, passes it to its subagent — puts
the Answer Key into the *interviewing* context, where it stays for the rest of
the Session. Possibly the key to a Topic not yet asked. No prompt removes text
that is already present, so this must be prevented structurally.

A sealed or opaque payload relayed by the host is cosmetic: it is still text in
the host's context.

## The shape

`submit_answer` opens a Topic Visit and returns a `topic_visit_id`. The Judge
Subagent redeems that id for exactly the grounding of that one Visit. The score
write is idempotent on the same id.

Both cross-mode invariants therefore hold without asking the host to cooperate:
the host cannot see an Answer Key, and it cannot write **Evidence** twice.

## Dependency

Subagents must inherit MCP server access in the host environment. Where they do
not, this collapses to host-relayed material and the leakage becomes a
deliberate cost rather than a solved problem.

## Consequence

**Grader Provenance** is recorded per Evidence row. Weights stay set by
**Grading Mode** — a Judge Subagent following the same rubric is not weaker
evidence — but provenance makes drift findable and makes affected rows
re-judgeable in batch.
