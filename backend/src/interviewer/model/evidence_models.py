"""The outcome of one Evidence write (ADR-0004).

`EvidenceLedger` stays in `repository/core/evidence.py`: it contains SQL.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["EvidenceWrite"]


@dataclass(frozen=True, slots=True)
class EvidenceWrite:
    evidence_id: str
    already_existed: bool
    posterior: Posterior
