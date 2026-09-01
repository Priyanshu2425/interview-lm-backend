"""What an ingest costs, on the ledger the rest of the product already uses.

Two rules from PRODUCT.md apply here in opposite directions.

*Never quote a Session's price* — because Topic material varies four-fold and
the Candidate chooses the duration, so the total is not knowable in advance.
That reasoning does not transfer to ingest: the text is extracted before a
single provider call is made, so the token count is a measurement. It is still
not quoted, because the Candidate did not ask for a quote; it is simply spent
and shown, like everything else.

*Say which ledger you are on* — an insufficient balance stops ingest **before**
the first embedding call and names the shortfall, and a BYOK Candidate is never
shown a Credit message.
"""

from __future__ import annotations

from dataclasses import dataclass


class InsufficientBalance(Exception):
    """Refused before spending. Carries what was short, not a quote."""

    def __init__(self, *, required: int, balance: int) -> None:
        self.required = required
        self.balance = balance
        self.shortfall = max(0, required - balance)
        super().__init__(
            f"ingest needs {required} Credits and the balance is {balance}; "
            f"short by {self.shortfall}"
        )


@dataclass(frozen=True, slots=True)
class IngestCost:
    """A measurement, made after extraction and before embedding."""

    tokens: int
    credits: int
    model: str
    route: str

    @property
    def is_free(self) -> bool:
        return self.credits == 0


def estimate(texts: list[str], *, embedder, route: str) -> IngestCost:
    """Token count is our own, as ADR-0014 requires of every number we bill on."""
    tokens = sum(len(t) // 4 for t in texts)
    per_1k = float(getattr(embedder, "credits_per_1k_tokens", 0.0) or 0.0)
    credits = 0 if route != "credits" else int(-(-tokens * per_1k // 1000))
    return IngestCost(
        tokens=tokens,
        credits=credits,
        model=getattr(embedder, "model_name", "unknown"),
        route=route,
    )


class IngestMeter:
    """Gates ingest on balance, then records what it actually cost.

    The gate is a refusal, not a confirmation dialog: nothing is shown to the
    Candidate before ingest starts, and nothing is half-ingested after it stops.
    """

    __slots__ = ("_credits",)

    def __init__(self, credits=None) -> None:
        self._credits = credits

    def gate(self, cost: IngestCost, *, candidate_id: str) -> None:
        if cost.is_free or self._credits is None:
            return
        balance = self._credits.balance(candidate_id)
        if balance < cost.credits:
            raise InsufficientBalance(required=cost.credits, balance=balance)

    def charge(
        self, cost: IngestCost, *, candidate_id: str, notebook_id: str, source_id: str
    ) -> None:
        """Idempotent on the Source, so a resumed ingest never bills twice."""
        if cost.is_free or self._credits is None:
            return
        self._credits.debit(
            candidate_id=candidate_id,
            call_id=f"ingest:{source_id}",
            credits=cost.credits,
            topic_visit_id=f"ingest:{source_id}",
            session_id=f"ingest:{notebook_id}",
        )
