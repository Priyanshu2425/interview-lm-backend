"""ISSUE-0010 — key custody.

The security properties are asserted on the stored bytes and on what crosses a
boundary, not on the code being written carefully.
"""

import logging

import pytest
import sqlalchemy as sa

from interviewer.db import schema as S
from interviewer.service.metering.keyvault import (
    AcceptingValidator, KeyVault, LocalKms, RejectedKey,
)

KEY = "sk-or-v1-0123456789abcdef0123456789abcdef"
CAND = "cand_vault"


@pytest.fixture()
def vault(clean_db):
    return KeyVault(clean_db, LocalKms(), AcceptingValidator())


def test_only_openrouter_keys_are_accepted(vault):
    for bad in ("sk-ant-api03-xxx", "AIzaSyXXXX", "sk-proj-xxx", "hunter2"):
        with pytest.raises(RejectedKey, match="OpenRouter"):
            vault.attach(CAND, bad)


def test_a_key_openrouter_refuses_fails_at_attach_not_mid_session(clean_db):
    class Refusing:
        def validate(self, key):
            raise RejectedKey("OpenRouter refused this key")

    v = KeyVault(clean_db, LocalKms(), Refusing())
    with pytest.raises(RejectedKey):
        v.attach(CAND, KEY)
    assert v.active(CAND) is None


def test_the_stored_bytes_do_not_contain_the_key(vault, clean_db):
    vault.attach(CAND, KEY)
    with clean_db.connect() as c:
        row = c.execute(sa.select(S.byok_key)).first()._mapping
    blob = bytes(row["ciphertext"]) + bytes(row["wrapped_dek"])
    assert KEY.encode() not in blob
    assert b"sk-or-" not in blob


def test_a_database_dump_alone_does_not_yield_plaintext(vault, clean_db):
    """The key-encryption key never appears in the table."""
    vault.attach(CAND, KEY)
    with clean_db.connect() as c:
        row = c.execute(sa.select(S.byok_key)).first()._mapping
    from cryptography.fernet import Fernet, InvalidToken

    with pytest.raises((InvalidToken, Exception)):
        Fernet(bytes(row["wrapped_dek"])).decrypt(bytes(row["ciphertext"]))


def test_only_the_vault_can_resolve_plaintext(vault):
    vault.attach(CAND, KEY)
    assert vault.resolver()(CAND) == KEY
    # the public surface returns metadata only
    meta = vault.active(CAND)
    assert meta.fingerprint and KEY not in str(meta)
    assert not hasattr(meta, "key")


def test_the_key_never_appears_in_a_log(vault, caplog):
    with caplog.at_level(logging.DEBUG):
        vault.attach(CAND, KEY)
        vault.resolver()(CAND)
    assert KEY not in caplog.text
    assert "sk-or-" not in caplog.text


def test_the_key_never_appears_in_a_call_record(clean_db):
    from decimal import Decimal

    from interviewer.service.metering.client import Binding, MeteredModelClient
    from interviewer.service.metering.ledger import CreditLedger
    from interviewer.service.metering.transport import ScriptedTransport

    v = KeyVault(clean_db, LocalKms(), AcceptingValidator())
    v.attach(CAND, KEY)
    c = MeteredModelClient(clean_db, ScriptedTransport(cost_usd=Decimal("0.01")),
                           CreditLedger(clean_db), key_resolver=v.resolver())
    c.bind(Binding("v1", "deepseek", "byok"), session_id="s1", candidate_id=CAND)
    c.complete(topic_visit_id="v1", role="judge", system="s", user="u")

    with clean_db.connect() as conn:
        row = conn.execute(sa.select(S.call_record)).first()._mapping
    assert KEY not in str(dict(row))


def test_rotating_the_key_encryption_key_leaves_ciphertext_untouched(vault, clean_db):
    vault.attach(CAND, KEY)
    with clean_db.connect() as c:
        before = bytes(c.execute(sa.select(S.byok_key.c.ciphertext)).scalar())

    n = vault.rotate_kek(LocalKms())
    assert n == 1

    with clean_db.connect() as c:
        after = bytes(c.execute(sa.select(S.byok_key.c.ciphertext)).scalar())
    assert before == after
    assert vault.resolver()(CAND) == KEY      # still usable


def test_revoking_deletes_ciphertext_and_keeps_the_fingerprint(vault, clean_db):
    attached = vault.attach(CAND, KEY)
    vault.revoke(CAND, attached.key_id)

    with clean_db.connect() as c:
        row = c.execute(sa.select(S.byok_key)).first()._mapping
    assert bytes(row["ciphertext"]) == b""
    assert row["key_fingerprint"] == attached.fingerprint
    assert row["status"] == "revoked"
    assert vault.active(CAND) is None


def test_removing_a_key_falls_back_to_credits_without_touching_the_record(
    vault, clean_db
):
    from interviewer.service.metering.ledger import CreditLedger

    ledger = CreditLedger(clean_db)
    ledger.grant(CAND, 5000, "p")
    a = vault.attach(CAND, KEY)
    vault.revoke(CAND, a.key_id)
    assert ledger.balance(CAND) == 5000


def test_attaching_a_second_key_revokes_the_first(vault):
    a = vault.attach(CAND, KEY)
    b = vault.attach(CAND, KEY.replace("0123", "9999"))
    assert vault.active(CAND).key_id == b.key_id
    assert a.key_id != b.key_id


def test_only_one_active_key_per_candidate_is_possible(clean_db, vault):
    vault.attach(CAND, KEY)
    with pytest.raises(Exception) as e:
        with clean_db.begin() as c:
            c.execute(sa.insert(S.byok_key).values(
                key_id="k2", candidate_id=CAND, ciphertext=b"x",
                wrapped_dek=b"y", key_fingerprint="ff", status="active",
            ))
    assert "uq_byok_one_active_per_candidate" in str(e.value)


def test_grading_never_moves_to_the_client():
    """A Candidate who produces their own score can mint their own Mastery."""
    from interviewer.service.judge import judge as judge_mod

    src = (judge_mod.__file__)
    text = open(src).read()
    assert "class Judge" in text
    # the Judge takes a ModelClient it is given; it has no client-side path
    assert "requests" not in text and "httpx" not in text


def test_a_key_is_revocable_only_by_the_candidate_holding_it(vault, clean_db):
    """A key id is opaque and is not a secret: it comes back in the response
    that attached it and travels wherever that response goes."""
    mine = vault.attach(CAND, KEY)
    assert vault.revoke("cand_somebody_else", mine.key_id) is False
    assert vault.active(CAND) is not None
    assert vault.revoke(CAND, mine.key_id) is True
    assert vault.active(CAND) is None


# --- the key-encryption key outlives the process ----------------------------

def test_a_key_attached_before_a_restart_is_readable_after_one():
    """The defect this closes: a generated key lived in one process, so every
    row it wrapped stayed in the table and became permanently unreadable."""
    from interviewer.service.metering.keyvault import LocalKms

    secret = {"BYOK_KEK": "a3f9c2b18e7d4a6f9c0b5e2d8a1f7c34"}
    before = LocalKms(env=secret)
    wrapped = before.wrap(b"a data key")

    after = LocalKms(env=secret)          # a new process, same secret
    assert after.unwrap(wrapped) == b"a data key"


def test_a_different_secret_cannot_read_it():
    from interviewer.service.metering.keyvault import LocalKms

    wrapped = LocalKms(env={"BYOK_KEK": "one"}).wrap(b"a data key")
    with pytest.raises(Exception):
        LocalKms(env={"BYOK_KEK": "another"}).unwrap(wrapped)


def test_generating_a_key_is_something_a_deployment_has_to_ask_for():
    """Silently inventing one is what made the keys unreadable."""
    from interviewer.service.metering.keyvault import EphemeralKek, LocalKms

    with pytest.raises(EphemeralKek, match="BYOK_KEK"):
        LocalKms(env={})
    assert LocalKms(env={"BYOK_KEK_EPHEMERAL": "1"}) is not None


def test_whatever_the_platform_generated_is_a_usable_key():
    """Fernet wants base64 of 32 bytes; a secret manager gives you a random
    value. Refusing it would make not knowing that a boot loop."""
    from cryptography.fernet import Fernet

    from interviewer.service.metering.keyvault import LocalKms

    for secret in (Fernet.generate_key().decode(), "x" * 40, "correct horse battery staple"):
        a, b = LocalKms(env={"BYOK_KEK": secret}), LocalKms(env={"BYOK_KEK": secret})
        assert b.unwrap(a.wrap(b"k")) == b"k"
