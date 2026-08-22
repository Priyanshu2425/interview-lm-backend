# The API, and the surface it serves when they share an origin.
#
# API only, and that follows from `frontend/` being its own git repository
# (ADR-0009): a clone of this one has no surface to build, so an image that
# insisted on building one could not be built at all.
#
# The surface is deployed separately and reaches this API cross-origin
# (ADR-0020). For a single-origin deployment the API still mounts whatever
# `SURFACE_DIR` points at, so a built surface can be mounted in at run time or
# copied in by an image that extends this one:
#
#   FROM cortex-interviewer
#   COPY dist /app/frontend/dist

# --- the API ----------------------------------------------------------------
FROM python:3.12-slim AS api

# Bytecode written at build time rather than on every cold start, and stdout
# unbuffered so a platform's log tail is not a minute behind.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The runtime, pinned to the versions the test suite passes against —
# `backend/pyproject.toml` declares only what the Adapter cannot work without
# and leaves the rest to the deployment, and this is the deployment saying so.
# Copied before the source so a code change does not reinstall the world.
#
# The `embeddings` extra is deliberately absent: 2.5GB of wheels, and a
# deployment serving Related Topics needs no model at all — the index is a
# committed artifact (ADR-0018). Add it only where notebook ingest must be
# semantic, and prefer EMBEDDING_PROVIDER=openrouter over carrying weights.
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt && pip install "uvicorn[standard]"

COPY backend/pyproject.toml backend/README.md ./backend/
COPY backend/src ./backend/src
RUN pip install --no-deps -e ./backend

# No Corpus is copied in, and there is nothing to copy: every Corpus belongs to
# somebody and lives in Postgres (SPEC-0006). A boot needs no scrape, no model
# and no `data/` directory — material arrives by import, and
# `scripts/import_corpus.py` runs against a database rather than a mount.

# Not root. Nothing here writes to the image at runtime.
RUN useradd --create-home --uid 10001 cortex && chown -R cortex:cortex /app
USER cortex

ENV SURFACE_DIR=/app/frontend/dist \
    PORT=8000

# Absent by default, and `create_app` skips the mount rather than failing when
# the directory is not there.
RUN mkdir -p /app/frontend

EXPOSE 8000

# `PORT` because platforms assign one. One worker on purpose: the LangGraph
# checkpointer and the connection pool are per-process, and a free tier has
# neither the memory nor the traffic to want more.
CMD ["sh", "-c", "uvicorn interviewer.api.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
