"""`python -m interviewer.corpus.cli <corpus.json>` — validate locally.

The contract stated as something an Adapter author can run without the system.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .adapters.cortex import AdapterError, ingest
from .conformance import validate


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m interviewer.corpus.cli <corpus.json>")
        return 2
    try:
        corpus = ingest(Path(argv[1]))
    except AdapterError as e:
        print(f"ingest failed: {e}")
        return 1
    except Exception as e:  # pydantic validation, etc.
        print(f"contract violated: {e}")
        return 1

    report = validate(corpus)
    print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
