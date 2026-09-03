"""``python -m switchboard_core.load`` — load the dataset into Postgres.

One transaction: the source tables, every Knowledge-layer build step, then
`chunk_notes` - the free half of Prose. Idempotent: run it twice and the
database is identical. Does **not** call `embed_pending`: that costs money
and calls a live API, so it stays a separate, explicit
``python -m switchboard_core.prose`` run - see that module's docstring.
"""

import logging
import sys

from switchboard_core.db.session import create_db_engine, session_factory
from switchboard_core.knowledge import build_all as build_knowledge
from switchboard_core.load.loaders import load_all
from switchboard_core.prose import chunk_notes


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    log = logging.getLogger("switchboard_core.load")

    engine = create_db_engine()
    with session_factory(engine)() as session, session.begin():
        counts = load_all(session)
        counts.update(build_knowledge(session))
        counts.update(chunk_notes(session))

    for table, written in sorted(counts.items()):
        log.info("%-30s %6d rows", table, written)
    log.info("%-30s %6d rows total", "", sum(counts.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
