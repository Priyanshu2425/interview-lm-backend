# The Answer Turn crosses the wire as a request, not a socket

A Candidate's **Answer Turn** is delivered by an ordinary HTTP request that
carries a client-generated idempotency key and returns when the graph next
parks. Server-sent events stream question and rationale *text* within a turn.
They never carry the turn boundary.

## Why

PRD-0003 requires the graph to treat the Answer Turn as **an event it waits for,
never a read from a particular kind of input**, and states that a surface which
cannot say when a turn ended cannot be plugged in. A request is that statement,
made by the surface, at one instant, with a body. There is nothing to infer.

**A dropped socket is ambiguous; a retried request is not.** If a WebSocket
closes mid-turn, the surface cannot know whether the answer was received, and
resumption has to reconcile a half-known state — for the exact unit that
**Evidence**, metering and refunds all key on. With a request plus an
idempotency key, the retry is a no-op that returns the existing result, which is
the same mechanism ADR-0004 and SPEC-0005 already use everywhere else.

## Why not WebSocket

Liveness would become a precondition for correctness. The interview is turn-
based and slow — a Candidate thinks for a minute, the Judge takes seconds — so
a persistent connection buys nothing the request does not, while making every
network blip a state-reconciliation problem.

## Why streaming still exists

Waiting in silence for a question to appear is a bad interview. SSE streams the
question and the Judge's rationale as they generate, which is presentation. The
rule is that no stream event ever advances the graph.

## Consequence

The turn request is long-running: it returns only when grading completes and the
next park is reached. It therefore needs an explicit timeout and a documented
recovery — on timeout the surface polls Session state and resumes, which is the
same path an interrupted Session already takes. This is a real cost and it is
paid deliberately, because it keeps the boundary explicit.

Voice and the code editor supply the turn their own way against an unchanged
contract. For the code editor this is what keeps a test run from being mistaken
for an answer: running is a different endpoint entirely.
