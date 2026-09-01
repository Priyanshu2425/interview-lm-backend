"""The Metered Model Client — the single chokepoint (SPEC-0005 §3.2).

Every model call in the system goes through here: Interviewer, Question Writer,
Judge, and anything added later. Nothing else in the codebase may construct a
provider client, and a static check enforces that, because it is the kind of
rule that decays in exactly one careless import.

A call arriving without a topic_visit_id is rejected, not recorded
unattributed — metering, Evidence, provenance and refunds all key on the same
unit.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from ...db import schema as S
from ...service.graph.ports import ModelReply
from .credits import CostStatus, usd_to_credits
from .ledger import CreditLedger


@dataclass(frozen=True, slots=True)
class Binding:
    """Fixed for a Topic Visit's lifetime (SPEC-0005 I2)."""

    topic_visit_id: str
    provider: str
    payment_route: str
    byok_key_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    text: str
    model_id: str
    cost_usd: Decimal | None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ProviderTransport(Protocol):
    """The only thing allowed to speak to OpenRouter. Injected so the chokepoint
    stays testable without network."""

    def send(
        self, *, provider: str, api_key: str | None, system: str, user: str,
        max_tokens: int,
    ) -> ProviderResponse: ...


class ProviderFailure(RuntimeError):
    def __init__(self, cause: str, provider: str) -> None:
        super().__init__(f"{provider}: {cause}")
        self.cause = cause
        self.provider = provider


class MeteredModelClient:
    """Wraps a transport, records a Call Record for every attempt, and debits."""

    def __init__(
        self,
        engine: Engine,
        transport: ProviderTransport,
        ledger: CreditLedger,
        *,
        key_resolver=None,
    ) -> None:
        self._e = engine
        self._t = transport
        self._ledger = ledger
        self._keys = key_resolver
        self._binding: Binding | None = None
        self._session_id: str = ""
        self._candidate_id: str = ""

    def bind(self, binding: Binding, *, session_id: str, candidate_id: str) -> None:
        self._binding = binding
        self._session_id = session_id
        self._candidate_id = candidate_id

    def complete(
        self, *, topic_visit_id: str, role: str, system: str, user: str,
        max_tokens: int = 800,
    ) -> ModelReply:
        if not topic_visit_id:
            raise ValueError("a model call must carry a topic_visit_id")
        b = self._binding
        if b is None or b.topic_visit_id != topic_visit_id:
            raise ValueError(
                "no Provider is bound for this Topic Visit; bind() first"
            )

        api_key = None
        if b.payment_route == "byok":
            if self._keys is None:
                raise ValueError("a BYOK route needs a key resolver")
            api_key = self._keys(self._candidate_id)
            if not api_key:
                # Revoked between Visits. Named for what happened, so the
                # Candidate is not sent to look at our configuration.
                raise ProviderFailure("key_revoked", b.provider)

        call_id = f"call_{uuid.uuid4().hex[:22]}"
        started = time.perf_counter()
        try:
            resp = self._t.send(
                provider=b.provider, api_key=api_key, system=system,
                user=user, max_tokens=max_tokens,
            )
        except ProviderFailure:
            # A failed attempt that consumed tokens still cost money, so the
            # record is written either way.
            self._record(
                call_id=call_id, topic_visit_id=topic_visit_id, role=role,
                model_id="", cost=None, latency_ms=_ms(started), outcome="provider_error",
                prompt_tokens=None, completion_tokens=None,
            )
            raise

        cost = usd_to_credits(resp.cost_usd)
        self._record(
            call_id=call_id, topic_visit_id=topic_visit_id, role=role,
            model_id=resp.model_id, cost=(resp.cost_usd, cost),
            latency_ms=_ms(started), outcome="ok",
            prompt_tokens=resp.prompt_tokens, completion_tokens=resp.completion_tokens,
        )
        return ModelReply(
            text=resp.text, call_id=call_id, provider=b.provider,
            model_id=resp.model_id,
        )

    def _record(
        self, *, call_id: str, topic_visit_id: str, role: str, model_id: str,
        cost, latency_ms: int, outcome: str, prompt_tokens, completion_tokens,
    ) -> None:
        b = self._binding
        usd, c = (None, None) if cost is None else cost
        status = CostStatus.UNPRICED if c is None else c.status
        credits = 0 if c is None else c.credits
        # Credits meter our key only. Under BYOK the Candidate pays their
        # provider directly and spends none.
        charge = credits if b.payment_route == "credits" else 0

        with self._e.begin() as conn:
            conn.execute(sa.insert(S.call_record).values(
                call_id=call_id,
                topic_visit_id=topic_visit_id,
                session_id=self._session_id,
                candidate_id=self._candidate_id,
                role=role if role in ("interviewer", "question_writer", "judge")
                     else "other",
                provider=b.provider,
                model_id=model_id or "unknown",
                payment_route=b.payment_route,
                reported_cost_usd=usd,
                cost_status=status.value,
                credits_charged=charge,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                outcome=outcome,
            ))

        if charge > 0:
            self._ledger.debit(
                candidate_id=self._candidate_id, call_id=call_id,
                credits=charge, topic_visit_id=topic_visit_id,
                session_id=self._session_id,
            )


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


class BindingStore:
    """Write-once per Visit. A second binding is a constraint violation, not a
    branch (SPEC-0005 §2.3)."""

    def __init__(self, engine: Engine) -> None:
        self._e = engine

    def bind(self, b: Binding) -> Binding:
        with self._e.connect() as c:
            row = c.execute(
                sa.select(S.visit_provider_binding).where(
                    S.visit_provider_binding.c.topic_visit_id == b.topic_visit_id
                )
            ).first()
        if row:
            m = row._mapping
            return Binding(m["topic_visit_id"], m["provider"],
                           m["payment_route"], m["byok_key_id"])
        with self._e.begin() as c:
            c.execute(sa.insert(S.visit_provider_binding).values(
                topic_visit_id=b.topic_visit_id, provider=b.provider,
                payment_route=b.payment_route, byok_key_id=b.byok_key_id,
            ))
        return b

    def get(self, topic_visit_id: str) -> Binding | None:
        with self._e.connect() as c:
            row = c.execute(
                sa.select(S.visit_provider_binding).where(
                    S.visit_provider_binding.c.topic_visit_id == topic_visit_id
                )
            ).first()
        if not row:
            return None
        m = row._mapping
        return Binding(m["topic_visit_id"], m["provider"], m["payment_route"],
                       m["byok_key_id"])
