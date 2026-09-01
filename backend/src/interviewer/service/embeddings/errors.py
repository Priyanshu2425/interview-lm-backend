"""What an embedder is allowed to fail with.

A small, closed set, because the API renders failure copy from the code rather
than composing it on the client (AGENTS.md). A provider that invents its own
exception type reaches the Candidate as a 500 with no message worth reading.
"""

from __future__ import annotations


class EmbeddingError(Exception):
    """Base for everything in this package. Carries the code the API renders."""

    code = "embedding_failed"

    def __init__(self, message: str, *, provider: str = "", model: str = "") -> None:
        self.provider = provider
        self.model = model
        super().__init__(message)


class EmbeddingUnavailable(EmbeddingError):
    """The provider could not be reached, or would not answer.

    Transient by assumption: ingest is refused whole and can be retried, which
    is the same shape as a parked Session rather than a lost one.
    """

    code = "embedding_unavailable"


class EmbeddingTimeout(EmbeddingUnavailable):
    """A batch outlived its deadline. A hung provider parks ingest, not the process."""

    code = "embedding_timeout"


class EmbeddingContractError(EmbeddingError):
    """The provider answered, and the answer was not what it promised.

    Wrong width, wrong count, or a vector carrying NaN. Never retried — a model
    that changed its default dimension will change it again on the next call —
    and never stored, because a poisoned centroid freezes into a Topic and is
    close to undiagnosable months later.
    """

    code = "embedding_contract"


class UnsupportedModality(EmbeddingError):
    """Asked for images from a text-only embedder."""

    code = "embedding_unsupported_modality"


class PaidProviderRefused(EmbeddingError):
    """A billed provider was selected while ADR-0016 is unsigned.

    Who pays for a BYOK Candidate's ingest is an open product decision. Until it
    is made, a provider that would charge is refused at boot rather than
    discovered by a Candidate at the moment they upload their notes.
    """

    code = "embedding_paid_provider_refused"
