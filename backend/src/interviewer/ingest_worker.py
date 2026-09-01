"""Ingest runs in this process, in a thread, while the surface polls.

SPEC-0000 refuses Redis and a message queue outright, and embedding a 200-page
PDF takes roughly forty seconds — long enough that a Candidate cannot be held on
a request, short enough that no infrastructure should be introduced for it. So
the work runs here and the poll drives the progress readout.

**No worker survives a restart**, which is what makes a killed one detectable
without a timeout: any Source still marked `ingesting` when the process starts is
stale by definition (see `reset_stale`).
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)

#: Why a Source that was mid-ingest when the process died reads as failed. Not a
#: guess about how long is too long — a statement about what is knowable.
RESTART_REASON = (
    "the ingest was interrupted when the server restarted. Nothing partial was "
    "written; retry to run it again."
)


def start(notebook_id: str, source_id: str, *, route: str = "credits") -> None:
    """Claim the Source and embed it, off the request.

    Failures are recorded on the Source and logged here rather than raised: the
    caller has already been answered, and a background thread has nobody to
    raise at.
    """
    threading.Thread(
        target=_run,
        args=(notebook_id, source_id, route),
        name=f"ingest:{source_id}",
        daemon=True,
    ).start()


def _run(notebook_id: str, source_id: str, route: str) -> None:
    from .deps import get_notebook_service, refresh_corpus

    try:
        get_notebook_service().ingest_source(
            notebook_id, source_id, route=route,
            # Rebuilt *before* the Source reads `ready`, because `ready` is what
            # the Library shows as examinable — and a Candidate who starts a
            # Session the moment the progress bar fills must not be told their
            # Module holds no examinable Topic.
            before_ready=refresh_corpus,
        )
    except Exception:
        # Already written to the Source as a `failed` state with its reason;
        # this is for whoever is reading the process log.
        log.warning("ingest failed for %s", source_id, exc_info=True)


def reset_stale() -> int:
    """Mark every Source left `ingesting` by a dead process as failed.

    Called at startup. The worker runs in-process, so nothing that was running
    is still running: this needs no timeout and invents none.
    """
    from .deps import get_notebook_service

    reset = get_notebook_service().store.reset_stale_ingests(RESTART_REASON)
    if reset:
        log.warning("reset %s interrupted ingest(s) to failed", reset)
    return reset
