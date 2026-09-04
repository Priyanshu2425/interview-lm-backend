# The API, and the surface it serves when they share an origin.
#
# **The build context is `backend/`, not the repository root**, so every path
# below is relative to this file's own directory:
#
#   docker build -t interview-lm backend/
#
# Nothing outside `backend/` is copied in, which is what lets the context be
# the narrower one: `data/` is imported into Postgres rather than mounted
# (SPEC-0006) and `docs/` is not the API's business.
#
# API only, and that follows from `frontend/` being its own git repository
# (ADR-0009): a clone of this one has no surface to build, so an image that
# insisted on building one could not be built at all.
#
# The surface is deployed separately and reaches this API cross-origin
# (ADR-0020). **This image serves no surface at all** — the mount went with that
# decision, and the `SURFACE_DIR` that configured it was read by nothing for
# some months afterwards while this comment went on describing what it did.
# Copying a `dist/` into an image that extends this one achieves nothing;
# put a reverse proxy in front instead, which is what production does.

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
# deployment needs no local model to serve or to embed — prefer
# EMBEDDING_PROVIDER=openrouter over carrying weights (ADR-0019).
#
# `boto3` is *not* part of that extra any more. The object store is on the
# upload path since ISSUE-0033 — a document is stored before its row is
# written — so a deployment with a bucket configured cannot answer an upload
# without it. It is in requirements.txt for that reason.
COPY requirements.txt ./
RUN pip install -r requirements.txt && pip install "uvicorn[standard]"

COPY pyproject.toml README.md ./backend/
COPY src ./backend/src
RUN pip install --no-deps -e ./backend

# No Corpus is copied in, and there is nothing to copy: every Corpus belongs to
# somebody and lives in Postgres (SPEC-0006). A boot needs no scrape, no model
# and no `data/` directory — material arrives by import, and
# `scripts/import_corpus.py` runs against a database rather than a mount.

# Not root. Nothing here writes to the image at runtime.
RUN useradd --create-home --uid 10001 cortex && chown -R cortex:cortex /app
USER cortex

ENV PORT=8000

EXPOSE 8000

# `PORT` because platforms assign one. One worker on purpose: the LangGraph
# checkpointer and the connection pool are per-process, and a free tier has
# neither the memory nor the traffic to want more.
CMD ["sh", "-c", "uvicorn interviewer.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
