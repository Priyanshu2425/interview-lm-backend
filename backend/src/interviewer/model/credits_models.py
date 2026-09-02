"""Credit Math — pure. Integer cents end to end; a float never touches a balance.

One Credit is one US cent of what OpenRouter charged us. Not a house currency
and not a smoothed average: a $9.70 call spends 970 Credits. Credits therefore
float with the Provider, and the Candidate sees that.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from enum import Enum
from typing import Final

CREDIT_PER_USD: Final = 100

# The one number here with no principled derivation. Sized off the largest
# observed dossier rather than the median, because sizing it off the median
# guarantees the overrun path fires routinely — and the overrun path is the one
# that carries a negative balance.
HEADROOM_CREDITS: Final = 400
LOW_BALANCE_WARN: Final = HEADROOM_CREDITS * 4


class CostStatus(str, Enum):
    PRICED = "priced"
    UNPRICED = "unpriced"


@dataclass(frozen=True, slots=True)
class Cost:
    """What one call cost, and whether we could price it at all."""

    credits: int
    status: CostStatus

    @classmethod
    def of_usd(cls, usd: Decimal | float | str | None) -> "Cost":
        """Convert a provider-reported cost.

        `None` is **unpriced**, not zero. Unpriced is a metering gap: it charges
        nothing and is flagged, because silently charging nothing is how a
        metering bug survives a quarter.

        Rounding is floor, at the call, away from us — a sub-cent call costs
        zero rather than one. Rounding up would turn a chatty Visit into a
        rounding-fee product.
        """
        if usd is None:
            return cls(0, CostStatus.UNPRICED)
        d = usd if isinstance(usd, Decimal) else Decimal(str(usd))
        if d < 0:
            raise ValueError(f"a provider cost cannot be negative: {d}")
        credits = int((d * CREDIT_PER_USD).to_integral_value(rounding=ROUND_FLOOR))
        return cls(credits, CostStatus.PRICED)


@dataclass(frozen=True, slots=True)
class Balance:
    """A Candidate's Credit balance, and the rules that are true of it.

    A value, not a row: the ledger stores the integer and this says what may
    be concluded from it.
    """

    credits: int

    def debit(self, credits: int) -> "Balance":
        """Never clamps at zero and never raises on insufficient balance.

        The negative balance is the specified outcome: a Visit runs to
        completion on an exhausted balance, because a truncated Visit corrupts
        a permanent write while an overrun costs a few Credits.
        """
        if credits < 0:
            raise ValueError("a debit must be non-negative")
        return Balance(self.credits - credits)

    def refund(self, credits: int) -> "Balance":
        if credits < 0:
            raise ValueError("a refund must be non-negative")
        return Balance(self.credits + credits)

    def clears_headroom(self, headroom: int = HEADROOM_CREDITS) -> bool:
        return self.credits >= headroom
