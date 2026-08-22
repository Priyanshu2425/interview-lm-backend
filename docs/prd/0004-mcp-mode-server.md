# PRD-0004 — MCP Mode Server

Status: ready-for-agent
Depends on: PRD-0001, PRD-0002, PRD-0003; ADR-0002 (amendment), ADR-0006

## Problem Statement

The people most likely to want interview practice are already sitting in a Claude
session. Asking them to leave it, open another product, and sign in somewhere
else to be asked questions is a worse experience than the one they already have
open — and it means our loop only reaches Candidates who came looking for it.

The obvious answer is to expose the system as an MCP server so the host Claude
can run a Session in place. The obvious answer is also where the design gets
dangerous, because in MCP Mode we no longer control the loop.

The host is a ReAct agent we do not control. Prompts steer it; they do not
constrain it. Every guarantee that PRD-0003 gets from a graph edge — Evidence
written exactly once, the right weight applied, no score without a grade — becomes
a request we are making of somebody else's agent. And one of those requests is
not merely unreliable but unrecoverable: the host holds its context in front of
the Candidate, so an Answer Key that reaches the host is leaked by construction.
Possibly the key to a Topic not yet asked. No prompt removes text that is already
present.

Handing the material down to a subagent does not fix it — the material passed
through the interviewing context on the way. Nor does sealing it: an opaque
payload relayed by the host is still text in the host's context.

## Solution

Expose the tool surface, and enforce every invariant in the server rather than
asking for it in a prompt.

Two invariants survive both modes, and both are structural:

**Evidence is written once per Topic Visit** — because the write is idempotent on
a server-issued Topic Visit id, and the Session will not advance while a Visit is
unresolved. Not because the host was asked to behave.

**No Answer Key enters the interviewing context** — because grading material is
never returned to the host at all. Submitting an answer opens a Topic Visit and
returns an id. The host dispatches a Judge Subagent, and that subagent calls the
server directly and redeems the id for exactly the grounding of that one Visit.
The host orchestrates and never holds an Answer Key.

That subagent satisfies the blindness requirement of ADR-0002, because blindness
was never about which machine grades. It is context isolation. A subagent starts
fresh, receives only the question, the answer, and the grounding, applies the same
rubric, and ends. It never held the conversation, so it cannot be charmed by it.

The Evidence a Session produces in MCP Mode is the same Evidence, at the same
weights, in the same tables, as a Managed Mode Session. A Judge Subagent
following the same rubric is not weaker evidence — it is differently attributed,
and Grader Provenance records which.

## User Stories

1. As a Candidate already working in Claude, I want to run a mock interview without leaving my session, so that practice fits into where I already am.
2. As a Candidate in MCP Mode, I want the Session scoped to Modules I choose, so that scope works the same way it does in the managed product.
3. As a Candidate in MCP Mode, I want my Topic Confidence to be the same record as in Managed Mode, so that practice in either place accumulates into one history.
4. As a Candidate in MCP Mode, I want the host never to see an Answer Key before I have answered, so that it cannot leak the answer to a question I have not been asked yet.
5. As a Candidate in MCP Mode, I want to be told my answer was graded by a Judge Subagent, so that provenance is visible rather than implied.
6. As a Candidate in MCP Mode, I want my Session's cost paid by my own Claude subscription, so that there is no second billing relationship to set up.
7. As a Candidate in MCP Mode, I want an interrupted Session to be resumable, so that closing a chat does not lose the record.
8. As a Candidate in MCP Mode, I want to see the same score, rationale and Evidence Floor hedging as in Managed Mode, so that the two modes tell me the same truth.
9. As the host Claude, I want a tool that starts a Session and returns its scope, so that I know what I am allowed to ask about.
10. As the host Claude, I want a tool that asks the server for the next Topic, so that selection stays with the selector rather than with me.
11. As the host Claude, I want a tool that returns the interviewing dossier for a Topic, so that I can write a grounded question.
12. As the host Claude, I want that dossier to contain no Answer Key, so that I cannot leak what I was never given.
13. As the host Claude, I want a tool that submits the Candidate's answer and returns a Topic Visit id, so that the exchange has an identifier everything else keys on.
14. As the host Claude, I want to dispatch a Judge Subagent with only a Topic Visit id, so that I do not have to hold grading material to get an answer graded.
15. As the host Claude, I want the server to tell me when a Visit is unresolved, so that I know the Session will not advance until grading completes.
16. As the host Claude, I want a tool that ends the Session and returns a summary, so that the Candidate gets the same closing reading as in Managed Mode.
17. As the host Claude, I want tool descriptions that state the intended loop, so that steering is available even though it is not a constraint.
18. As a Judge Subagent, I want to redeem a Topic Visit id for exactly the grounding of that one Visit, so that I can grade without the host having handled the material.
19. As a Judge Subagent, I want to receive the question, the answer and the grounding and nothing else, so that I am blind to the conversation by construction.
20. As a Judge Subagent, I want to submit a score against the Topic Visit id, so that the write is idempotent on the same identifier the redemption used.
21. As a Judge Subagent, I want to apply the same versioned rubric as the server Judge, so that scores from the two graders are comparable.
22. As the server, I want to issue every Topic Visit id myself, so that the host cannot invent one.
23. As the server, I want a redemption to be valid only for its own Visit, so that an id cannot be used to fish for other Topics' Answer Keys.
24. As the server, I want redemption to be single-use or narrowly scoped in time, so that a leaked id has a bounded blast radius.
25. As the server, I want to refuse to open a new Topic Visit while one is unresolved, so that the host cannot run ahead of grading.
26. As the server, I want a second score submitted for the same Topic Visit id to be a no-op, so that a retrying or confused host cannot double-write Evidence.
27. As the server, I want to enforce Session scope on every Topic request, so that the host cannot examine a Module the Candidate did not choose.
28. As the server, I want to apply the Grading Mode weight myself from the Visit's recorded mode, so that a host or subagent cannot supply a weight.
29. As the server, I want to record Grader Provenance as Judge Subagent on these rows, so that drift between graders is findable later.
30. As the server, I want to store the raw exchange for every MCP-graded Visit, so that these rows are re-judgeable in batch like any other.
31. As the server, I want an unresolved Visit to remain open across a disconnect, so that resumption grades it rather than losing it.
32. As a system operator, I want MCP Mode Sessions to be distinguishable in the record, so that I can compare grading quality between modes.
33. As a system operator, I want the server to be safe against a host that ignores every prompt, so that correctness does not depend on the host's cooperation.
34. As a system operator, I want a fallback recorded when subagents cannot reach the server, so that host-relayed material is a deliberate, visible cost rather than a silent one.
35. As a future maintainer, I want the MCP surface to be a driver over the same modules Managed Mode uses, so that a fix to the tracker or the rubric lands in both modes at once.

## Implementation Decisions

**Modules built**

- *MCP Tool Surface* — the tools the host drives. Thin: it validates, delegates, and enforces. No interviewing logic of its own.
- *Topic Visit Redemption* — issues Visit ids, redeems them for grounding, and scopes what a redemption may return. The single security-relevant module in this PRD.
- *Session Guard* — enforces scope, Visit ordering and the unresolved-Visit block, independent of anything the host was told.

Everything else — selection, dossiers, the rubric, the tracker — is reused
unchanged from PRD-0001 through PRD-0003. MCP Mode is a second driver, not a
second system.

**The shape**

`submit_answer` opens a Topic Visit and returns a `topic_visit_id`. The Judge
Subagent redeems that id for exactly the grounding of that one Visit and submits
a score against the same id. The score write is idempotent on it.

Both cross-mode invariants therefore hold without asking the host to cooperate:
the host cannot see an Answer Key, and it cannot write Evidence twice.

**What the host can and cannot get**

The host's dossier call returns the interviewing load path from PRD-0001 — the
one that structurally cannot return Ground Truth. There is no parameter, flag or
alternate call on the host's surface that returns grading material. The grading
load path is reachable only through redemption, and only against a Visit id the
server issued.

**Redemption scoping**

A redemption returns the grounding for one Visit and nothing adjacent. It is
bounded — single-use, or valid only while its Visit is open — so that an id
observed in a transcript does not become a key to the Corpus's Answer Keys.
Redemption for a Visit that is already graded returns nothing new.

**The unresolved-Visit block**

The server refuses to open a new Topic Visit while one is unresolved. This is
what makes "the Session will not advance while a Visit is unresolved" true of a
host we do not control, and it is also what makes resumption work: an interrupted
MCP Session has at most one open Visit, and the exchange for it is already
stored.

**Weights and provenance**

The weight comes from the Visit's recorded Grading Mode, applied server-side. A
subagent submits `s` and nothing else that affects the posterior. Provenance
records grader identity — Judge Subagent — and the provider behind it. Weights
stay set by Grading Mode: a Judge Subagent following the same rubric is not
weaker evidence, and inventing a mode-4 for it would make `α + β` uninterpretable
in exactly the way the coarse weights are deliberately not.

**Billing**

In MCP Mode the host's own Claude subscription pays for both the interviewing and
the Judge Subagent. There is no key to hold and nothing to meter — Credits and
BYOK (PRD-0005) do not apply here. This is the reason MCP Mode is cheap for us
and the reason its cost model needs no design.

**The dependency, stated plainly**

Subagents must inherit MCP server access in the host environment. Where they do
not, this collapses to host-relayed material and the leakage becomes a deliberate
cost rather than a solved problem. That fallback is detected and recorded on the
Session, never entered silently — a Session that leaked by fallback must be
identifiable afterwards.

**Prompts**

Tool descriptions and returned guidance steer the host toward the intended loop:
ask one Topic at a time, dispatch a subagent to grade, do not attempt to grade
yourself. This is worth doing and is worth nothing as a guarantee. Any invariant
that matters is in the server. Anything only in a prompt is a preference.

## Testing Decisions

A good test here is written from the position of a hostile or broken host: it
asserts that the server holds regardless of what the caller does. Tests drive the
tool surface directly rather than through a real Claude session — the point is
what the server permits, not what a well-behaved host happens to do.

**Topic Visit Redemption and leakage prevention — the critical suite.**

- no host-facing tool returns Ground Truth for any Topic, including one with an Answer Key
- redemption against a valid Visit id returns the grounding for that Visit only
- redemption against another Visit's id returns that Visit's grounding and no more — an id is not a general key
- redemption against a fabricated or malformed id is refused
- redemption against a Visit belonging to another Session or Candidate is refused
- a redemption outside its bound (reused, or after the Visit closed) is refused
- the grounding returned for a text-grounded Visit contains no Answer Key

**Session Guard — tested against a misbehaving caller.**

- opening a second Topic Visit while one is unresolved is refused
- requesting a Topic outside the Session's chosen Modules is refused
- submitting a score for a Visit that was never opened is refused
- submitting a second score for the same `topic_visit_id` leaves the posterior unchanged and reports the existing result
- submitting a weight, a Grading Mode, or an `α`/`β` delta from the caller has no effect — the server derives them
- a Session with an unresolved Visit, disconnected and resumed, still has exactly one open Visit and grades it once
- a completed MCP Session's Evidence rows are indistinguishable in shape from Managed Mode rows, and distinguishable in provenance

**Judge Subagent contract.**

- what the subagent receives on redemption contains question, answer and grounding, and no conversation history
- the same exchange graded by the server Judge and by a Judge Subagent with the same rubric version and stubbed model produces the same score
- rubric version and grader provenance are recorded on the resulting row

**Fallback path.**

- when subagent server access is unavailable, the Session records that it entered the host-relayed fallback
- a fallback Session is identifiable in the record afterwards

**Not tested.** Whether a real host Claude follows the intended loop. It is not
testable and, by design, does not need to be — that is the entire content of this
PRD.

**Prior art.** PRD-0002's idempotency tests and PRD-0003's loop tests cover the
same invariants from the inside; these cover them from the outside, against a
caller assumed to be uncooperative.

## Out of Scope

- Managed Mode's graph. MCP Mode drives the same modules; it does not run the graph.
- Credits, BYOK and metering. The host's subscription pays; there is nothing to meter.
- Authentication and account linking between a Claude session and a Candidate record. Needed before this ships to strangers; not designed here.
- Rate limiting, quotas and abuse handling for a publicly reachable server.
- Distribution: how a Candidate installs or discovers the server.
- Making the host behave. Prompts steer; the server enforces; there is no third option being pursued.

## Further Notes

The reason this PRD exists as its own document rather than as a surface inside
PRD-0003 is that its failure modes are different in kind. Managed Mode's risks
are correctness risks inside code we wrote. MCP Mode's risks are what an
uncontrolled agent does with a tool surface — and the mitigation is not better
prompting, it is a smaller surface.

Worth stating for a future reader tempted to simplify: handing the dossier to the
host and letting it pass grading material to its own subagent is the obvious
design, is one line shorter, and is exactly what ADR-0006 rejected. The Answer
Key would sit in the interviewing context for the rest of the Session, possibly
for a Topic not yet asked. Redemption exists to make that structurally
impossible, not to be tidy.

The upside of MCP Mode is disproportionate to its cost: the host's subscription
pays for inference, so a Session costs us essentially nothing, and the Evidence
it produces is the same Evidence at the same weights. If the mode works, it is
the cheapest route to the graded rows that every deferred question — the provider
normaliser, judge drift, adaptive termination — is waiting on.
