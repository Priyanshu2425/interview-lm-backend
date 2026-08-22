# candidate_id is ours and is never an identity-provider subject

Authentication is delegated to an external identity provider over OIDC. The
subject it returns is stored on an `identity` row that points at a **Candidate**.
`candidate_id` is issued by us, is opaque, and appears in no token.

## Why

`candidate_id` is the join key for everything permanent in the system: 71
**Topic Confidence** rows per Candidate, every **Evidence** row with its stored
exchange, every ledger entry, every `call_record`. ADR-0007 already made this
argument for `topic_id` — identity is the join key for everything permanent, so
it may not be borrowed from a system whose shape we do not control.

If `candidate_id` were a Google subject, changing identity provider would mean
rewriting the permanent record. The record is explicitly irreversible (PRD-0002:
Evidence is append-only, and permanence is enforced by the store). Making it
depend on a vendor's identifier contradicts that at the root.

## Why not email

Emails change, and they are the field most likely to be reused across two humans
over a long enough period. A Candidate's **Mastery** history attaching to the
wrong person is a failure with no recovery.

## Consequence

One Candidate may hold several identities, so account merging is a supported
operation rather than an incident: it repoints `identity` rows and leaves every
`core` row untouched. This works only because nothing permanent references the
subject.

The **BYOK** key, the Credit balance and the Topic Confidence rows all hang off
`candidate_id`, so a Candidate who changes provider keeps their record, their
balance and their key.
