"""Sync-to-Async Adapters for LangGraph nodes.

LangGraph nodes run synchronously but need to call async service methods.
This adapter runs async coroutines in a dedicated thread pool with an event loop.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from interviewer.config import config


class SyncToAsyncAdapter:
    """Runs async service methods from sync LangGraph nodes via thread pool."""

    def __init__(self, async_services: Any) -> None:
        self._async = async_services
        self._executor = ThreadPoolExecutor(max_workers=config.graph_bridge.workers)
        self._loop = asyncio.new_event_loop()
        self._timeout = config.graph_bridge.timeout
        # Start the event loop in a background thread
        self._loop_thread = None
        self._start_loop()

    def _start_loop(self) -> None:
        """Start the event loop in a background thread."""
        def run_loop():
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        import threading
        self._loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._loop_thread.start()

    def _run_async(self, coro) -> Any:
        """Run async coroutine in thread pool, return result synchronously."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=self._timeout)

    def shutdown(self) -> None:
        """Shutdown the adapter."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread:
            self._loop_thread.join(timeout=5)
        self._executor.shutdown(wait=True)

    # --- SessionStore sync wrappers ---
    def sessions_ensure_candidate(self, candidate_id: str, name: str | None = None) -> str:
        return self._run_async(self._async.sessions.ensure_candidate(candidate_id, name))

    def sessions_create(self, candidate_id: str, cfg: Any) -> str:
        return self._run_async(self._async.sessions.create(candidate_id, cfg))

    def sessions_get(self, session_id: str) -> dict | None:
        return self._run_async(self._async.sessions.get(session_id))

    def sessions_park(self, session_id: str, reason: str) -> None:
        self._run_async(self._async.sessions.park(session_id, reason))

    def sessions_resume(self, session_id: str) -> None:
        self._run_async(self._async.sessions.resume(session_id))

    def sessions_end(self, session_id: str, reason: str) -> None:
        self._run_async(self._async.sessions.end(session_id, reason))

    # --- VisitLifecycle sync wrappers ---
    def visits_open(
        self, *, session_id: str, candidate_id: str, topic_id: str, visit_index: int
    ) -> str:
        return self._run_async(
            self._async.visits.open(
                session_id=session_id,
                candidate_id=candidate_id,
                topic_id=topic_id,
                visit_index=visit_index,
            )
        )

    def visits_record_answer(
        self,
        topic_visit_id: str,
        *,
        exchange: dict,
        turn_count: int,
        mode: Any,
        grounding_ref: dict | None = None,
    ) -> None:
        self._run_async(
            self._async.visits.record_answer(
                topic_visit_id, exchange=exchange, turn_count=turn_count, mode=mode, grounding_ref=grounding_ref
            )
        )

    def visits_get(self, topic_visit_id: str) -> dict | None:
        return self._run_async(self._async.visits.get(topic_visit_id))

    def visits_unresolved(self, session_id: str) -> dict | None:
        return self._run_async(self._async.visits.unresolved(session_id))

    def visits_open_topic_ids(self) -> set[str]:
        return self._run_async(self._async.visits.open_topic_ids())

    def visits_visited_topic_ids(self, session_id: str) -> set[str]:
        return self._run_async(self._async.visits.visited_topic_ids(session_id))

    def visits_for_session(self, session_id: str) -> list[dict]:
        return self._run_async(self._async.visits.for_session(session_id))

    def visits_abandon(self, topic_visit_id: str) -> None:
        self._run_async(self._async.visits.abandon(topic_visit_id))

    # --- EvidenceLedger sync wrappers ---
    def evidence_write(self, **kwargs) -> Any:
        return self._run_async(self._async.evidence.write(**kwargs))

    def evidence_rejudgeable(self, *, limit: int = 500, mode: str | None = None) -> list[dict]:
        return self._run_async(self._async.evidence.rejudgeable(limit=limit, mode=mode))

    def evidence_for_session(self, session_id: str) -> list[dict]:
        return self._run_async(self._async.evidence.for_session(session_id))

    def evidence_rows_for(self, candidate_id: str) -> list[dict]:
        return self._run_async(self._async.evidence.rows_for(candidate_id))

    # --- ConfidenceStore sync wrappers ---
    def confidence_get(self, candidate_id: str, topic_id: str) -> Any:
        return self._run_async(self._async.confidence.get(candidate_id, topic_id))

    def confidence_get_many(self, candidate_id: str, topic_ids: list[str]) -> dict[str, Any]:
        return self._run_async(self._async.confidence.get_many(candidate_id, topic_ids))

    def confidence_all_on_topic(self, topic_id: str) -> dict[str, Any]:
        return self._run_async(self._async.confidence.all_on_topic(topic_id))

    def confidence_examined_counts(self, topic_ids: list[str]) -> dict[str, int]:
        return self._run_async(self._async.confidence.examined_counts(topic_ids))

    def confidence_all_for(self, candidate_id: str) -> dict[str, Any]:
        return self._run_async(self._async.confidence.all_for(candidate_id))

    # --- BindingStore sync wrappers ---
    def bindings_bind(self, binding: Any) -> Any:
        return self._run_async(self._async.bindings.bind(binding))

    def bindings_get(self, topic_visit_id: str) -> Any | None:
        return self._run_async(self._async.bindings.get(topic_visit_id))

    # --- CreditLedger sync wrappers ---
    def credits_balance(self, candidate_id: str) -> int:
        return self._run_async(self._async.credits.balance(candidate_id))

    def credits_debit(self, **kwargs) -> None:
        self._run_async(self._async.credits.debit(**kwargs))

    def credits_grant(self, **kwargs) -> None:
        self._run_async(self._async.credits.grant(**kwargs))

    def credits_refund(self, **kwargs) -> None:
        self._run_async(self._async.credits.refund(**kwargs))

    def credits_visit_cost(self, topic_visit_id: str) -> int:
        return self._run_async(self._async.credits.visit_cost(topic_visit_id))

    # --- KeyVault sync wrappers ---
    def keyvault_active(self, candidate_id: str) -> dict | None:
        return self._run_async(self._async.keyvault.active(candidate_id))

    def keyvault_resolver(self, candidate_id: str) -> str | None:
        return self._run_async(self._async.keyvault.resolver(candidate_id))

    # --- CorpusService sync wrappers ---
    def corpus_topic_ids_for(self, module_ids: list[str]) -> list[str]:
        return self._run_async(self._async.corpus.topic_ids_for(module_ids))

    # --- NotebookStore sync wrappers ---
    def notebooks_source_by_hash(self, notebook_id: str, content_hash: str) -> str | None:
        return self._run_async(self._async.notebooks.source_by_hash(notebook_id, content_hash))

    def notebooks_next_source_order(self, notebook_id: str) -> int:
        return self._run_async(self._async.notebooks.next_source_order(notebook_id))

    def notebooks_create_source(self, **kwargs) -> None:
        self._run_async(self._async.notebooks.create_source(**kwargs))

    def notebooks_begin_ingest(self, source_id: str) -> bool:
        return self._run_async(self._async.notebooks.begin_ingest(source_id))

    def notebooks_record_progress(self, source_id: str, *, done: int, total: int) -> None:
        self._run_async(self._async.notebooks.record_progress(source_id, done=done, total=total))

    def notebooks_fail_ingest(self, source_id: str, reason: str) -> None:
        self._run_async(self._async.notebooks.fail_ingest(source_id, reason))

    def notebooks_finish_ingest(self, **kwargs) -> None:
        self._run_async(self._async.notebooks.finish_ingest(**kwargs))

    def notebooks_mark_ready(self, source_id: str) -> None:
        self._run_async(self._async.notebooks.mark_ready(source_id))

    def notebooks_frozen_topics(self, notebook_id: str) -> dict[str, Any]:
        return self._run_async(self._async.notebooks.frozen_topics(notebook_id))

    def notebooks_chunks_of(self, notebook_id: str, *, modality: str | None = None) -> list[dict]:
        return self._run_async(self._async.notebooks.chunks_of(notebook_id, modality=modality))

    def notebooks_embeddings_by_hash(self, notebook_id: str, *, embedding_model: str | None = None) -> dict[str, tuple]:
        return self._run_async(self._async.notebooks.embeddings_by_hash(notebook_id, embedding_model=embedding_model))