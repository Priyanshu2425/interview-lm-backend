"""Work done against work found, while the work is happening.

Embedding a 200-page PDF takes roughly forty seconds and SPEC-0000 refuses Redis
and a message queue outright, so the work runs in-process and the surface polls.
What the surface must never be shown is an indeterminate spinner: forty seconds
of spinner is indistinguishable from a hang, and the difference is the only
thing the Candidate actually wants to know.

So the embedder is wrapped rather than the pipeline instrumented. It is the one
place that knows how much has been embedded, it already receives every chunk of
a Source in one call, and wrapping it means the progress reading cannot drift
from the work — there is no second counter to keep in step.
"""

from __future__ import annotations

from typing import Callable, Sequence

#: How many chunks are embedded between two progress reports. Small enough that
#: a long ingest moves visibly, large enough that the reporting is not itself
#: the cost — each report is one small UPDATE.
BATCH = 16


class ProgressEmbedder:
    """An Embedder that says how far through it is.

    Delegates everything it is not measuring, including `embed_images` and the
    model identity, so nothing downstream can tell it is here.
    """

    __slots__ = ("_inner", "_report", "_done", "_batch")

    def __init__(
        self,
        inner,
        report: Callable[[int, int], None],
        *,
        batch: int = BATCH,
    ) -> None:
        self._inner = inner
        self._report = report
        self._done = 0
        self._batch = max(1, batch)

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        texts = list(texts)
        total = self._done + len(texts)
        out: list[tuple[float, ...]] = []
        for start in range(0, len(texts), self._batch):
            out.extend(self._inner.embed(texts[start:start + self._batch]))
            self._done = min(total, self._done + self._batch)
            self._report(self._done, total)
        if not texts:
            self._report(self._done, total)
        return out

    def __getattr__(self, name: str):
        return getattr(self._inner, name)
