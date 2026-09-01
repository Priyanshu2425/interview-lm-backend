# The Interviewer is a state machine with agentic regions, not an agent with tools

A **Session** runs as an explicit LangGraph state machine —
`build_plan → next_planned_item → load_dossiers → generate_question →
interrupt → record_exchange → decide_next` — with LLM calls made *inside* nodes
rather than deciding which node runs next. Agency is confined to the region
around the **Answer Turn**: probing a vague answer, offering a hint, deciding a
follow-up is warranted before closing the question.

> **Amended by ISSUE-0041 and ISSUE-0042.** The node list was
> `select_topic → load_dossier → generate_question → interrupt → grade →
> update_confidence → decide_next`. `build_plan` was added in front of it
> (ISSUE-0041): the Session decides what it will ask before it asks anything,
> and writes the plan down. Then `select_topic` became `next_planned_item`,
> `load_dossier` became `load_dossiers` — a question may span up to three
> Topics — `record_answer` became `record_exchange`, and `grade` and
> `update_confidence` were **deleted from the loop** (ISSUE-0042). ISSUE-0044
> then added `grade_session` on the edge to END, so the list now reads
> `build_plan → next_planned_item → load_dossiers → generate_question →
> interrupt → interviewer_move → record_exchange → decide_next →
> grade_session → END`.
>
> The deletion does not weaken the argument below; it is the argument applied
> once more. In-loop grading existed because selection was adaptive: the
> sampler needed a posterior updated after every Visit before it could pick the
> next Topic. Fixing the plan before the first question removes that
> dependency, and removing it is what lets the Evidence write move to the end
> of the Session (ISSUE-0044), which is where it now is. It is still an edge
> and it still cannot not run; it runs once, over a transcript, instead of once
> per question. Thompson
> sampling did not die either — it moved to plan-construction time.

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
