"""``python -m switchboard_core.load`` — load the dataset into Postgres.

One transaction. Idempotent: run it twice and the database is identical.
"""

import logging
import sys

from switchboard_core.db.session import create_db_engine, session_factory
from switchboard_core.load.loaders import load_all


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

    for table, written in sorted(counts.items()):
        log.info("%-20s %6d rows", table, written)
    log.info("%-20s %6d rows total", "", sum(counts.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
