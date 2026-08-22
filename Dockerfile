# The API, and the surface it serves when they share an origin.
#
# Two stages. The first builds the React surface; the second runs Python and
# copies the build in. Splitting them keeps Node out of the running image —
# 300MB of node_modules that exist only to produce a directory of static files.
#
# The surface is built here *and* can be hosted separately (ADR-0020). Both work:
# with ALLOWED_ORIGINS unset the API serves the copy baked in below, and with it
# set the API serves its routes while a CDN serves the surface. Building it
# either way costs one stage and means the image is never useless on its own.

# --- the surface ------------------------------------------------------------
FROM node:22-alpine AS surface
WORKDIR /surface

# `frontend/` is its own git repository, so a build context that includes it is
# a deliberate act (see .dockerignore). If it is absent the stage still
# succeeds and produces nothing, and the API simply has no surface to mount.
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Baked in at build time, so a surface always knows which API it was built
# against. Empty means same-origin, which is what this image does by default.
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

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

# The Corpus and its precomputed index. Both are read-only at runtime and both
# ship with the image, which is what lets a boot need neither a scrape nor a
# model (ADR-0005, ADR-0018).
COPY data ./data
COPY --from=surface /surface/dist ./frontend/dist

# Not root. Nothing here writes to the image at runtime.
RUN useradd --create-home --uid 10001 cortex && chown -R cortex:cortex /app
USER cortex

ENV CORPUS_PATH=/app/data/corpus.json \
    CORPUS_INDEX_PATH=/app/data/corpus-index.json \
    SURFACE_DIR=/app/frontend/dist \
    PORT=8000

EXPOSE 8000

# `PORT` because platforms assign one. One worker on purpose: the LangGraph
# checkpointer and the connection pool are per-process, and a free tier has
# neither the memory nor the traffic to want more.
CMD ["sh", "-c", "uvicorn interviewer.api.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
