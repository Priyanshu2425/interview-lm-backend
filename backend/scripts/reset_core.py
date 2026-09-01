#!/usr/bin/env python
"""Drop and rebuild the `core` schema. Destructive, and hard to run by accident.

ISSUE-0039 breaks the schema: the Session becomes a plan executed against a
transcript and graded once at the end, and `create_all` cannot get there from
here because it never ALTERs. This is the break.

It destroys Evidence. Evidence is append-only precisely because it is not meant
to be destroyable, so this script asks twice, in two different ways, and refuses
unless both agree:

    INTERVIEWER_ALLOW_DESTRUCTIVE_RESET=1 \\
        python backend/scripts/reset_core.py --confirm-host 127.0.0.1

The environment variable is the intent. The echoed host is the *target* — the
thing people actually get wrong. A script that only asked "are you sure" would
be answered "yes" by someone certain about the wrong database, which is the
failure it exists to prevent. Guessing the host is not possible from muscle
memory: it has to be read off the DSN in front of you.

A destructive script that is easy to run by accident is the same defect as no
guard at all.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

ALLOW_VAR = "INTERVIEWER_ALLOW_DESTRUCTIVE_RESET"


def host_of(url: str) -> str:
    """The host this DSN names, or `local` for a socket connection."""
    import sqlalchemy as sa

    return sa.engine.make_url(url).host or "local"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-host",
        default=None,
        help="the host of the database to reset, echoed back exactly",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="recreate the core tree after dropping it (usually what you want)",
    )
    args = parser.parse_args()

    from interviewer.db.engine import create_core, dsn, make_engine
    from interviewer.db.schema import CORE

    url = dsn()
    host = host_of(url)

    if os.environ.get(ALLOW_VAR) != "1":
        print(
            f"refusing: {ALLOW_VAR} is not set to 1.\n"
            f"This drops schema {CORE} on {host}, Evidence included.",
            file=sys.stderr,
        )
        return 2

    if args.confirm_host != host:
        got = args.confirm_host if args.confirm_host is not None else "nothing"
        print(
            f"refusing: --confirm-host must name the target database's host.\n"
            f"  DATABASE_URL points at: {host}\n"
            f"  --confirm-host said:    {got}",
            file=sys.stderr,
        )
        return 2

    engine = make_engine()
    import sqlalchemy as sa

    with engine.begin() as c:
        counts = {}
        for table in ("evidence", "session", "topic_visit"):
            present = c.execute(
                sa.text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = :s AND table_name = :t"
                ),
                {"s": CORE, "t": table},
            ).scalar()
            if present:
                counts[table] = c.execute(
                    sa.text(f"SELECT count(*) FROM {CORE}.{table}")
                ).scalar()
    if counts:
        print("dropping, with: " + ", ".join(f"{v} {k}" for k, v in counts.items()))

    with engine.begin() as c:
        c.execute(sa.text(f"DROP SCHEMA IF EXISTS {CORE} CASCADE"))
    print(f"dropped {CORE} on {host}")

    if args.rebuild:
        create_core(engine)
        print(f"rebuilt {CORE} on {host}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
