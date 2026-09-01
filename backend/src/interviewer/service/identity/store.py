"""Candidate identity (ADR-0012).

`candidate_id` is issued by us, is opaque, and appears in no token. The identity
provider's subject lives on a separate row that points at a Candidate.

The argument is the same one ADR-0007 makes for `topic_id`: identity is the join
key for everything permanent — 71 posteriors per Candidate, every Evidence row
with its stored exchange, every ledger entry — so it may not be borrowed from a
system whose shape we do not control.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from ...db import schema as S


@dataclass(frozen=True, slots=True)
class Principal:
    candidate_id: str
    issuer: str
    subject: str


class IdentityStore:
    def __init__(self, engine: Engine) -> None:
        self._e = engine

    def resolve(self, *, issuer: str, subject: str) -> Principal:
        """Find or create the Candidate behind an authenticated subject."""
        with self._e.connect() as c:
            row = c.execute(
                sa.select(S.identity.c.candidate_id).where(
                    S.identity.c.issuer == issuer,
                    S.identity.c.subject == subject,
                )
            ).first()
        if row:
            return Principal(row[0], issuer, subject)

        cid = f"cand_{uuid.uuid4().hex[:22]}"
        with self._e.begin() as c:
            c.execute(sa.insert(S.candidate).values(candidate_id=cid))
            c.execute(sa.insert(S.identity).values(
                identity_id=f"idn_{uuid.uuid4().hex[:22]}",
                candidate_id=cid, issuer=issuer, subject=subject,
            ))
        return Principal(cid, issuer, subject)

    def link(self, *, candidate_id: str, issuer: str, subject: str) -> None:
        """One Candidate may hold several identities."""
        with self._e.begin() as c:
            c.execute(sa.insert(S.identity).values(
                identity_id=f"idn_{uuid.uuid4().hex[:22]}",
                candidate_id=candidate_id, issuer=issuer, subject=subject,
            ))

    def identities(self, candidate_id: str) -> list[dict]:
        with self._e.connect() as c:
            return [
                {"issuer": r[0], "subject": r[1]}
                for r in c.execute(
                    sa.select(S.identity.c.issuer, S.identity.c.subject)
                    .where(S.identity.c.candidate_id == candidate_id)
                ).all()
            ]

    def merge(self, *, keep: str, absorb: str) -> int:
        """Repoints identity rows and leaves every permanent row untouched.

        This works only because nothing permanent references the subject — which
        is the whole reason for the indirection.
        """
        with self._e.begin() as c:
            n = c.execute(
                sa.update(S.identity)
                .where(S.identity.c.candidate_id == absorb)
                .values(candidate_id=keep)
            ).rowcount
        return n
