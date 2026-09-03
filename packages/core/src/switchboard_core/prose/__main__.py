"""``python -m switchboard_core.prose`` — fill every pending embedding.

Separate from ``python -m switchboard_core.load`` on purpose: this one costs
money and calls a live API, so it never runs silently as a side effect of an
ordinary reload. ``chunk_notes`` (free) is already part of ``load``; this
only does the paid half, and only for rows that don't have one yet.
"""

import logging
import sys

from switchboard_core.db.session import create_db_engine, session_factory
from switchboard_core.prose.embed_pending import embed_pending


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    log = logging.getLogger("switchboard_core.prose")

    engine = create_db_engine()
    with session_factory(engine)() as session:
        counts = embed_pending(session)

    for label, n in sorted(counts.items()):
        log.info("%-24s %6d", label, n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
