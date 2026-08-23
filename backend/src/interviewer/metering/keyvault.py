"""BYOK Key Vault — envelope encryption (ADR-0013).

Each key is encrypted under its own data key; the data keys are wrapped by a
key-encryption key held in a KMS. Only this module can unwrap, and only the
Metered Model Client calls it.

Plaintext exists in this process and nowhere else: never logged, never in a call
record, never returned across an API boundary. ADR-0008 accepts OpenRouter keys
only — they carry their own spend cap and are revocable in isolation, so a
breach costs a capped credential rather than unbounded access to a Candidate's
accounts at Anthropic, Google or DeepSeek.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from typing import Protocol

import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.engine import Engine

from ..db import schema as S


class RejectedKey(ValueError):
    """Not an OpenRouter key, or OpenRouter refused it."""


class KeyManagementService(Protocol):
    """Wraps and unwraps data keys. In production this is a managed KMS; the
    key-encryption key never leaves it."""

    def wrap(self, dek: bytes) -> bytes: ...
    def unwrap(self, wrapped: bytes) -> bytes: ...


class LocalKms:
    """A stand-in for tests and local development.

    Deliberately not a production path: it holds the key-encryption key in
    process, which is exactly the single-secret failure ADR-0013 rejects.
    """

    def __init__(self, kek: bytes | None = None) -> None:
        self._f = Fernet(kek or Fernet.generate_key())

    def wrap(self, dek: bytes) -> bytes:
        return self._f.encrypt(dek)

    def unwrap(self, wrapped: bytes) -> bytes:
        return self._f.decrypt(wrapped)


class KeyValidator(Protocol):
    def validate(self, key: str) -> None:
        """Raise RejectedKey if OpenRouter will not accept it."""


class OpenRouterValidator:
    """A real call, so a well-formed dead key fails at attach rather than
    halfway through a Session."""

    def __init__(self, base_url: str = "https://openrouter.ai/api/v1") -> None:
        self._base = base_url

    def validate(self, key: str) -> None:
        import httpx

        try:
            r = httpx.get(
                f"{self._base}/key",
                headers={"Authorization": f"Bearer {key}"},
                timeout=15.0,
            )
        except httpx.HTTPError as e:
            raise RejectedKey("could not reach OpenRouter to check the key") from e
        if r.status_code in (401, 403):
            raise RejectedKey("OpenRouter refused this key")
        if r.status_code >= 400:
            raise RejectedKey("OpenRouter could not check this key")


class AcceptingValidator:
    def validate(self, key: str) -> None:  # pragma: no cover - test double
        return None


@dataclass(frozen=True, slots=True)
class AttachedKey:
    key_id: str
    fingerprint: str
    status: str


def fingerprint(key: str) -> str:
    """Non-reversible, for display and dedupe. Never the key itself."""
    digest = hashlib.sha256(key.encode()).hexdigest()
    return f"{digest[:4]}·{digest[4:8]}"


class KeyVault:
    def __init__(
        self, engine: Engine, kms: KeyManagementService, validator: KeyValidator
    ) -> None:
        self._e = engine
        self._kms = kms
        self._v = validator

    def attach(self, candidate_id: str, key: str) -> AttachedKey:
        # OpenRouter keys only. There is no branch that would take a raw vendor
        # credential, so the refusal is structural rather than a check.
        if not key.startswith("sk-or-"):
            raise RejectedKey(
                "only OpenRouter keys are accepted — they carry their own spend "
                "cap and can be revoked on their own"
            )
        self._v.validate(key)

        dek = Fernet.generate_key()
        ciphertext = Fernet(dek).encrypt(key.encode())
        wrapped = self._kms.wrap(dek)
        kid = f"key_{uuid.uuid4().hex[:22]}"

        with self._e.begin() as c:
            c.execute(
                sa.update(S.byok_key)
                .where(
                    S.byok_key.c.candidate_id == candidate_id,
                    S.byok_key.c.status == "active",
                )
                .values(status="revoked", revoked_at=sa.func.now())
            )
            c.execute(
                sa.insert(S.byok_key).values(
                    key_id=kid,
                    candidate_id=candidate_id,
                    ciphertext=ciphertext,
                    wrapped_dek=wrapped,
                    key_fingerprint=fingerprint(key),
                    status="active",
                    validated_at=sa.func.now(),
                )
            )
        return AttachedKey(kid, fingerprint(key), "active")

    def active(self, candidate_id: str) -> AttachedKey | None:
        """Metadata only. This is what an API boundary may see."""
        with self._e.connect() as c:
            r = c.execute(
                sa.select(
                    S.byok_key.c.key_id,
                    S.byok_key.c.key_fingerprint,
                    S.byok_key.c.status,
                ).where(
                    S.byok_key.c.candidate_id == candidate_id,
                    S.byok_key.c.status == "active",
                )
            ).first()
        return AttachedKey(*r) if r else None

    def revoke(self, candidate_id: str, key_id: str) -> bool:
        """Ciphertext is deleted; the fingerprint survives so history stays
        readable and the Candidate can see which key was removed.

        The owner is an argument rather than an option. A key id is opaque but
        it is not a secret — it comes back in the response that attached it and
        travels wherever that response goes — so scoping the update to the
        Candidate is what makes it theirs to revoke. Returns whether a row
        matched, so a route can answer "no such key of yours" without saying
        which of the two it was.
        """
        with self._e.begin() as c:
            result = c.execute(
                sa.update(S.byok_key)
                .where(
                    S.byok_key.c.key_id == key_id,
                    S.byok_key.c.candidate_id == candidate_id,
                )
                .values(status="revoked", ciphertext=b"", wrapped_dek=b"",
                        revoked_at=sa.func.now())
            )
        return result.rowcount > 0

    def rotate_kek(self, new_kms: KeyManagementService) -> int:
        """Re-wraps data keys without touching ciphertext, so rotation is
        routine rather than a migration."""
        n = 0
        with self._e.begin() as c:
            rows = c.execute(
                sa.select(S.byok_key.c.key_id, S.byok_key.c.wrapped_dek)
                .where(S.byok_key.c.status == "active")
            ).all()
            for kid, wrapped in rows:
                dek = self._kms.unwrap(bytes(wrapped))
                c.execute(
                    sa.update(S.byok_key)
                    .where(S.byok_key.c.key_id == kid)
                    .values(wrapped_dek=new_kms.wrap(dek))
                )
                n += 1
        self._kms = new_kms
        return n

    # -- the only path to plaintext ---------------------------------------

    def _resolve(self, candidate_id: str) -> str | None:
        with self._e.connect() as c:
            r = c.execute(
                sa.select(S.byok_key.c.ciphertext, S.byok_key.c.wrapped_dek).where(
                    S.byok_key.c.candidate_id == candidate_id,
                    S.byok_key.c.status == "active",
                )
            ).first()
        if not r:
            return None
        dek = self._kms.unwrap(bytes(r[1]))
        return Fernet(dek).decrypt(bytes(r[0])).decode()

    def resolver(self):
        """Handed only to the Metered Model Client — the same chokepoint that
        already makes an unmetered call impossible."""
        return self._resolve
