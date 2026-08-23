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


def _fernet_key(material: bytes) -> bytes:
    """A Fernet key from whatever the platform generated.

    Fernet wants url-safe base64 of exactly 32 bytes. A secret manager asked
    for "a random value" gives you a random value — Render's `generateValue`,
    a password manager, a line somebody typed — and none of those are that
    shape. Rejecting them would mean the operator has to know to run
    `Fernet.generate_key()`, and the failure for not knowing is a boot loop.

    So a key already of that shape is used as it is, and anything else is
    hashed to the right one. The mapping is fixed, so the same secret always
    produces the same key and a restart reads back what the last process wrote.
    """
    import base64
    import hashlib

    try:
        if len(base64.urlsafe_b64decode(material)) == 32:
            return material
    except Exception:
        pass
    return base64.urlsafe_b64encode(hashlib.sha256(material).digest())


class EphemeralKek(RuntimeError):
    """No key-encryption key is configured, and one was about to be invented."""


class LocalKms:
    """The key-encryption key, held in this process.

    Still not what ADR-0013 asks for — a managed KMS keeps the key-encryption
    key somewhere this process cannot read it, and this is a single secret in an
    environment variable. It is the difference between one failure and two,
    though, and the second one is the one that bites:

    A generated key is **per process**. Every BYOK key attached before a restart
    stays in the table and becomes permanently unreadable after it, because the
    key that wrapped its data key existed only in the memory of a process that
    has exited. The Candidate's row is there, the ciphertext is there, and
    nothing can decrypt it. On a host that restarts on idle — a free tier — that
    is every key, every day, and it fails at the moment somebody starts a
    Session rather than at the moment the key was attached.

    So a key is read from the environment, and generating one is something a
    deployment has to ask for. `rotate_kek` re-wraps without touching
    ciphertext, which is what makes changing this routine.
    """

    ENV = "BYOK_KEK"

    def __init__(self, kek: bytes | None = None, *, env: dict | None = None) -> None:
        import os

        env = os.environ if env is None else env
        material = kek or (env.get(self.ENV) or "").strip().encode() or None
        if material is None:
            if (env.get("BYOK_KEK_EPHEMERAL") or "") == "1":
                # Tests and a laptop, where nothing outlives the process anyway.
                material = Fernet.generate_key()
            else:
                raise EphemeralKek(
                    f"{self.ENV} is not set. A generated key lives in this "
                    "process only, so every BYOK key attached before the next "
                    "restart becomes permanently undecryptable — the row "
                    "survives and nothing can read it. Set it to a Fernet key "
                    "(`Fernet.generate_key()`), or set BYOK_KEK_EPHEMERAL=1 to "
                    "accept losing them at restart."
                )
        self._f = Fernet(_fernet_key(material))

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
