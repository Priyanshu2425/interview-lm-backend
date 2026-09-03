# SPEC-0005 — Credits, BYOK and Per-Visit Provider Metering

Implements: PRD-0005
Depends on: PRD-0002 (Evidence Ledger, Topic Visit Lifecycle), PRD-0003 (Session Graph)
Governed by: ADR-0002, ADR-0004, ADR-0008

Type signatures below describe **shape, not syntax** — no runtime or database has
been chosen in any ADR to date, and this spec does not choose one. Where a choice
is load-bearing it is called out under *Open decisions* at the end rather than
assumed silently.

---

## 1. Units and invariants

**Credit.** An integer. One Credit is one US cent of OpenRouter's reported cost.
Never a float, never a rate we set, never derived from a token count.

**Balance.** Derived from the Credit Ledger. Not a stored mutable field. May be
negative. Integer Credits.

**The five invariants this spec exists to hold**

| # | Invariant | Enforced by |
|---|---|---|
| I1 | Every model call carries a `topic_visit_id` | Metered Model Client rejects calls without one |
| I2 | A Provider is constant for a Topic Visit's lifetime | Provider Binding, resolved once at Visit open |
| I3 | Spend checks run only at a Visit boundary | Single call site in `decide_next` |
| I4 | A BYOK Session emits no Credit-flavoured event and no debit row | Failure Classifier has no such code path; Ledger writes no debits when route is BYOK |
| I5 | `pool ≥ Σ(candidate balances)` | Pre-funding + grant-on-clear ordering |

I3 is the one that will be violated by a well-meaning change. A spend check added
inside the Visit region reads as defensive and breaks the Evidence model.

---

## 2. Data model

### 2.1 `credit_ledger`

Append-only. Balance is `SUM(delta_credits)` over a candidate.

| Column | Type | Notes |
|---|---|---|
| `id` | id | server-issued |
| `candidate_id` | id | |
| `entry_type` | enum | `grant` \| `debit` \| `refund` \| `promo_grant` |
| `delta_credits` | integer | signed; `debit` negative, grants and refunds positive |
| `topic_visit_id` | id, nullable | required on `debit` and `refund`; null on grants |
| `session_id` | id, nullable | denormalised for reporting; null on grants |
| `call_id` | id, nullable | required and **unique** on `debit`; null otherwise |
| `refunded_visit_id` | id, nullable | required and **unique** on `refund` |
| `payment_ref` | string, nullable | required on `grant`; the cleared-payment identifier |
| `created_at` | timestamp | |

Uniqueness constraints are the idempotency mechanism, not application logic:

- `UNIQUE(call_id) WHERE entry_type = 'debit'` — a retried debit is a no-op
- `UNIQUE(refunded_visit_id) WHERE entry_type = 'refund'` — a Visit refunds once
- `UNIQUE(payment_ref) WHERE entry_type IN ('grant')` — a replayed payment webhook grants once

A `promo_grant` carries no `payment_ref` and is otherwise identical to a `grant`.
It draws from the same pool, which is the point (PRD-0005: a promotion is a
margin question, never an availability one).

### 2.2 `call_record`

One row per model call. Written by the Metered Model Client, by every caller,
with no exceptions.

| Column | Type | Notes |
|---|---|---|
| `call_id` | id | server-issued, idempotency key for the debit |
| `topic_visit_id` | id | **NOT NULL** — I1 |
| `session_id` | id | |
| `candidate_id` | id | |
| `role` | enum | `interviewer` \| `question_writer` \| `judge` \| `other` |
| `provider` | enum | `deepseek` \| `gemini` \| `claude` |
| `model_id` | string | the OpenRouter model slug actually served |
| `payment_route` | enum | `credits` \| `byok` |
| `reported_cost_usd` | decimal, nullable | as reported by OpenRouter |
| `cost_status` | enum | `priced` \| `unpriced` |
| `credits_charged` | integer | 0 when `unpriced` or when route is `byok` |
| `prompt_tokens` / `completion_tokens` | integer, nullable | reporting only — never a cost input |
| `latency_ms` | integer | |
| `outcome` | enum | `ok` \| `provider_error` \| `timeout` \| `rejected` |
| `created_at` | timestamp | |

`cost_status = 'unpriced'` is the metering-gap flag. It is countable, alertable,
and never collapsed into "cost 0" (PRD-0005, story 34).

Under `payment_route = 'byok'` the row is still written in full — provider,
model, tokens, latency, outcome — because it is the operational and provenance
record. Only `credits_charged` is zero and only the debit row is absent.

### 2.3 `visit_provider_binding`

One row per Topic Visit. Written at Visit open, never updated.

| Column | Type |
|---|---|
| `topic_visit_id` | id, primary key |
| `provider` | enum |
| `payment_route` | enum |
| `byok_key_id` | id, nullable |
| `bound_at` | timestamp |

The primary key on `topic_visit_id` is I2: a second binding for the same Visit is
a constraint violation, not a branch.

### 2.4 `byok_key`

| Column | Type | Notes |
|---|---|---|
| `key_id` | id | |
| `candidate_id` | id | |
| `ciphertext` | bytes | encrypted at rest; plaintext never logged, never returned |
| `key_fingerprint` | string | non-reversible; for display and dedupe |
| `status` | enum | `active` \| `revoked` \| `failed_validation` |
| `validated_at` | timestamp, nullable | |
| `last_error` | enum, nullable | see §5 |
| `created_at` / `revoked_at` | timestamp | |

Only OpenRouter keys are accepted (ADR-0008). Validation at attach is a real call
against OpenRouter's key/credit endpoint, not a regex on the prefix — a
well-formed dead key is the failure mode this prevents.

### 2.5 `pool_ledger`

Operator-side. Not per-candidate.

| Column | Type | Notes |
|---|---|---|
| `id` | id | |
| `entry_type` | enum | `topup` \| `drawdown` |
| `delta_credits` | integer | signed. On a drawdown this is **our** summed `call_record` cost (ADR-0014) |
| `provider_reported_credits` | integer, nullable | OpenRouter's figure for the same window, recorded beside ours and never used in the invariant |
| `source_ref` | string | bank transfer ref, or the usage window this row covers |
| `created_at` | timestamp | |

Pool headroom is computed from `delta_credits` alone. The difference between the
two columns is a monitored metric, not a correction — see ADR-0014 for why
neither source is declared authoritative yet.

Pool headroom = `SUM(pool_ledger.delta_credits) − Σ(candidate balances)`.
Alerting on this figure is §7.

---

## 3. Module interfaces

### 3.1 Credit Math — pure

```
usdToCredits(usd: Decimal): { credits: int, status: 'priced' }
usdToCredits(null):         { credits: 0,   status: 'unpriced' }

applyDebit(balance: int, credits: int): int      // may return negative
applyRefund(balance: int, credits: int): int
clearsHeadroom(balance: int, headroom: int): boolean   // balance >= headroom
```

Rules:

- Decimal arithmetic end to end. A float never touches a cost or a balance.
- Rounding is **floor** to whole Credits, at the call. A sub-cent call costs 0.
- `applyDebit` never clamps at zero and never throws on insufficient balance —
  the negative balance is the specified outcome (PRD-0005, I3 discussion).
- No clock, no storage, no randomness. Fully testable with no harness.

### 3.2 Metered Model Client — the chokepoint

```
call(request: {
  topicVisitId: id            // required; absence is a rejection, not a default
  role: 'interviewer' | 'question_writer' | 'judge' | 'other'
  binding: VisitProviderBinding
  messages: ...
  params: ...
}): Promise<{ callId, content, record: CallRecord }>
```

Contract:

- Resolves the API key from `binding.payment_route`: platform key for `credits`,
  decrypted BYOK key for `byok`. The caller never sees or supplies a key.
- Writes exactly one `call_record` per attempt, including failed attempts —
  a provider error that consumed tokens still cost money.
- Writes the `debit` ledger row in the same transaction as the `call_record`
  when route is `credits` and `cost_status = 'priced'`.
- Returns `callId` so a caller retrying at a higher layer can be deduped.

**No other module may construct a provider client.** This is enforced as a
lint/static check over the codebase (PRD-0005 testing section), because it is the
kind of rule that decays in exactly one careless import.

### 3.3 Provider Binding

```
bindForVisit(sessionId, topicVisitId, candidateId): VisitProviderBinding
```

- Called once, by the graph, at Visit open. Idempotent on `topic_visit_id`:
  a second call returns the existing binding.
- Resolution order: the **Session's** route, fixed at `POST /sessions` and
  carried onto every Visit of it. The Candidate chooses it; where they choose
  nothing it defaults to their active BYOK key if present and `active`, and
  otherwise to the Credit route. A Candidate holding a key may still run a
  Session on Credits — the two routes send different keys, so the attached key
  is left unused rather than billed alongside the ledger — while `byok` with no
  active key is refused at start rather than quietly resolved to Credits.
  Provider comes from the Session's chosen Provider, falling back to the next
  live Provider **only at bind time**.
- There is no `rebind` and no mid-Visit failover call. Its absence is the design
  (ADR-0004 provenance argument, PRD-0005).

### 3.4 Credit Ledger

```
balanceOf(candidateId): int
grant(candidateId, credits, paymentRef): LedgerEntry        // idempotent on paymentRef
promoGrant(candidateId, credits, reason): LedgerEntry
debit(callRecord): LedgerEntry | Existing                    // idempotent on callId
refundVisit(topicVisitId, reason): LedgerEntry | Existing    // idempotent on visit
```

- `refundVisit` sums every `debit` under that Visit and writes one positive entry.
  It is called only for failures attributable to us.
- Balance is always computed from the ledger. There is no balance column to
  drift, and no code path that edits one.

### 3.5 Key Vault

```
attach(candidateId, openRouterKey): { keyId, status }   // performs live validation
revoke(keyId): void
resolveFor(candidateId): DecryptedKey | null            // internal to the Metered Client
```

`resolveFor` is callable only by the Metered Model Client. Plaintext keys are
never logged, never included in a `call_record`, and never returned across an API
boundary.

### 3.6 Failure Classifier — pure

```
classify(input: {
  route: 'credits' | 'byok' | 'mcp'
  cause: ProviderCause | BillingCause
}): UserFacingEvent
```

The signature is the enforcement: `route` is required, and the function has no
branch from `route: 'byok'` to a Credit event (I4). See §5 for the taxonomy.

### 3.7 Spend Disclosure

```
visitCost(topicVisitId): { credits, provider, route, unpricedCalls: int }
sessionRunningTotal(sessionId): { credits, byVisit: [...] }
providerPriceComparison(): [{ provider, relativePrice, sampleSize }]
lowBalanceReading(candidateId): { balance, estimatedVisitsRemaining: int | 'unknown' }
```

`estimatedVisitsRemaining` returns `'unknown'` until enough per-Visit cost data
exists for the Candidate's chosen Provider and scope. It never guesses — PRD-0005
refuses to quote a Session price in advance, and a dressed-up estimate here would
reintroduce that by the back door.

Under `route: 'byok'`, `visitCost` reports provider and calls but reports credits
as `null`, not `0` — the Candidate spent no Credits, and zero reads as "it was
free" rather than "this ledger does not apply to you".

---

## 4. Control flow

### 4.1 The spend gate — the only one

Inside `decide_next` (PRD-0003's graph), before opening a Visit:

```
if route == 'byok'      → open Visit
else if route == 'mcp'  → open Visit                     // no metering exists here
else if clearsHeadroom(balanceOf(candidate), HEADROOM)
                        → open Visit
else                    → park Session, emit CREDITS_EXHAUSTED, end cleanly
```

Nothing anywhere else calls `clearsHeadroom`. A Visit already open is never
re-checked.

### 4.2 Visit open

1. `bindForVisit(...)` — writes `visit_provider_binding`, fixing Provider and route (I2)
2. Visit proceeds per PRD-0003; every model call goes through the Metered Client with the binding and the `topic_visit_id`
3. Judge call uses the **same** binding — same Provider, same key
4. On Evidence write, provenance on the Evidence row must equal `visit_provider_binding.provider`. A mismatch is a bug, and is asserted in tests.

### 4.3 Overrun

A Visit whose calls carry the balance below zero **completes**. No check
interrupts it. The negative balance is carried, surfaced to the Candidate at the
end of the Visit, and cleared by the next grant.

### 4.4 Mid-Visit provider failure

1. Metered Client writes the failed `call_record` (`outcome = provider_error`) and its debit if priced
2. The error propagates; the graph parks the Session (PRD-0003 resumption path)
3. The Visit stays **open and ungraded** — no Evidence is written
4. On resume, `decide_next` runs the spend gate again and a **new** Visit binds a fresh Provider

Where the failure was ours, `refundVisit` clears that Visit's debits.

### 4.5 Payment clears

`payment cleared` event → pre-funding check → `grant(candidateId, credits,
paymentRef)`. Grants never precede clearance (I5). This spec consumes the event;
it does not process payments.

---

## 5. Error taxonomy

Every user-facing failure is exactly one of these. The `route` column is the
constraint that makes I4 structural.

| Event | Valid routes | Message names | Must never name | Session outcome |
|---|---|---|---|---|
| `CREDITS_EXHAUSTED` | `credits` | balance, top-up action | a provider fault | park at boundary, resumable |
| `CREDITS_EXHAUSTED_MID_VISIT` | `credits` | balance now negative, top-up action | truncation — the Visit completed | Visit completes, then park |
| `BYOK_KEY_REVOKED` | `byok` | provider, "key revoked at OpenRouter" | Credits, balance, top-up | park, resumable after re-attach |
| `BYOK_KEY_UNFUNDED` | `byok` | provider, "no credit at your provider" | Credits, balance, top-up | park, resumable |
| `BYOK_KEY_RATE_LIMITED` | `byok` | provider, retry guidance | Credits | park, resumable |
| `BYOK_KEY_INVALID` | `byok` | attach-time validation failure | Credits | attach rejected; no Session started |
| `PROVIDER_UNAVAILABLE` | `credits`, `byok` | provider, outage | fault of the Candidate | park; next Visit rebinds |
| `PROVIDER_TIMEOUT` | `credits`, `byok` | provider | Credits under byok | park; next Visit rebinds |

`CREDITS_EXHAUSTED_MID_VISIT` exists as a distinct event because its message is
the opposite of what an engineer would write by reflex: it reports a completed
Visit and a negative balance, not a failure.

MCP Mode emits none of these. There is no key and no meter (PRD-0004).

---

## 6. Constants

| Name | Value | Basis |
|---|---|---|
| `CREDIT_PER_USD` | 100 | definitional — one Credit is one cent |
| `ROUNDING` | floor, per call | PRD-0005; rounding up makes a chatty Visit a fee |
| `HEADROOM_CREDITS` | start generous, from the **largest** observed Topic dossier, not the median | PRD-0005 Further Notes — sizing off the median makes the overrun path routine |
| `LOW_BALANCE_WARN` | a multiple of `HEADROOM_CREDITS` | tune from data |
| `POOL_HEADROOM_ALERT` | operator-set | §7 |

`HEADROOM_CREDITS` is the one number here with no principled derivation. It is a
named constant with a recorded basis so that tightening it later is a decision
rather than a discovery.

---

## 7. Operator surface

- **Pool headroom** — `pool − Σ balances`, with an alert below `POOL_HEADROOM_ALERT`. Pre-funding is scheduled off this reading, never triggered by a Candidate's failure.
- **Float** — pool balance reported as working capital. One-way: recoverable as service, not as cash.
- **Unpriced call rate** — proportion of `call_record` rows with `cost_status = 'unpriced'`, per Provider. A rising figure is a metering regression, and the only reason it is visible is that unpriced was never collapsed into zero.
- **Drawdown divergence** — cumulative `provider_reported_credits − delta_credits` across drawdown rows. Should sit near zero. A persistent gap upward means calls are being made that produce no `call_record`, which is precisely what the metering chokepoint exists to prevent and is otherwise invisible; a gap downward means Candidates are being charged for calls the provider did not bill (ADR-0014).
- **Per-Provider spend and failure rate** — from `call_record` alone, no new instrumentation.
- **Unit economics** — spend rolls up call → Visit → Session → Candidate on existing keys.

---

## 8. What this spec deliberately does not define

- Payment processing, checkout, invoicing, tax, refund policy. The boundary is the *payment cleared* event in, a `grant` out.
- A provider cost normaliser. Refused, not deferred (PRD-0005). The data to derive one is being recorded; the constant is not being invented.
- Mid-Visit failover. Structurally absent — there is no function to call.
- Any metering path in MCP Mode.
- Rate limiting, quotas, abuse controls.

## 9. Decisions since resolved

Two of the three gaps this spec opened have been settled, and the settlement
changes what §2 means:

1. **Runtime and database — settled.** Python on managed Postgres
   (ADR-0009, ADR-0010). The partial unique constraints this spec's idempotency
   rests on are expressed directly, so the fallback contemplated here — moving
   idempotency into a transaction — is not needed. `session` and `topic_visit`,
   referenced throughout §2 but undefined at the time, are specified in
   SPEC-0002.
2. **BYOK key custody — settled.** Envelope encryption with a per-key data key
   and a KMS-held key-encryption key, decryptable only by the Metered Model
   Client (ADR-0013). §2.4's `ciphertext` column is that ciphertext; §3.5's
   `resolveFor` is the only caller with permission to unwrap.

Still open:

3. **Pool drawdown authority — settled as a deliberate deferral (ADR-0014).**
   Drawdown is recorded in our own summed `call_record` costs, because that is
   the unit the pool invariant is written in; OpenRouter's figure is stored on
   the same row and the divergence is a monitored metric. Which source is
   *correct* is left open on purpose, to be answered from production data rather
   than guessed — and if the gap proves immaterial, the question never needs
   answering. Flipping the authority later is a recomputation over rows that
   already hold both numbers, not a migration.
