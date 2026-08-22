# Pool drawdown is measured in our own numbers, with the provider's recorded beside it

`pool_ledger` drawdown rows are written from our own summed `call_record` costs.
OpenRouter's reported usage figure for the same window is stored on the row next
to it, and the difference between the two is a monitored metric. Neither is
declared "correct". The authority question is deliberately left open, to be
settled from production data.

## Why our sum, and not the provider's

Not because it is more accurate. Because of what the invariant is written in.

ADR-0010 and PRD-0005 state the pool invariant as
`pool ≥ sum(candidate balances)`, and every candidate balance is derived from
`credit_ledger` debits, which are derived from `call_record`. Recording drawdown
from the provider's figure would compare two quantities produced by different
processes and call the comparison an invariant. The invariant would then drift
by the size of the disagreement, and we would be unable to tell a genuine
shortfall from an accounting mismatch — which is the one thing the pre-funding
design exists to make impossible.

Our sum is also the only figure attributable to a **Topic Visit**, which is the
unit **Evidence**, idempotency and refunds already key on.

## Why the provider's figure is stored anyway

Because the disagreement is information, not noise. It is the same class of
signal as the unpriced call rate in SPEC-0005 §7: a number that should be near
zero, whose drift means something specific has broken.

A persistent gap in one direction means we are under-counting spend — calls made
that never produced a `call_record`, which is the failure mode the metering
chokepoint exists to prevent and would otherwise be invisible. A gap in the
other direction means we are charging Candidates for calls the provider did not
bill.

Storing both makes that measurable from the day the system runs, rather than
requiring a migration once someone notices the numbers are off.

## Why not decide the authority now

Guessing which source is right, with no data, and then encoding the guess is the
same mistake as the provider normaliser PRD-0005 refuses to invent. The
information needed to decide — how large the gap is, which direction it runs,
whether it correlates with a provider or with unpriced calls — arrives free
once both figures are recorded.

If the gap turns out to be immaterial, this stays as it is and the decision
never needs making. That is a legitimate outcome and the most likely one.

## Consequence

`pool_ledger` carries both figures on a drawdown row, and pool headroom is
computed from ours. The operator surface (PRD-0005 §7) gains one reading:
cumulative divergence, alongside the unpriced call rate it belongs next to.

This decision is revisitable by construction. Flipping the authority later is a
recomputation over rows that already hold both numbers, not a migration.
