# ISSUE-0010 — BYOK: key vault and failure classifier

Status: ready-for-agent
Type: HITL
Source: PRD-0005; ADR-0008, ADR-0013; SPEC-0005
Covers: PRD-0005 §13–§21, §37

## What to build

A Candidate pays their own inference costs with an OpenRouter key they supply.
**BYOK** differs from the Credit path in exactly one respect — which key pays,
and whether Credits decrement. Routing, Provider selection, per-Visit metering,
provenance and grading are identical code paths.

**Only OpenRouter keys are accepted.** They carry their own spend cap and are
revocable in isolation, so a breach costs a capped, revocable credential rather
than unbounded access to a Candidate's accounts at Anthropic, Google or DeepSeek.
There is no field that would take a raw vendor credential. A key is validated at
attach time against a real call, so the first failure is not mid-Session.

Keys are envelope-encrypted: a per-key data key, wrapped by a key-encryption key
in a managed KMS. Only the Metered Model Client holds permission to unwrap.
Plaintext never appears in a log, a call record, or an API response. Rotation
re-wraps data keys without touching ciphertext.

Grading still runs server-side. A client that produces its own score can mint its
own **Mastery**, and this is permanent — any future proposal to move grading
client-side for latency, cost or privacy reintroduces exactly that.

**The Failure Classifier is the honesty rule made structural.** A BYOK Candidate
spends no Credits, so telling them their Credits ran out sends them to fix
something that is not broken. The classifier takes the payment route as a required
input and **has no code path from a BYOK Session to a Credit-flavoured event**.
Enforcing that in a message template is how it eventually leaks.

BYOK applies to Managed Mode only.

**Why HITL:** the KMS choice and a security review of key custody, IAM boundaries
and log scrubbing need a human before any Candidate credential is held.

## Acceptance criteria

- [ ] Attaching a key performs live validation; a well-formed dead key is rejected at attach
- [ ] Anything that is not an OpenRouter key is rejected
- [ ] Keys are stored envelope-encrypted; a database dump alone does not yield plaintext
- [ ] Only the metering component holds unwrap permission, enforced by IAM
- [ ] Plaintext appears in no log, no call record, and no API response — asserted by a scrubbing test over emitted logs
- [ ] Rotating the key-encryption key leaves ciphertext untouched and keys usable
- [ ] Revoking a key deletes ciphertext and retains the fingerprint so history stays readable
- [ ] A BYOK Session writes no debit rows at all
- [ ] Under BYOK the Candidate's key pays for the Judge call as well as the interviewing calls
- [ ] Under Credits the platform key is used and the Candidate's key is never consulted
- [ ] An exhausted balance on a Credit Session yields the Credit event
- [ ] A revoked, rate-limited or unfunded BYOK key each yields a provider event naming the provider and the reason
- [ ] Exhaustively: no input on a BYOK Session produces a Credit-flavoured event, and no such message contains the word Credits
- [ ] An MCP Mode failure references neither Credits nor a key
- [ ] Removing a key falls back to Credits without touching the Candidate's record
- [ ] Screen 05 renders both failure messages, and the BYOK cost reads `—` rather than `0`
- [ ] A security review of key custody has been completed and signed off

## Blocked by

- ISSUE-0009 — BYOK is the Credit path with one branch, so the Credit path exists first
