#!/usr/bin/env python
"""Regenerate backend/requirements.txt from the environment the tests pass in.

`pyproject.toml` declares only the dependencies the Notebook Adapter cannot
work without, and says outright that the rest of the runtime is the
deployment's business. This is the deployment's business, written down: the
image installs exactly what 840 passing tests ran against.

Runtime only. The test dependencies are pinned separately in
`requirements-dev.txt`, because a test runner carried by every container for
the life of the deployment is a cost paid forever for a command nobody runs
there.

Run it after changing a dependency, and commit the result — an unpinned build
is a build that changes without a commit, and the first sign of that is
production behaving differently from the machine the tests ran on.
"""

from __future__ import annotations

import importlib.metadata as md
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "requirements.txt"

#: What the API imports at runtime, directly or through something it imports.
#: Deliberately a list rather than `pip freeze`: the local environment also
#: carries pytest, torch and the whole embeddings extra, none of which belong in
#: an image that serves precomputed Related Topics.
RUNTIME = [
    "fastapi", "uvicorn", "starlette",
    "sqlalchemy", "psycopg", "psycopg-binary", "psycopg-pool", "pgvector",
    "langgraph", "langgraph-checkpoint", "langgraph-checkpoint-postgres",
    "langchain-core",
    "pydantic", "pydantic-core", "httpx", "cryptography", "tenacity",
    "numpy", "scipy", "pypdf", "python-multipart",
    # The object store is on the upload path since ISSUE-0033, so this is
    # runtime rather than part of the `embeddings` extra it predates. It was
    # once hand-written into requirements.txt and absent from this list, which
    # meant the documented regeneration command silently removed it — and the
    # symptom is an upload refused in production, nowhere near the change.
    "boto3", "botocore",
    # Verifying a Gatehouse token (ADR-0026).
    "pyjwt",
]

HEADER = """\
# Generated from the environment the test suite passes in.
# Regenerate with: python backend/scripts/pin_requirements.py
#
# Pinned because an unpinned build is a build that changes without a
# commit, and the first sign of it is production behaving differently
# from the machine the tests ran on.
"""


def main() -> int:
    lines = [HEADER.rstrip()]
    missing = []
    for name in RUNTIME:
        try:
            lines.append(f"{name}=={md.version(name)}")
        except md.PackageNotFoundError:
            missing.append(name)
            lines.append(f"# {name}: not installed locally, left to resolve")
    TARGET.write_text("\n".join(lines) + "\n")
    print(f"wrote {TARGET.relative_to(TARGET.parents[1])} "
          f"({len(RUNTIME) - len(missing)} pinned)")
    if missing:
        print("not installed locally:", ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
