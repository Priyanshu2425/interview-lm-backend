"""The `core` schema — SPEC-0002 and SPEC-0005.

Two schemas with opposite lifecycles share one Postgres instance (ADR-0010):

  graph/  LangGraph's checkpointer tables. Disposable outside the resumption
          window. Created by the framework's own setup(), not by us.
  core/   Everything permanent. Ours, and never touched by a graph migration.

The invariants live here as constraints rather than as application logic,
because the MCP host is a ReAct agent we do not control and a constraint is the
only thing a prompt cannot talk its way past.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    Column,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP

CORE = "core"
GRAPH = "graph"

metadata = MetaData(schema=CORE)


def _ts(name: str, **kw) -> Column:
    return Column(name, TIMESTAMP(timezone=True), **kw)


grading_mode = Enum(
    "ground_truth", "text_grounded", "model_judgment",
    name="grading_mode", schema=CORE,
)
session_state = Enum("running", "parked", "ended", name="session_state", schema=CORE)
visit_state = Enum(
    "open", "answered", "graded", "abandoned", name="visit_state", schema=CORE
)
payment_route = Enum("credits", "byok", "mcp", name="payment_route", schema=CORE)
run_mode = Enum("managed", "mcp", name="run_mode", schema=CORE)
provider = Enum("deepseek", "gemini", "claude", name="provider", schema=CORE)
grader_kind = Enum(
    "server_judge", "judge_subagent", name="grader_kind", schema=CORE
)
cost_status = Enum("priced", "unpriced", name="cost_status", schema=CORE)
ledger_entry = Enum(
    "grant", "promo_grant", "debit", "refund", name="ledger_entry", schema=CORE
)
pool_entry = Enum("topup", "drawdown", name="pool_entry", schema=CORE)
call_outcome = Enum(
    "ok", "provider_error", "timeout", "rejected", name="call_outcome", schema=CORE
)
call_role = Enum(
    "interviewer", "question_writer", "judge", "other", name="call_role", schema=CORE
)


candidate = Table(
    "candidate", metadata,
    Column("candidate_id", String, primary_key=True),
    Column("display_name", String, nullable=True),
    _ts("created_at", nullable=False, server_default=sa.func.now()),
)

# ADR-0012: the provider's subject lives here and never on a permanent row.
identity = Table(
    "identity", metadata,
    Column("identity_id", String, primary_key=True),
    Column("candidate_id", String,
           ForeignKey(f"{CORE}.candidate.candidate_id"), nullable=False),
    Column("issuer", String, nullable=False),
    Column("subject", String, nullable=False),
    UniqueConstraint("issuer", "subject", name="uq_identity_issuer_subject"),
)

session = Table(
    "session", metadata,
    Column("session_id", String, primary_key=True),
    Column("candidate_id", String,
           ForeignKey(f"{CORE}.candidate.candidate_id"), nullable=False),
    Column("mode", run_mode, nullable=False),
    Column("payment_route", payment_route, nullable=False),
    Column("provider_chosen", provider, nullable=True),
    Column("scope_module_ids", ARRAY(String), nullable=False),
    Column("duration_seconds", Integer, nullable=False),
    Column("rubric_version", String, nullable=False),
    Column("state", session_state, nullable=False, server_default="running"),
    Column("parked_reason", String, nullable=True),
    Column("ended_reason", String, nullable=True),
    _ts("started_at", nullable=False, server_default=sa.func.now()),
    _ts("ended_at", nullable=True),
    CheckConstraint("duration_seconds > 0", name="ck_session_duration_positive"),
    CheckConstraint(
        "array_length(scope_module_ids, 1) >= 1", name="ck_session_scope_nonempty"
    ),
)

topic_visit = Table(
    "topic_visit", metadata,
    Column("topic_visit_id", String, primary_key=True),
    Column("session_id", String,
           ForeignKey(f"{CORE}.session.session_id"), nullable=False),
    Column("candidate_id", String, nullable=False),
    Column("topic_id", String, nullable=False),
    Column("visit_index", Integer, nullable=False),
    Column("state", visit_state, nullable=False, server_default="open"),
    Column("grading_mode", grading_mode, nullable=True),
    _ts("opened_at", nullable=False, server_default=sa.func.now()),
    _ts("answered_at", nullable=True),
    _ts("graded_at", nullable=True),
    Column("turn_count", Integer, nullable=False, server_default="0"),
    Column("exchange", JSONB, nullable=True),
    Column("grounding_ref", JSONB, nullable=True),
    # PRD-0003: no Topic is visited twice within one Session.
    UniqueConstraint("session_id", "topic_id", name="uq_visit_session_topic"),
    UniqueConstraint("session_id", "visit_index", name="uq_visit_session_index"),
    # A mode is recorded when the question is written and persisted at the
    # Answer Turn — so it must be present once a Visit has been answered or
    # graded. A Visit abandoned while still open never had one, and requiring
    # it there would make abandoning an open Visit impossible.
    CheckConstraint(
        "(state IN ('open', 'abandoned')) OR (grading_mode IS NOT NULL)",
        name="ck_visit_mode_once_answered",
    ),
)

# CONTEXT.md, MCP Mode invariant 1: "the Session will not advance while a Visit
# is unresolved". A partial unique index is what makes that a property of the
# store rather than a request to a ReAct agent.
Index(
    "uq_visit_one_open_per_session",
    topic_visit.c.session_id,
    unique=True,
    postgresql_where=text("state IN ('open','answered')"),
)

# ADR-0004, as a constraint: one Topic Visit produces one Evidence row.
evidence = Table(
    "evidence", metadata,
    Column("evidence_id", String, primary_key=True),
    Column("topic_visit_id", String,
           ForeignKey(f"{CORE}.topic_visit.topic_visit_id"),
           nullable=False, unique=True),
    Column("candidate_id", String, nullable=False),
    Column("topic_id", String, nullable=False),
    Column("session_id", String, nullable=False),
    Column("score", Numeric(4, 3), nullable=False),
    Column("grading_mode", grading_mode, nullable=False),
    Column("weight", Numeric(3, 2), nullable=False),
    Column("alpha_delta", Numeric(6, 4), nullable=False),
    Column("beta_delta", Numeric(6, 4), nullable=False),
    Column("grader_kind", grader_kind, nullable=False),
    Column("provider", provider, nullable=True),
    Column("rubric_version", String, nullable=False),
    Column("rationale", Text, nullable=False, server_default=""),
    Column("exchange_snapshot", JSONB, nullable=True),
    # Where the question came from, snapshotted at grading time: the spans that
    # grounded it, with their text and their locator (ISSUE-0025). Written here
    # rather than read back through content, so a citation still resolves after
    # the notebook that produced it is deleted (ISSUE-0027).
    Column("citations", JSONB, nullable=True),
    Column("topic_title_snapshot", String, nullable=False, server_default=""),
    Column("module_title_snapshot", String, nullable=False, server_default=""),
    _ts("created_at", nullable=False, server_default=sa.func.now()),
    CheckConstraint("score >= 0 AND score <= 1", name="ck_evidence_score_unit"),
    CheckConstraint("weight IN (1.00, 0.70, 0.50)", name="ck_evidence_weight_known"),
)

# The one mutable table in the system.
topic_confidence = Table(
    "topic_confidence", metadata,
    Column("candidate_id", String, primary_key=True),
    Column("topic_id", String, primary_key=True),
    Column("alpha", Numeric(10, 4), nullable=False, server_default="1.0"),
    Column("beta", Numeric(10, 4), nullable=False, server_default="1.0"),
    _ts("updated_at", nullable=False, server_default=sa.func.now()),
    # The uniform prior is the floor; nothing drives a posterior below it.
    CheckConstraint("alpha >= 1.0 AND beta >= 1.0", name="ck_confidence_prior_floor"),
)

call_record = Table(
    "call_record", metadata,
    Column("call_id", String, primary_key=True),
    Column("topic_visit_id", String, nullable=False),   # SPEC-0005 I1
    Column("session_id", String, nullable=False),
    Column("candidate_id", String, nullable=False),
    Column("role", call_role, nullable=False),
    Column("provider", provider, nullable=False),
    Column("model_id", String, nullable=False),
    Column("payment_route", payment_route, nullable=False),
    Column("reported_cost_usd", Numeric(12, 8), nullable=True),
    Column("cost_status", cost_status, nullable=False),
    Column("credits_charged", Integer, nullable=False, server_default="0"),
    Column("prompt_tokens", Integer, nullable=True),
    Column("completion_tokens", Integer, nullable=True),
    Column("latency_ms", Integer, nullable=False, server_default="0"),
    Column("outcome", call_outcome, nullable=False),
    _ts("created_at", nullable=False, server_default=sa.func.now()),
    CheckConstraint("credits_charged >= 0", name="ck_call_credits_nonneg"),
    CheckConstraint(
        "(cost_status = 'priced') OR (credits_charged = 0)",
        name="ck_unpriced_charges_nothing",
    ),
)

visit_provider_binding = Table(
    "visit_provider_binding", metadata,
    Column("topic_visit_id", String, primary_key=True),  # SPEC-0005 I2
    Column("provider", provider, nullable=False),
    Column("payment_route", payment_route, nullable=False),
    Column("byok_key_id", String, nullable=True),
    _ts("bound_at", nullable=False, server_default=sa.func.now()),
)

credit_ledger = Table(
    "credit_ledger", metadata,
    Column("id", String, primary_key=True),
    Column("candidate_id", String, nullable=False),
    Column("entry_type", ledger_entry, nullable=False),
    Column("delta_credits", Integer, nullable=False),
    Column("topic_visit_id", String, nullable=True),
    Column("session_id", String, nullable=True),
    Column("call_id", String, nullable=True),
    Column("refunded_visit_id", String, nullable=True),
    Column("payment_ref", String, nullable=True),
    Column("reason", String, nullable=True),
    _ts("created_at", nullable=False, server_default=sa.func.now()),
    CheckConstraint(
        "(entry_type <> 'debit') OR (call_id IS NOT NULL AND delta_credits <= 0)",
        name="ck_debit_has_call_and_is_negative",
    ),
    CheckConstraint(
        "(entry_type <> 'refund') OR "
        "(refunded_visit_id IS NOT NULL AND delta_credits >= 0)",
        name="ck_refund_has_visit_and_is_positive",
    ),
    CheckConstraint(
        "(entry_type <> 'grant') OR (payment_ref IS NOT NULL AND delta_credits > 0)",
        name="ck_grant_has_payment_ref",
    ),
)

# Idempotency is a constraint, not application logic (SPEC-0005 §2.1).
Index("uq_ledger_debit_call", credit_ledger.c.call_id, unique=True,
      postgresql_where=text("entry_type = 'debit'"))
Index("uq_ledger_refund_visit", credit_ledger.c.refunded_visit_id, unique=True,
      postgresql_where=text("entry_type = 'refund'"))
Index("uq_ledger_grant_payment", credit_ledger.c.payment_ref, unique=True,
      postgresql_where=text("entry_type = 'grant'"))

byok_key = Table(
    "byok_key", metadata,
    Column("key_id", String, primary_key=True),
    Column("candidate_id", String, nullable=False),
    Column("ciphertext", sa.LargeBinary, nullable=False),
    Column("wrapped_dek", sa.LargeBinary, nullable=False),
    Column("key_fingerprint", String, nullable=False),
    Column("status", String, nullable=False, server_default="active"),
    _ts("validated_at", nullable=True),
    Column("last_error", String, nullable=True),
    _ts("created_at", nullable=False, server_default=sa.func.now()),
    _ts("revoked_at", nullable=True),
)
Index("uq_byok_one_active_per_candidate", byok_key.c.candidate_id, unique=True,
      postgresql_where=text("status = 'active'"))

pool_ledger = Table(
    "pool_ledger", metadata,
    Column("id", String, primary_key=True),
    Column("entry_type", pool_entry, nullable=False),
    Column("delta_credits", Integer, nullable=False),
    Column("provider_reported_credits", Integer, nullable=True),  # ADR-0014
    Column("source_ref", String, nullable=False),
    _ts("created_at", nullable=False, server_default=sa.func.now()),
)


# ADR-0015. A notebook Topic may change shape; it may not change shape in
# silence. The event is permanent because it outlives the material it describes:
# deleting a notebook empties `content` and leaves this row standing.
corpus_version = Table(
    "corpus_version", metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),
    Column("notebook_id", String, nullable=False),
    Column("source_id", String, nullable=False),
    # re_ingested | embedding_model_changed
    Column("reason", String, nullable=False),
    Column("surviving_topic_ids", ARRAY(String), nullable=False),
    Column("new_topic_ids", ARRAY(String), nullable=False),
    Column("vanished_topic_ids", ARRAY(String), nullable=False),
    Column("note", Text, nullable=False, server_default=""),
    _ts("at", nullable=False, server_default=sa.func.now()),
)

Index("ix_corpus_version_notebook", corpus_version.c.notebook_id)


IMMUTABLE_SESSION_FIELDS_TRIGGER = f"""
-- PRD-0003 makes scope and duration immutable after start. A trigger is the
-- only place that survives a careless service method.
CREATE OR REPLACE FUNCTION {CORE}.reject_session_scope_change()
RETURNS trigger AS $$
BEGIN
  IF NEW.scope_module_ids IS DISTINCT FROM OLD.scope_module_ids THEN
    RAISE EXCEPTION 'session scope is immutable after start';
  END IF;
  IF NEW.duration_seconds IS DISTINCT FROM OLD.duration_seconds THEN
    RAISE EXCEPTION 'session duration is immutable after start';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_session_immutable ON {CORE}.session;
CREATE TRIGGER trg_session_immutable
  BEFORE UPDATE ON {CORE}.session
  FOR EACH ROW EXECUTE FUNCTION {CORE}.reject_session_scope_change();
"""

APPEND_ONLY_EVIDENCE_TRIGGER = f"""
-- PRD-0002 §33: append-only enforced by the store, not by convention. In
-- production the application role simply holds no UPDATE/DELETE grant; the
-- trigger makes the same guarantee true for the owning role used in tests.
CREATE OR REPLACE FUNCTION {CORE}.reject_evidence_mutation()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'evidence is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_evidence_append_only ON {CORE}.evidence;
CREATE TRIGGER trg_evidence_append_only
  BEFORE UPDATE OR DELETE ON {CORE}.evidence
  FOR EACH ROW EXECUTE FUNCTION {CORE}.reject_evidence_mutation();
"""
