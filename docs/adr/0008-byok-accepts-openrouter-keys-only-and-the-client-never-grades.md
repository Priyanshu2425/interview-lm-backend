# BYOK accepts OpenRouter keys only, and the client never grades

**BYOK** Candidates supply an OpenRouter key, held encrypted. Raw vendor
credentials are not accepted. Grading always runs server-side.

## Why not raw vendor keys

Custody is unavoidable — ADR-0002 puts the **Judge** on the server, so a key
that never reaches us cannot grade. Given that, the question is what we are
custodian *of*. An OpenRouter key carries its own spend cap and is revocable in
isolation, so a breach costs a capped, revocable credential rather than
unbounded access to a Candidate's Anthropic, Google and DeepSeek accounts.

It also collapses branching: BYOK and the **Credit** path then share routing,
**Provider** selection and per-**Topic Visit** metering, differing only in which
key pays and whether Credits decrement.

## Why the client never grades

A client-side-only key would keep us out of custody entirely, and it is rejected
for integrity rather than security. If the client produces the score, every Beta
value in the system becomes forgeable and no **Evidence** is auditable. A
**Candidate** could mint their own **Mastery**.

This is permanent. Any future proposal to move grading clientside — for
latency, for cost, for privacy — reintroduces exactly this.
