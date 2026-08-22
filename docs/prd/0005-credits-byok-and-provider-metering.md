# PRD-0005 — Credits, BYOK and Per-Visit Provider Metering

Status: ready-for-agent
Depends on: PRD-0002, PRD-0003; ADR-0002, ADR-0004, ADR-0008
Referenced as deferred work by: PRD-0003, PRD-0004

## Problem Statement

Every other PRD in this project says the same sentence in its Out of Scope
section: *this assumes a working model client and does not care whose key paid*.
Nothing builds that client. A Session cannot run.

Underneath the missing plumbing sit three problems that are not plumbing.

**Nobody knows what a Session costs, including us.** Topic dossiers vary 4.3×
across Modules and the Candidate chooses the duration, so the price of a Session
is not knowable before it runs. A product that cannot quote a price in advance
either surprises the Candidate with a bill or refuses to start — and both are
worse than telling them the truth about which unit of spend they control.

**A Candidate's balance and our provider account are two ledgers that can
disagree.** Money arrives from a Candidate on one schedule and leaves to
OpenRouter on another. If those are reconciled after the fact, then settlement
lag, a failed card, or a refund can leave a Candidate holding a positive balance
against an empty pool — and the failure surfaces mid-Session, in front of the
Candidate, as an error that is not their fault and that they cannot act on.

**Running out of money mid-question corrupts the record.** A Session ends softly,
after the current Topic Visit completes, never inside one — because a truncated
Visit produces either no Evidence or Evidence from a half-examined answer. A
naive spend check does the opposite: it stops at whatever call happens to exhaust
the balance, which is usually inside a Visit. The billing system, left to its own
logic, will break the one invariant the Evidence model rests on.

And a fourth problem that is purely about honesty: BYOK Candidates spend no
Credits at all. Telling one of them their Credits ran out — when their real
problem is a revoked key at DeepSeek — is a support ticket manufactured by
sloppy error handling.

## Solution

Route every model call in the system through one metered client, and make the
Topic Visit the unit that spend, provenance and refunds all key on — the same
unit Evidence and idempotency already key on.

A **Credit** is defined as one US cent of what OpenRouter charges us. Not a unit
of value, not a currency we invent, not a smoothed average: a $9.70 call spends
970 Credits. Credits therefore float with the **Provider**, and the Candidate
sees that — choosing DeepSeek over Claude visibly stretches a balance. This is
the only definition that lets us show a price without pretending to know one in
advance.

The pool problem is removed rather than detected. The OpenRouter pool is
**pre-funded** from our own bank account ahead of receipts, and Credits are
granted to a Candidate only once their payment clears. `pool ≥ sum(candidate
balances)` then holds by construction, so a Candidate with a positive balance is
never blocked by an empty pool. The cost is working capital, and that is a
deliberate trade: the float is recoverable as service rather than as cash, and we
would rather carry it than ship a failure mode that fires mid-interview.

Spend is checked at the **Topic Visit boundary**, never inside one. A Visit opens
only if the balance clears a headroom threshold; once open it runs to completion
even if it overruns, because the Evidence invariant outranks a few Credits. A
balance may end a Visit slightly negative. It may never end a Visit early.

**BYOK** is the same machine with one branch: which key pays, and whether Credits
decrement. Routing, Provider selection, per-Visit metering, provenance and
grading are identical. The keys accepted are OpenRouter keys only — they carry
their own spend cap and are revocable in isolation — and grading always runs
server-side, because a client that produces its own score can mint its own
Mastery.

## User Stories

1. As a Candidate, I want to buy Credits and see them in my balance once payment clears, so that my balance is money I actually have.
2. As a Candidate, I want a Credit to mean one cent of real provider cost, so that the number is a fact rather than a house currency.
3. As a Candidate, I want to choose a Provider before a Session starts, so that I can trade cost against quality myself.
4. As a Candidate, I want to see each Provider's relative price before I choose, so that the choice is informed rather than a guess between three brand names.
5. As a Candidate, I want to be told that a Session's total cost cannot be quoted in advance, so that I am not surprised by a number nobody promised.
6. As a Candidate, I want to see what a Topic Visit cost me after it completes, so that I learn the real price of the thing I am buying.
7. As a Candidate, I want a running total for the Session, so that I can end early if it is costing more than I expected.
8. As a Candidate, I want the cost shown alongside which grader and provider produced my score, so that price and provenance read as one fact.
9. As a Candidate, I want to be warned when my balance is running low, so that I can top up before a Session ends on me.
10. As a Candidate, I want a Session to stop opening new Topic Visits when my balance is exhausted, so that the Session ends cleanly rather than erroring mid-question.
11. As a Candidate, I want the Topic Visit I am inside to finish even if it overruns my balance, so that the answer I already gave still gets graded and still counts.
12. As a Candidate, I want an exhausted balance to be a resumable state, so that topping up continues the Session rather than starting a new one.
13. As a Candidate, I want to supply my own OpenRouter key, so that I can pay my provider directly.
14. As a BYOK Candidate, I want to be told that my key spends no Credits, so that I understand which ledger I am on.
15. As a BYOK Candidate, I want a failure at my provider to name that provider and the reason, so that I fix the thing that is actually broken.
16. As a BYOK Candidate, I want to never be told my Credits ran out, so that an error message does not send me to the wrong place.
17. As a BYOK Candidate, I want my key held encrypted and revocable, so that handing it over is a bounded risk.
18. As a BYOK Candidate, I want to be told at the moment I attach a key whether it works, so that the first failure is not mid-Session.
19. As a BYOK Candidate, I want to remove my key and fall back to Credits, so that I am not locked into a payment route.
20. As a Candidate, I want to know that only OpenRouter keys are accepted, so that I never hand over an Anthropic or Google credential.
21. As a Candidate, I want grading to be paid for on the same key as the interviewing, so that there is no hidden second bill.
22. As a Candidate, I want a refund when a failure was ours, so that a broken Visit is not a Visit I paid for.
23. As a Candidate, I want a refund credited against the Topic Visit it belongs to, so that the refund is checkable against what I was charged.
24. As a Candidate in MCP Mode, I want no Credits and no key involved at all, so that using my own Claude subscription is genuinely free of our billing.
25. As the Interviewer, I want a Provider bound for the whole Topic Visit, so that one score is not split across two graders.
26. As the Judge, I want to run on the Provider recorded for the Visit, so that provenance describes what actually graded.
27. As the graph, I want a Provider failure mid-Visit to park and error rather than switch providers, so that the provenance record stays interpretable.
28. As the graph, I want the retry after a parked Visit to run on whichever Provider is live when the next Visit opens, so that an outage costs a pause rather than a Session.
29. As the graph, I want the spend check to happen where a Session may legally end, so that billing cannot break the invariant that a Visit is never truncated.
30. As the graph, I want an ungraded Visit to write no Evidence even though its calls were metered, so that spend and Evidence stay independent facts.
31. As the system, I want exactly one path to a model provider, so that an unmetered call is impossible rather than discouraged.
32. As the system, I want every model call attributed to a Topic Visit, so that metering, Evidence, provenance and refunds all key on the same unit.
33. As the system, I want per-call spend recorded from the provider's reported cost, so that Credits are measured rather than estimated from token counts.
34. As the system, I want a call whose cost the provider does not report to be recorded as unpriced rather than as zero, so that a gap in metering is visible instead of silently free.
35. As the system, I want the spend ledger idempotent on a call id, so that a retried write does not double-charge.
36. As the system, I want Credits granted only after payment clears, so that the pool invariant is maintained by pre-funding rather than by reconciliation.
37. As the system, I want a failure classifier that cannot emit a Credit message on a BYOK Session, so that the honesty rule is structural rather than a prompt or a code review habit.
38. As an operator, I want the pool topped up ahead of receipts, so that settlement lag never starves a Candidate with a positive balance.
39. As an operator, I want an alert when pool headroom falls below a threshold, so that pre-funding is a scheduled act rather than an emergency.
40. As an operator, I want to see pool float as a working-capital figure, so that how large the float runs is a live decision rather than an accident.
41. As an operator, I want promotional Credits to spend from the same pool as purchased ones, so that a promotion is a margin question and never an availability one.
42. As an operator, I want per-Provider spend and per-Provider failure rates, so that Provider choice can be advised from data.
43. As an operator, I want spend attributable to Topic Visit, Session and Candidate, so that unit economics are readable without instrumenting anything new.
44. As an operator, I want refunds to be an explicit ledger entry rather than a balance edit, so that the ledger stays the record.
45. As a future maintainer, I want no provider normaliser anywhere in this system, so that `α + β` stays interpretable.
46. As a future maintainer, I want the raw exchange and provider recorded on every metered call, so that a normaliser can be derived from production data later rather than guessed now.
47. As a future maintainer, I want BYOK and Credits to differ in exactly one branch, so that adding a payment route later does not fork routing.

## Implementation Decisions

**Modules built**

- *Credit Math* — pure. Converts a provider-reported cost in USD to Credits in integer cents, applies debits and refunds to a balance, and answers whether a balance clears the Visit headroom. No storage, no clock, no network. Integer cents throughout; a float never touches a balance.
- *Metered Model Client* — the single chokepoint. Every model call in the system goes through it: Interviewer, Question Writer, Judge, and anything added later. Takes a bound Provider and a `topic_visit_id`, makes the OpenRouter call, and emits one Call Record. Nothing else in the codebase may construct a provider client.
- *Provider Binding* — resolves a Session's Provider choice and payment route into the concrete client a Visit will use, and holds it fixed for that Visit's lifetime. Records the binding on the Visit. Rebinds only between Visits.
- *Credit Ledger* — append-only. One row per metered call, one row per grant, one row per refund. Balance is derived from the ledger, never edited in place. Idempotent on call id.
- *Pool Ledger* — the operator-side record of OpenRouter pool funding and drawdown, and the `pool ≥ sum(balances)` headroom reading that pre-funding is scheduled against.
- *Key Vault* — encrypted storage for BYOK OpenRouter keys, validated at attach time and revocable. Rejects anything that is not an OpenRouter key.
- *Failure Classifier* — pure. Maps a provider or billing error into exactly one of a small set of user-facing events, and structurally cannot emit a Credit-flavoured event on a BYOK Session.
- *Spend Disclosure* — turns ledger rows into what a Candidate sees: per-Visit cost, Session running total, Provider price comparison, low-balance warning. Sits next to Grader Provenance, which is already visible.

**The Credit definition, and what follows from it**

One Credit is one US cent of what OpenRouter charges us. Cost comes from the
provider's reported figure on the response, not from a token count multiplied by
a price table we maintain — a price table is a second source of truth that drifts
silently the day a provider changes pricing.

A call whose cost OpenRouter does not report is recorded as **unpriced** and
charged zero, with the row flagged. Unpriced is not zero-cost; it is a metering
gap, and it is visible in the ledger and countable in reporting. Silently
charging nothing is how a metering bug survives a quarter.

Rounding is to whole Credits, at the call, away from us: a sub-cent call costs
zero Credits rather than one. The alternative — rounding up per call — turns a
chatty Visit into a rounding-fee product, which is exactly the sort of thing that
makes a transparent price stop being transparent.

**Spend is checked at the Visit boundary, never inside one**

`decide_next` is the only place a spend check runs. A Visit opens only if the
balance clears a headroom threshold sized from the observed per-Visit cost
distribution. Once open, the Visit runs to completion — every call it needs,
including the Judge — regardless of what the balance does in the meantime.

**A balance may go negative. A Visit may never be truncated.** This is the
decision this PRD exists to make, and it is settled in the Evidence model's
favour: a Visit cut off mid-exchange produces no Evidence or corrupt Evidence,
and either outcome costs more than the overrun. The negative balance is a real
number, carried, and cleared on the next top-up.

Exhaustion at the boundary is therefore a clean end, not an error: the Session
stops opening Visits, reports why, and parks. Topping up resumes it — the
checkpointer already makes this free (ADR-0003, PRD-0003).

**Metering is per call; refunds are per Visit**

Every call is metered when it happens, so an ungraded Visit still cost money and
the ledger says so. Spend and Evidence are independent facts and are never
derived from one another.

Refunds are the exception that reunites them, and they key on `topic_visit_id`:
where a Visit failed for a reason that was ours — our bug, our outage, a Judge
that never returned — the Visit's calls are refunded as one explicit ledger
entry. A refund is never a balance edit. The ledger is the record; a balance is a
reading of it.

A Visit that failed at the Candidate's own provider under BYOK has nothing to
refund, because no Credits were spent.

**Provider is fixed for a Visit and recorded on it**

The Provider may change between Visits — an outage failover, or the Candidate
switching — and may never change inside one. Splitting a single score across two
graders corrupts the provenance record that a future normaliser depends on.

A Provider failure mid-Visit is therefore handled exactly like a credit failure:
park, error, resume. The retry runs on whichever Provider is live when the next
Visit opens. There is no mid-Visit failover, and the absence is deliberate.

**BYOK differs in one branch and no others**

Which key pays, and whether Credits decrement. Routing, Provider selection,
per-Visit metering, provenance, rubric and grading are identical code paths.

OpenRouter keys only (ADR-0008). A key is validated at attach time against a
cheap call, so the first failure is not mid-Session. Keys are held encrypted and
can be removed, at which point the Candidate falls back to Credits.

Grading runs server-side on the Candidate's key. It is paid for on the same key
as the interviewing — there is no second bill — and the Judge remains ours and
blind (ADR-0002). A client-side grader is permanently rejected: a Candidate who
produces their own score can mint their own Mastery.

BYOK applies to **Managed Mode only**. In MCP Mode the host's Claude subscription
pays for both the interviewing and the Judge Subagent, so there is no key to hold
and nothing to meter. The metering path is simply absent there, not disabled.

**Failure taxonomy is structural, not editorial**

Two failures that look similar and must never be confused:

- *Credit exhaustion* — ours. Names Credits, offers a top-up, and is a resumable park.
- *BYOK provider failure* — theirs. Names the Provider and the reason (revoked, rate-limited, unfunded), and must never mention Credits.

The classifier takes the payment route as an input and has no code path from a
BYOK Session to a Credit-flavoured event. Enforcing this in a message template or
a code-review habit is how it eventually leaks.

**Pre-funding, not reconciliation**

The pool is topped up from our own bank account ahead of receipts. Credits are
granted only once payment clears. `pool ≥ sum(candidate balances)` then holds by
construction rather than being checked after the fact.

Pool balance is a one-way float — recoverable as service, not as cash — so its
size is an operator decision with an alert threshold, not a set-and-forget
number. Promotional Credits spend from the same pool, which makes a promotion a
margin question and never an availability one.

**No provider normaliser**

Weights are set by Grading Mode alone. No constant that adjusts a score for
having been graded by DeepSeek rather than Claude exists, and none will be
invented: a fitted constant with no data behind it makes `α + β` uninterpretable
in exactly the way the Grading Mode weights are deliberately not.

This is affordable because the raw exchange is already stored on every Evidence
row (PRD-0002). Any Evidence can be re-judged later by any grader, so a
normaliser can be measured retroactively and mis-weighted history rebuilt.

## Testing Decisions

A good test here asserts what a Candidate, an auditor or an operator would
observe: what the balance became, what the ledger says, what the Candidate was
told, which key was used. It does not assert how many HTTP calls were made, what
an SDK was configured with, or the shape of an internal request object.

The provider is stubbed. These are tests of the machine around the provider —
which is the whole reason the provider sits behind one chokepoint.

**Credit Math — tested directly, no I/O.**

- $9.70 reported cost converts to exactly 970 Credits
- a sub-cent call converts to 0 Credits, not 1
- conversion is exact at values that would drift under floating point
- a debit larger than the balance produces a negative balance rather than a clamped zero or an error
- headroom clears and fails at the boundary value, in both directions
- a refund of a debit restores the exact prior balance
- balances are integers at every step; no operation returns a fraction

**Failure Classifier — tested directly, no I/O.**

- an exhausted balance on a Credit Session yields the Credit event
- a revoked key on a BYOK Session yields a provider event naming the provider and the reason
- a rate-limited BYOK key yields a provider event, not a Credit event
- an unfunded BYOK key — the case most likely to be miswritten — yields a provider event and its message contains no reference to Credits
- exhaustive check: no input on a BYOK Session produces a Credit-flavoured event
- an MCP Mode failure references neither Credits nor a key

**Metered Model Client — tested through a stubbed provider.**

- every call emits exactly one Call Record carrying its `topic_visit_id`
- a call made without a `topic_visit_id` is rejected rather than recorded unattributed
- a provider response with no reported cost is recorded as unpriced and flagged, and charges zero
- unpriced calls are countable in reporting rather than indistinguishable from free ones
- a retried write for the same call id is a no-op returning the existing row
- a Session's Interviewer, Question Writer and Judge calls all appear under the same Visit
- no module outside the client can reach a provider — asserted as a static check over the codebase, not a runtime one

**Provider Binding — tested through a scripted Session.**

- every call within one Visit uses the Provider bound at its open
- a Provider change requested mid-Visit does not take effect until the next Visit
- the binding is recorded on the Visit and matches the provenance on its Evidence row
- a Provider failure mid-Visit parks the Session and writes no Evidence for that Visit
- resuming after a parked Visit binds whichever Provider is live at that moment
- under BYOK the Candidate's key is used for the Judge call as well as the interviewing calls
- under Credits the platform key is used and the Candidate's key is never consulted

**Credit Ledger and Pool — tested through the store.**

- balance is derived from ledger rows and matches the sum of grants, debits and refunds
- a grant is written only after payment clears
- a refund keyed on a `topic_visit_id` refunds every call under that Visit exactly once
- a repeated refund for the same Visit is a no-op
- a BYOK Session writes no debit rows at all
- an ungraded Visit still has its calls metered — spend and Evidence are independent
- a Session parks when the balance fails headroom at a Visit boundary and writes no partial Visit
- an in-flight Visit completes and grades when the balance is exhausted mid-Visit, ending negative
- topping up resumes a parked Session rather than starting a new one
- pool headroom falls below threshold → an alert is raised; `pool ≥ sum(balances)` holds across a grant/spend/refund sequence

**Not tested.** Whether a Provider is worth its price, whether the headroom
threshold is well-chosen, whether the low-balance warning fires early enough.
These are judgement calls the ledger makes measurable over time, not assertions.

**Prior art.** PRD-0002's Evidence Ledger tests establish the idempotency
pattern — server-issued id, second write is a no-op returning the existing row —
and the Credit Ledger reuses it on call id. PRD-0003's scripted-Session tests
establish the stubbed-model harness these Visit-boundary tests extend.

## Out of Scope

- Metering in MCP Mode. The host's subscription pays; there is nothing to meter (PRD-0004).
- A provider cost normaliser. Refused on principle, not deferred — it would make `α + β` uninterpretable.
- Payment processing, checkout, invoices, tax and refund policy. This PRD consumes a *payment cleared* event and produces a grant; it does not take money.
- Candidate accounts, auth and billing UI beyond the spend readings named here.
- Per-Provider quality measurement. The data to derive it accumulates here; the analysis is later work.
- Mid-Visit provider failover. Structurally rejected — it would split one score across two graders.
- Cost estimation or quoting before a Session. Not knowable, and a fake estimate is worse than none.
- Raw vendor keys. Permanently rejected in ADR-0008.
- Client-side grading of any kind, for any reason.
- Rate limiting, quotas and abuse controls.

## Further Notes

The two hard decisions in this PRD both resolve the same way, and it is worth
naming the pattern: when billing and the Evidence model conflict, Evidence wins.
A Visit runs to completion on an exhausted balance because a truncated Visit
corrupts a permanent write while an overrun costs a few Credits. A Provider never
switches mid-Visit because provenance is permanent while a park is a pause.
Billing is recoverable; the Beta values are not.

The headroom threshold is the one number here with no principled derivation. It
should start deliberately generous — sized off the largest observed Topic dossier
rather than the median — and be tightened once the per-Visit cost distribution is
real data rather than an estimate. Sizing it off the median guarantees the
overrun path fires routinely, and the overrun path is the one that carries a
negative balance.

Everything a future provider normaliser would need is being recorded here and in
PRD-0002 — provider, grader identity, rubric version, raw exchange, per-call
cost. That is the deliberate shape: collect what makes the question answerable
later, and refuse to answer it with a guess now.
