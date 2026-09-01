"""ISSUE-0011 — identity, and the indirection that makes it swappable."""

import sqlalchemy as sa

from interviewer.db import schema as S
from interviewer.service.identity.store import IdentityStore


def test_a_candidate_id_is_ours_and_is_not_the_provider_subject(clean_db):
    s = IdentityStore(clean_db)
    p = s.resolve(issuer="https://accounts.google.com", subject="10422")
    assert p.candidate_id.startswith("cand_")
    assert "10422" not in p.candidate_id


def test_the_same_subject_resolves_to_the_same_candidate(clean_db):
    s = IdentityStore(clean_db)
    a = s.resolve(issuer="iss", subject="sub-1")
    b = s.resolve(issuer="iss", subject="sub-1")
    assert a.candidate_id == b.candidate_id


def test_no_permanent_table_references_a_provider_subject(clean_db):
    """The property that makes changing identity provider survivable."""
    permanent = (
        S.evidence, S.topic_confidence, S.topic_visit, S.session,
        S.credit_ledger, S.call_record, S.byok_key,
    )
    for table in permanent:
        cols = set(table.c.keys())
        assert "subject" not in cols and "issuer" not in cols, table.name
        assert not {c for c in cols if "email" in c or "oidc" in c}, table.name


def test_one_candidate_may_hold_several_identities(clean_db):
    s = IdentityStore(clean_db)
    p = s.resolve(issuer="google", subject="g1")
    s.link(candidate_id=p.candidate_id, issuer="github", subject="gh1")
    assert len(s.identities(p.candidate_id)) == 2
    assert s.resolve(issuer="github", subject="gh1").candidate_id == p.candidate_id


def test_merging_repoints_identities_and_leaves_permanent_rows_untouched(
    clean_db, deps
):
    from interviewer.service.graph.runner import SessionRunner
    from interviewer.service.graph.sessions import SessionConfig

    s = IdentityStore(clean_db)
    keep = s.resolve(issuer="iss", subject="primary").candidate_id
    absorb = s.resolve(issuer="iss", subject="secondary").candidate_id

    mods = [m.module_id for m in deps.corpus.modules("aiml")][:1]
    r = SessionRunner(deps)
    sid, _ = r.start(candidate_id=absorb,
                     cfg=SessionConfig(scope_module_ids=tuple(mods),
                                       duration_seconds=1800))
    r.submit(sid, "an answer")

    before = deps.evidence.rows_for(absorb)
    assert before

    n = s.merge(keep=keep, absorb=absorb)
    assert n == 1
    assert len(s.identities(keep)) == 2
    # the permanent record is byte-identical: merging is an identity operation
    assert deps.evidence.rows_for(absorb) == before


def test_swapping_the_provider_leaves_every_permanent_row_untouched(clean_db, deps):
    from interviewer.service.graph.runner import SessionRunner
    from interviewer.service.graph.sessions import SessionConfig

    s = IdentityStore(clean_db)
    cid = s.resolve(issuer="old-idp", subject="u1").candidate_id
    mods = [m.module_id for m in deps.corpus.modules("aiml")][:1]
    r = SessionRunner(deps)
    sid, _ = r.start(candidate_id=cid,
                     cfg=SessionConfig(scope_module_ids=tuple(mods),
                                       duration_seconds=1800))
    r.submit(sid, "answer")
    snapshot = deps.confidence.all_for(cid)

    # the whole migration: point a new issuer's subject at the same Candidate
    s.link(candidate_id=cid, issuer="new-idp", subject="u1-new")
    assert s.resolve(issuer="new-idp", subject="u1-new").candidate_id == cid
    assert deps.confidence.all_for(cid) == snapshot


def test_a_subject_is_unique_per_issuer(clean_db):
    s = IdentityStore(clean_db)
    s.resolve(issuer="iss", subject="dup")
    import pytest
    with pytest.raises(Exception) as e:
        s.link(candidate_id="cand_other", issuer="iss", subject="dup")
    assert "uq_identity_issuer_subject" in str(e.value)


def test_a_candidate_keeps_their_balance_and_key_across_a_provider_change(clean_db):
    from interviewer.service.metering.keyvault import AcceptingValidator, KeyVault, LocalKms
    from interviewer.service.metering.ledger import CreditLedger

    s = IdentityStore(clean_db)
    cid = s.resolve(issuer="old", subject="x").candidate_id
    CreditLedger(clean_db).grant(cid, 4180, "p")
    vault = KeyVault(clean_db, LocalKms(), AcceptingValidator())
    vault.attach(cid, "sk-or-v1-" + "b" * 32)

    s.link(candidate_id=cid, issuer="new", subject="x2")
    assert CreditLedger(clean_db).balance(cid) == 4180
    assert vault.active(cid) is not None
