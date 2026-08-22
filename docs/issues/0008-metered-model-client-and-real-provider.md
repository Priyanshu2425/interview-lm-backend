# ISSUE-0008 — Metered Model Client and the real provider

Status: ready-for-agent
Type: AFK
Source: PRD-0005; ADR-0008, ADR-0009; SPEC-0005
Covers: PRD-0005 §31–§35; PRD-0003 §39

## What to build

The single chokepoint every model call in the system passes through, and the first
real provider traffic.

Every call — Interviewer, Question Writer, **Judge**, and anything added later —
goes through the Metered Model Client with a bound **Provider** and a
`topic_visit_id`. **Nothing else in the codebase may construct a provider
client**, and that is enforced by a static check rather than a convention,
because it is the kind of rule that decays in one careless import. A call
arriving without a `topic_visit_id` is rejected, not recorded unattributed.

Providers are reached through OpenRouter only. Cost comes from the provider's
reported figure on the response, never from a token count multiplied by a price
table we maintain — a price table is a second source of truth that drifts
silently the day a provider changes pricing.

A call whose cost is not reported is recorded as **unpriced** and flagged.
Unpriced is not zero-cost; it is a metering gap, visible in the record and
countable in reporting. Silently charging nothing is how a metering bug survives
a quarter.

**Provider Binding** resolves the Session's choice into the client a Visit uses
and holds it fixed for that Visit's lifetime. It may change between Visits and
never inside one: splitting one score across two graders corrupts the provenance
record. A provider failure mid-Visit parks the Session; the retry runs on whichever
Provider is live when the next Visit opens. There is no mid-Visit failover and no
function to call for one.

## Acceptance criteria

- [ ] Every model call emits exactly one call record carrying its `topic_visit_id`
- [ ] A call made without a `topic_visit_id` is rejected
- [ ] A response with no reported cost is recorded as unpriced, flagged, and charged zero
- [ ] Unpriced calls are countable in reporting rather than indistinguishable from free ones
- [ ] Cost is never derived from token counts
- [ ] A retried write for the same call id is a no-op returning the existing row
- [ ] A Session's Interviewer, Question Writer and Judge calls all appear under the same Visit
- [ ] A static check fails the build if any module outside the metering package constructs a provider client or imports the HTTP client
- [ ] Every call within one Visit uses the Provider bound at its open
- [ ] A Provider change requested mid-Visit takes effect only at the next Visit
- [ ] A second binding for the same Visit is a constraint violation, not a branch
- [ ] The binding recorded on the Visit matches the provenance on its Evidence row
- [ ] A Provider failure mid-Visit parks the Session and writes no Evidence for that Visit
- [ ] Resuming after a parked Visit binds whichever Provider is live at that moment
- [ ] Screen 03 shows the real cost of the Visit, in Credits, alongside its provenance

## Blocked by

- ISSUE-0007 — a provider failure mid-Visit must land in a working park-and-resume path
