# The Interviewer is a state machine with agentic regions, not an agent with tools

A **Session** runs as an explicit LangGraph state machine —
`select_topic → load_dossier → generate_question → interrupt → grade →
update_confidence → decide_next` — with LLM calls made *inside* nodes rather
than deciding which node runs next. Agency is confined to the region around the
**Answer Turn**: probing a vague answer, offering a hint, deciding a follow-up
is warranted before scoring.

## Why not a ReAct agent

Two reasons, both about guarantees rather than taste.

**Evidence integrity.** A graded answer updates a Beta distribution with a
weight set by its **Grading Mode**. That update must fire exactly once per
Answer Turn. As a tool call, a model can skip it, repeat it, or attach the wrong
mode — and a silently doubled `β` is invisible until **Mastery** is wrong weeks
later. As a graph edge, it cannot not run.

**Grading is unmeasurable without replay.** Three Grading Modes at three
different weights means we have no way to know whether grading is any good
except by replaying Sessions against changed prompts. A deterministic loop
replays exactly; an agent-driven one does not.

## Consequences

- The loop is rigid. Off-script Candidate behaviour needs explicit handling
  rather than emerging from the model.
- `interrupt()` is the **Answer Turn**. The graph parks and a surface resumes
  it, so adding voice or a code editor changes who calls `resume`, not the
  graph. This is the whole reason the surface question was settled first.
- Build the deterministic skeleton before growing the agentic region. Starting
  hybrid hides the seam.
