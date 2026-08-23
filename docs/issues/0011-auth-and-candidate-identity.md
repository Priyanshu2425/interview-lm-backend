# ISSUE-0011 — Auth and Candidate identity

Status: ready-for-agent — the provider is chosen (ADR-0026); the build is not done
Type: HITL
Source: ADR-0012; SPEC-0000
Covers: ADR-0012; prerequisite for every Candidate-scoped reading

## What to build

Authentication delegated to an external identity provider over OIDC, with a hard
separation between who signed in and who the **Candidate** is.

`candidate_id` is issued by us, is opaque, and appears in no token. The provider's
subject is stored on an `identity` row that points at a Candidate. This is the
same argument ADR-0007 makes for `topic_id`: identity is the join key for
everything permanent — 71 **Topic Confidence** rows per Candidate, every
**Evidence** row with its stored exchange, every ledger entry, every call record
— so it may not be borrowed from a system whose shape we do not control.

If `candidate_id` were a provider subject, changing identity provider would mean
rewriting a record the design makes deliberately irreversible. Email is rejected
for the same class of reason: emails change, and are the field most likely to be
reused across two humans over a long enough period.

One Candidate may hold several identities, so account merging is a supported
operation rather than an incident — it repoints `identity` rows and leaves every
permanent row untouched. That works only because nothing permanent references the
subject.

**Why HITL:** the identity provider was deliberately unchosen in ADR-0012.
It is now Gatehouse (ADR-0026), which also fixes where the surface may be
served from — its refresh cookie is `SameSite=Lax`, so the surface is same-site
with `auth.buildspacelabs.com` or it cannot sign anybody in.

## Acceptance criteria

- [x] An identity provider has been chosen and the decision recorded as an ADR (ADR-0026)
- [ ] `candidate_id` is server-issued and appears in no token or URL
- [ ] No permanent table references an identity-provider subject
- [ ] A Candidate can hold multiple identities pointing at one `candidate_id`
- [ ] Merging two Candidates repoints identity rows and leaves Topic Confidence, Evidence and ledger rows byte-identical
- [ ] Swapping the identity provider in a test harness leaves every permanent row untouched
- [ ] Every Candidate-scoped endpoint resolves the Candidate from the session, never from a client-supplied id
- [ ] A Candidate cannot read another Candidate's Sessions, posteriors, ledger or key — asserted per endpoint
- [ ] A Candidate who changes provider keeps their record, their balance and their attached key
- [ ] Sessions, Evidence and ledger rows created before auth existed remain readable and attributable

## Blocked by

- ISSUE-0002 — identity attaches to the Session and permanent tables that slice creates
