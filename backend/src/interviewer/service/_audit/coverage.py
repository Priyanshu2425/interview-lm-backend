"""Which module and which test satisfies each user story.

This exists so "the stories are done" is checkable rather than asserted. A test
walks every story in every PRD and fails if one is unmapped, so the claim cannot
quietly rot as the PRDs change.

Format:  (prd, story_number) -> (module path, test node)
"""

from __future__ import annotations

# Compact spans keep this readable; expand() turns them into per-story rows.
_MAP: dict[str, list[tuple[str, str, str]]] = {
    # ---- PRD-0001: Corpus Adapter Contract and Dossier Loader -------------
    "0001": [
        ("1-2",   "service/corpus/loader_service.py",              "test_corpus_contract.py"),
        ("3",     "service/corpus/loader_service.py:approx_tokens","test_corpus_contract.py"),
        ("4",     "model/dossier_models.py:text_for_prompt","test_corpus_contract.py"),
        ("5",     "model/corpus_models.py:grading_mode_ceiling","test_corpus_contract.py"),
        ("6-7",   "model/corpus_models.py",            "test_corpus_contract.py"),
        ("8-9",   "service/judge/judge_service.py:_grounding",     "test_judge.py"),
        ("10",    "service/corpus/sources/interview_lm.py",     "test_corpus_contract.py"),
        ("11",    "service/corpus/conformance.py:validate","test_conformance.py"),
        ("12",    "service/corpus/conformance.py",         "test_conformance.py"),
        ("13",    "model/corpus_models.py:CorpusProvenance","test_conformance.py"),
        ("14",    "service/corpus/sources/interview_lm.py",     "test_corpus_contract.py"),
        ("15",    "service/corpus/conformance.py:diff_topics","test_conformance.py"),
        ("16-17", "service/corpus/conformance.py",         "test_conformance.py"),
        ("18",    "util/cli_utils.py",                 "test_conformance.py"),
        ("19-21", "model/corpus_models.py",            "test_conformance.py"),
        ("22",    "service/corpus/conformance.py:fixture_corpus","test_conformance.py"),
        ("23-24", "service/corpus/readings_service.py",             "test_corpus_api.py"),
        ("25-26", "routes/v1/skills_router.py",          "test_corpus_api.py"),
        ("27",    "service/corpus/readings_service.py:topic_ids_for","test_selection.py"),
        ("28",    "service/corpus/sources/interview_lm.py",     "test_architecture.py"),
        ("29",    "service/corpus/sources/markdown_folder.py","test_conformance.py"),
    ],
    # ---- PRD-0002: Evidence and Topic Confidence Tracker ------------------
    "0002": [
        ("1",     "model/confidence_models.py:Band",       "test_confidence.py"),
        ("2-3",   "model/readings_models.py",       "test_summary.py"),
        ("4-5",   "model/confidence_models.py:band",       "test_confidence.py"),
        ("6",     "service/confidence/summary_service.py:weakest", "test_weakest.py"),
        ("7",     "model/confidence_models.py:EvidenceDelta","test_confidence.py"),
        ("8",     "repository/core/evidence.py:EvidenceLedger","test_judge.py"),
        ("9",     "model/corpus_models.py:_WEIGHTS",   "test_confidence.py"),
        ("10-11", "db/schema.py:topic_confidence", "test_walking_skeleton.py"),
        ("12",    "service/graph/machine_service.py:next_planned_item","test_selection.py"),
        ("13-14", "service/confidence/selector_service.py",        "test_selection.py"),
        ("15-17", "service/graph/planner_service.py:SessionPlanner","test_walking_skeleton.py"),
        ("18",    "service/confidence/selector_service.py",        "test_selection.py"),
        ("19",    "repository/core/visits.py:VisitLifecycle","test_walking_skeleton.py"),
        ("20-21", "repository/core/evidence.py:EvidenceLedger","test_walking_skeleton.py"),
        ("22-23", "repository/core/visits.py:VisitLifecycle","test_resumption.py"),
        ("24-25", "repository/core/evidence.py:EvidenceLedger","test_judge.py"),
        ("26-28", "db/schema.py:evidence",         "test_judge.py"),
        ("29",    "service/judge/rejudge_service.py",              "test_rejudge.py"),
        ("30-31", "repository/core/confidence.py:ConfidenceStore","test_resumption.py"),
        ("32",    "repository/core/confidence.py",           "test_walking_skeleton.py"),
        ("33",    "db/schema.py:APPEND_ONLY_EVIDENCE_TRIGGER","test_walking_skeleton.py"),
        ("34",    "model/confidence_models.py:coverage",   "test_confidence.py"),
        ("35-36", "model/confidence_models.py:Posterior",  "test_confidence.py"),
        ("37",    "model/corpus_models.py:_WEIGHTS",   "test_confidence.py"),
        ("38",    "service/judge/rejudge_service.py",              "test_rejudge.py"),
    ],
    # ---- PRD-0003: Managed Mode Interview Loop -----------------------------
    "0003": [
        ("1-2",   "service/graph/sessions.py:SessionConfig","test_selection.py"),
        ("3",     "service/graph/machine_service.py:decide_next",  "test_walking_skeleton.py"),
        ("4",     "service/graph/machine_service.py:next_planned_item","test_selection.py"),
        ("5",     "service/judge/question_writer_service.py",      "test_judge.py"),
        ("6-9",   "service/judge/interviewer_service.py",          "test_agentic_region.py"),
        ("10",    "repository/core/evidence.py:EvidenceLedger","test_agentic_region.py"),
        ("11",    "service/judge/interviewer_service.py:_GIVE_UP", "test_agentic_region.py"),
        ("12-13", "repository/core/evidence.py:EvidenceLedger","test_judge.py"),
        ("14",    "service/graph/machine_service.py",              "test_api_sessions.py"),
        ("15-16", "service/graph/runner_service.py",               "test_resumption.py"),
        ("17",    "routes/v1/sessions_router.py:end",    "test_api_sessions.py"),
        ("18-19", "service/confidence/summary_service.py",         "test_summary.py"),
        ("20-21", "service/confidence/selector_service.py",        "test_selection.py"),
        ("22-23", "service/graph/machine_service.py",              "test_selection.py"),
        ("24-26", "service/judge/question_writer_service.py:_ground","test_judge.py"),
        ("27",    "service/graph/machine_service.py:record_exchange","test_judge.py"),
        ("28-29", "service/judge/interviewer_service.py",          "test_agentic_region.py"),
        ("30-33", "service/judge/judge_service.py",                "test_judge.py"),
        ("34",    "service/graph/machine_service.py",              "test_walking_skeleton.py"),
        ("35-37", "service/graph/machine_service.py:answer_turn",  "test_resumption.py"),
        ("38",    "service/graph/ports.py",                "test_resumption.py"),
        ("39",    "service/metering/client_service.py",            "test_metering_store.py"),
        ("40",    "db/schema.py:session",          "test_summary.py"),
        ("41",    "service/graph/runner_service.py",               "test_remaining_stories.py"),
        ("42",    "service/graph/machine_service.py",              "test_architecture.py"),
    ],
    # ---- PRD-0004: MCP Mode Server ----------------------------------------
    "0004": [
        ("1-2",   "mcp/mcp_server.py:start_session",   "test_mcp.py"),
        ("3",     "repository/core/confidence.py",           "test_mcp.py"),
        ("4",     "mcp/mcp_server.py:next_topic",      "test_mcp.py"),
        ("5",     "mcp/mcp_server.py:record_score",    "test_mcp.py"),
        ("6",     "mcp/mcp_server.py",                 "test_mcp.py"),
        ("7",     "mcp/mcp_server.py",                 "test_remaining_stories.py"),
        ("8",     "service/confidence/summary_service.py",         "test_remaining_stories.py"),
        ("9-11",  "mcp/mcp_server.py",                 "test_mcp.py"),
        ("12",    "mcp/mcp_server.py:next_topic",      "test_mcp.py"),
        ("13-14", "mcp/mcp_server.py:submit_answer",   "test_mcp.py"),
        ("15",    "mcp/mcp_server.py:VisitUnresolved", "test_mcp.py"),
        ("16",    "mcp/mcp_server.py:end_session",     "test_remaining_stories.py"),
        ("17",    "mcp/mcp_server.py:TOOL_DESCRIPTIONS","test_remaining_stories.py"),
        ("18-19", "mcp/mcp_server.py:redeem_grading_material","test_mcp.py"),
        ("20-21", "mcp/mcp_server.py:record_score",    "test_mcp.py"),
        ("22-24", "mcp/mcp_server.py",                 "test_mcp.py"),
        ("25-27", "mcp/mcp_server.py",                 "test_mcp.py"),
        ("28-30", "mcp/mcp_server.py:record_score",    "test_mcp.py"),
        ("31",    "repository/core/visits.py:VisitLifecycle","test_mcp.py"),
        ("32",    "db/schema.py:session",          "test_mcp.py"),
        ("33",    "mcp/mcp_server.py",                 "test_mcp.py"),
        ("34",    "mcp/mcp_server.py:record_grading_unreachable","test_remaining_stories.py"),
        ("35",    "mcp/mcp_server.py",                 "test_mcp.py"),
    ],
    # ---- PRD-0005: Credits, BYOK and Per-Visit Provider Metering ----------
    "0005": [
        ("1",     "service/metering/ledger.py:grant",      "test_metering_store.py"),
        ("2",     "model/credits_models.py",           "test_metering_pure.py"),
        ("3",     "service/graph/sessions.py:SessionConfig","test_api_sessions.py"),
        ("4-5",   "service/metering/operator_service.py:PriceService","test_remaining_stories.py"),
        ("6",     "service/metering/ledger.py:visit_cost", "test_credits_in_session.py"),
        ("7",     "routes/v1/sessions_router.py:spend",  "test_remaining_stories.py"),
        ("8",     "service/confidence/reading_service.py:SessionReadingService","test_judge.py"),
        ("9",     "routes/v1/candidate_router.py:credits","test_api_sessions.py"),
        ("10",    "service/graph/machine_service.py:decide_next",  "test_credits_in_session.py"),
        ("11",    "service/graph/machine_service.py:decide_next",  "test_credits_in_session.py"),
        ("12",    "service/graph/runner_service.py",               "test_credits_in_session.py"),
        ("13",    "service/metering/keyvault_service.py:attach",   "test_keyvault.py"),
        ("14",    "routes/v1/candidate_router.py",       "test_api_sessions.py"),
        ("15-16", "model/failures_models.py",          "test_metering_pure.py"),
        ("17",    "service/metering/keyvault_service.py",          "test_keyvault.py"),
        ("18",    "service/metering/keyvault_service.py:OpenRouterValidator","test_keyvault.py"),
        ("19",    "service/metering/keyvault_service.py:revoke",   "test_keyvault.py"),
        ("20",    "service/metering/keyvault_service.py",          "test_keyvault.py"),
        ("21",    "service/metering/client_service.py",            "test_metering_store.py"),
        ("22-23", "service/metering/ledger.py:refund_visit","test_metering_store.py"),
        ("24",    "mcp/mcp_server.py",                 "test_mcp.py"),
        ("25-26", "service/metering/client_service.py:BindingStore","test_metering_store.py"),
        ("27-28", "service/graph/runner_service.py:submit",        "test_remaining_stories.py"),
        ("29",    "service/graph/machine_service.py:decide_next",  "test_credits_in_session.py"),
        ("30",    "service/metering/client_service.py",            "test_credits_in_session.py"),
        ("31",    "service/metering/client_service.py",            "test_architecture.py"),
        ("32",    "service/metering/client_service.py:complete",   "test_metering_store.py"),
        ("33-34", "model/credits_models.py:of_usd","test_metering_store.py"),
        ("35",    "service/metering/ledger.py:debit",      "test_metering_store.py"),
        ("36",    "service/metering/ledger.py:grant",      "test_metering_store.py"),
        ("37",    "model/failures_models.py:UserFacingEvent", "test_metering_pure.py"),
        ("38",    "service/metering/ledger.py:prefunded_for","test_remaining_stories.py"),
        ("39-40", "service/metering/operator_service.py:pool",     "test_operator.py"),
        ("41",    "service/metering/ledger.py:promo_grant","test_metering_store.py"),
        ("42",    "service/metering/operator_service.py:by_provider","test_operator.py"),
        ("43",    "service/metering/operator_service.py:sessions", "test_operator.py"),
        ("44",    "service/metering/ledger.py:refund_visit","test_metering_store.py"),
        ("45",    "service/metering/operator_service.py",          "test_rejudge.py"),
        ("46",    "db/schema.py:call_record",      "test_metering_store.py"),
        ("47",    "service/metering/client_service.py",            "test_metering_store.py"),
    ],
}


def _span(s: str) -> list[int]:
    if "-" in s:
        a, b = s.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(s)]


def expand() -> dict[tuple[str, int], tuple[str, str]]:
    out: dict[tuple[str, int], tuple[str, str]] = {}
    for prd, rows in _MAP.items():
        for span, module, test in rows:
            for n in _span(span):
                out[(prd, n)] = (module, test)
    return out


COVERAGE = expand()
