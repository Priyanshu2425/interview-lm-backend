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

CORE = "interview_lm_core"
GRAPH = "interview_lm_graph"

metadata = MetaData(schema=CORE)


def _ts(name: str, **kw) -> Column:
    return Column(name, TIMESTAMP(timezone=True), **kw)


grading_mode = Enum(
    "ground_truth", "text_grounded", "model_judgment",
    name="grading_mode", schema=CORE,
)
session_state = Enum("running", "parked", "ended", name="session_state", schema=CORE)
# `graded` still exists, and since ISSUE-0042 the managed loop never writes it:
# a question ends at `answered` and the Session is graded once, at the end
# (ISSUE-0044). MCP Mode grades per Visit and writes it today, which is why it
# is still here.
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

# ISSUE-0039. The plan is fixed before the first question, so its vocabulary is
# a type rather than a string: a breadth nobody can misspell, an item state that
# distinguishes "never reached" from "asked", and a transcript whose role and
# kind are closed sets.
plan_breadth = Enum("full", "compressed", name="plan_breadth", schema=CORE)
plan_item_state = Enum(
    "planned", "asked", "unreached", name="plan_item_state", schema=CORE
)
message_role = Enum("interviewer", "candidate", name="message_role", schema=CORE)
message_kind = Enum(
    "question", "answer", "probe", "hint", name="message_kind", schema=CORE
)


# ISSUE-0048. What a Candidate tells us about themselves, and nothing more.
# ADR-0026 keeps the credential and the address at Gatehouse; these four are
# answers to a form, defaulted so a row that predates the form reads as
# *unanswered* rather than as unknown.
#
# `target_role`, `experience_level` and `goal` are **read by nothing yet**, and
# that is deliberate rather than an oversight: the form is the only moment a
# person will answer, and the calibration that would consume them is later work.
# Said here so they are not mistaken for dead columns and deleted.
candidate = Table(
    "candidate", metadata,
    Column("candidate_id", String, primary_key=True),
    Column("display_name", String, nullable=True),
    # Null means never completed. A timestamp rather than a boolean because the
    # permanent record should say *when*, as the rest of `core` does — and
    # because "onboarded" is derived from it, so there is one fact and not two
    # that can disagree.
    _ts("onboarded_at", nullable=True),
    Column("target_role", String, nullable=False, server_default=""),
    Column("experience_level", String, nullable=False, server_default=""),
    Column("goal", String, nullable=False, server_default=""),
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
    # ISSUE-0039 deferred retiring this to "the slice that replaces its
    # writers". ISSUE-0042 replaced one of them: the managed loop writes
    # `message` and nothing else. It did not replace the other. MCP Mode still
    # records an exchange here and grades that blob against a redemption
    # ticket, so this column has a live writer and a live reader and stays
    # until MCP Mode is moved onto the transcript.
    Column("exchange", JSONB, nullable=True),
    Column("grounding_ref", JSONB, nullable=True),
    # ISSUE-0039. A row is now the *question*, not the Topic Visit: it may span
    # up to three Topics, and it belongs to the plan item that scheduled it.
    # `topic_id` stays as the owning Topic, because `open_topic_ids()` and the
    # refund path both need a scalar.
    Column("topic_ids", ARRAY(String), nullable=True),
    Column("plan_item_id", String, nullable=True),
    # `uq_visit_session_topic` was here, and ISSUE-0039 removed it: a plan may
    # deliberately spend two questions on one Topic. What it protected — one
    # Beta observation per Topic per Session — moved to `uq_evidence_session_topic`,
    # which is where ADR-0004 actually lives now.
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
#
# ISSUE-0042 narrowed the predicate from `state IN ('open','answered')` to
# `state = 'open'`, and the narrowing *is* the slice. Grading no longer follows
# answering inside the loop — it happens once, at the end, against the
# transcript — so `answered` stopped meaning "waiting on a grade before the
# Session may move" and started meaning "this question is finished". What the
# index still refuses is the thing it was always about: two questions open at
# once in one Session. MCP Mode grades per Visit and still refuses to advance
# past an `answered` one; it enforces that in `McpServer` through
# `visits.unresolved`, which is unchanged.
Index(
    "uq_visit_one_open_per_session",
    topic_visit.c.session_id,
    unique=True,
    postgresql_where=text("state = 'open'"),
)

# ADR-0004, restated by ISSUE-0039: the unit of Evidence is the Topic within a
# Session, not the Topic Visit. One Beta observation per Topic per Session —
# exactly as before — but an observation may now be assembled from several
# questions, and one spanning question may contribute to several observations.
evidence = Table(
    "evidence", metadata,
    Column("evidence_id", String, primary_key=True),
    # Nullable and non-unique since ISSUE-0039. Grading happens at the end of a
    # Session against a transcript, so an Evidence row need not descend from any
    # single question, and several may descend from the same one.
    Column("topic_visit_id", String,
           ForeignKey(f"{CORE}.topic_visit.topic_visit_id"),
           nullable=True),
    Column("candidate_id", String, nullable=False),
    Column("topic_id", String, nullable=False),
    Column("session_id", String, nullable=False),
    # `score` stays the stated combination; the two dimensions it combines are
    # recorded beside it (ISSUE-0043). Nullable because a Verdict written before
    # the Judge read two dimensions has neither.
    Column("score", Numeric(4, 3), nullable=False),
    Column("source_score", Numeric(4, 3), nullable=True),
    Column("truth_score", Numeric(4, 3), nullable=True),
    # Reporting only. It is never a Beta count — the observation is one,
    # however many questions were spent reaching it.
    Column("question_count", Integer, nullable=False, server_default="0"),
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
    # This constraint *is* ADR-0004: one Beta observation per Topic per Session.
    UniqueConstraint("session_id", "topic_id", name="uq_evidence_session_topic"),
    CheckConstraint("score >= 0 AND score <= 1", name="ck_evidence_score_unit"),
    CheckConstraint(
        "source_score IS NULL OR (source_score >= 0 AND source_score <= 1)",
        name="ck_evidence_source_score_unit",
    ),
    CheckConstraint(
        "truth_score IS NULL OR (truth_score >= 0 AND truth_score <= 1)",
        name="ck_evidence_truth_score_unit",
    ),
    CheckConstraint("question_count >= 0", name="ck_evidence_question_count_nonneg"),
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


# --- ISSUE-0039: the plan, and the transcript it is executed against --------
#
# The Session stops being a sequence of independently graded Topic Visits. A
# plan is fixed before the first question; the questions are asked against it;
# the transcript is graded once at the end. Fixing the plan up front is what
# removes the loop's dependency on a freshly updated posterior, and that is what
# lets grading move to the end at all.

session_plan = Table(
    "session_plan", metadata,
    Column("session_id", String,
           ForeignKey(f"{CORE}.session.session_id"), primary_key=True),
    Column("budget_questions", Integer, nullable=False),
    # What the scope suggested, and what the Candidate actually chose. Both are
    # kept: a plan built for forty minutes and run in twenty is a different
    # reading of the same scope, and the report has to be able to say so.
    Column("suggested_seconds", Integer, nullable=False),
    Column("chosen_seconds", Integer, nullable=False),
    Column("breadth", plan_breadth, nullable=False),
    # Which planner produced this, and whether it had to fall back. A plan built
    # by the deterministic fallback is still a plan; it is not the same claim.
    Column("planner_provider", String, nullable=True),
    Column("planner_fallback", sa.Boolean, nullable=False, server_default="false"),
    _ts("planned_at", nullable=False, server_default=sa.func.now()),
    CheckConstraint("budget_questions > 0", name="ck_plan_budget_positive"),
    CheckConstraint("suggested_seconds > 0", name="ck_plan_suggested_positive"),
    CheckConstraint("chosen_seconds > 0", name="ck_plan_chosen_positive"),
)

plan_item = Table(
    "plan_item", metadata,
    Column("plan_item_id", String, primary_key=True),
    Column("session_id", String,
           ForeignKey(f"{CORE}.session.session_id"), nullable=False),
    Column("item_order", Integer, nullable=False),
    # One to three Topics. A question spanning more than three stops being a
    # question about anything.
    Column("topic_ids", ARRAY(String), nullable=False),
    Column("focus", Text, nullable=False, server_default=""),
    Column("state", plan_item_state, nullable=False, server_default="planned"),
    _ts("created_at", nullable=False, server_default=sa.func.now()),
    UniqueConstraint("session_id", "item_order", name="uq_plan_item_session_order"),
    CheckConstraint(
        "array_length(topic_ids, 1) BETWEEN 1 AND 3",
        name="ck_plan_item_topic_span",
    ),
    CheckConstraint("item_order >= 0", name="ck_plan_item_order_nonneg"),
)

Index("ix_plan_item_session", plan_item.c.session_id)

# The transcript. `topic_visit.exchange` was a blob owned by one question;
# this is the Session's own record, in order, and it is the one writer.
message = Table(
    "message", metadata,
    Column("message_id", String, primary_key=True),
    Column("session_id", String,
           ForeignKey(f"{CORE}.session.session_id"), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("role", message_role, nullable=False),
    Column("kind", message_kind, nullable=False),
    Column("topic_ids", ARRAY(String), nullable=True),
    Column("text", Text, nullable=False),
    Column("topic_visit_id", String, nullable=True),
    Column("plan_item_id", String, nullable=True),
    _ts("created_at", nullable=False, server_default=sa.func.now()),
    UniqueConstraint("session_id", "seq", name="uq_message_session_seq"),
    CheckConstraint("seq >= 0", name="ck_message_seq_nonneg"),
)

Index("ix_message_session_seq", message.c.session_id, message.c.seq)


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


PLAN_ITEM_FIXED_TRIGGER = f"""
-- ISSUE-0039. The plan is fixed before the first question, and fixedness is a
-- constraint rather than a convention — the same argument `trg_session_immutable`
-- already makes about scope and duration. `state` still moves, because whether an
-- item was reached is a fact about the run, not about the plan.
CREATE OR REPLACE FUNCTION {CORE}.reject_plan_item_change()
RETURNS trigger AS $$
BEGIN
  IF NEW.topic_ids IS DISTINCT FROM OLD.topic_ids THEN
    RAISE EXCEPTION 'plan item topics are fixed once planned';
  END IF;
  IF NEW.item_order IS DISTINCT FROM OLD.item_order THEN
    RAISE EXCEPTION 'plan item order is fixed once planned';
  END IF;
  IF NEW.focus IS DISTINCT FROM OLD.focus THEN
    RAISE EXCEPTION 'plan item focus is fixed once planned';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_plan_item_fixed ON {CORE}.plan_item;
CREATE TRIGGER trg_plan_item_fixed
  BEFORE UPDATE ON {CORE}.plan_item
  FOR EACH ROW EXECUTE FUNCTION {CORE}.reject_plan_item_change();
"""

APPEND_ONLY_MESSAGE_TRIGGER = f"""
-- The transcript is what the Session is graded against, so it is append-only for
-- the same reason Evidence is: a record that can be edited after the fact grades
-- something that never happened.
CREATE OR REPLACE FUNCTION {CORE}.reject_message_mutation()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'message is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_message_append_only ON {CORE}.message;
CREATE TRIGGER trg_message_append_only
  BEFORE UPDATE OR DELETE ON {CORE}.message
  FOR EACH ROW EXECUTE FUNCTION {CORE}.reject_message_mutation();
"""

def statements(ddl: str) -> list[str]:
    """Split a DDL blob into single commands, respecting `$$` bodies.

    psycopg sends a multi-command string happily; asyncpg prepares every
    statement and refuses one — "cannot insert multiple commands into a prepared
    statement". Splitting on `;` naively would cut each trigger function in half,
    because the function body is full of them. So the dollar-quoted region is
    tracked and semicolons inside it are left alone.
    """
    out: list[str] = []
    current: list[str] = []
    in_body = False
    for line in ddl.splitlines():
        if line.count("$$") % 2 == 1:
            in_body = not in_body
        current.append(line)
        if not in_body and line.rstrip().endswith(";"):
            chunk = "\n".join(current).strip()
            if chunk:
                out.append(chunk)
            current = []
    tail = "\n".join(current).strip()
    if tail:
        out.append(tail)
    return out


#: Every trigger `core` depends on. Named once so that both engines apply the
#: same set — `create_async_tables` used to apply none of them (ISSUE-0039).
CORE_TRIGGERS = (
    IMMUTABLE_SESSION_FIELDS_TRIGGER,
    APPEND_ONLY_EVIDENCE_TRIGGER,
    PLAN_ITEM_FIXED_TRIGGER,
    APPEND_ONLY_MESSAGE_TRIGGER,
)
