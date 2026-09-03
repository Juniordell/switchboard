"""The post-call worker: extract, then review.

    uv run python -m switchboard_api.async_agents.worker

Wakes on `switchboard_async_jobs`, which the queue's trigger announces on
commit, and falls back to a poll so a worker started after a call was queued
still picks it up. Both are needed: the notification is what makes it
prompt, the poll is what makes it correct.

Extract and review run in **one transaction per job**. A stored extraction
whose review never happened is the state that leaves a promise sitting in
nobody's queue, which is the failure this whole phase exists to prevent.
"""

import logging
import os
import signal
import sys

import psycopg

from switchboard_api.async_agents.extractor import extract
from switchboard_api.async_agents.model import ModelUnavailableError
from switchboard_api.async_agents.queue import claim, finish
from switchboard_api.async_agents.reviewer import review
from switchboard_core.db.session import create_db_engine, database_url, session_factory

CHANNEL = "switchboard_async_jobs"
POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", "5"))

logger = logging.getLogger("switchboard_api.worker")


def _psycopg_url() -> str:
    return database_url().replace("postgresql+psycopg://", "postgresql://", 1)


def run_one(sessions) -> bool:
    """Handle at most one job. Returns whether it found work."""
    with sessions() as session, session.begin():
        job = claim(session)
        if job is None:
            return False

        call_id = job["call_id"]
        try:
            facts = extract(session, call_id)
            verdict = review(session, call_id, facts)
            finish(session, job["id"])
            logger.info(
                "reviewed %s: confidence %.2f, queued=%s",
                call_id,
                float(verdict.get("confidence", 0)),
                verdict.get("queued"),
            )
        except (ModelUnavailableError, ValueError) as exc:
            # A transcript we cannot read or a model we cannot reach is a
            # reason to stop on this job, not to lose it: attempts is
            # already incremented and MAX_ATTEMPTS ends the retries.
            finish(session, job["id"], error=str(exc)[:500])
            logger.warning("job %s failed: %s", job["id"], exc)
    return True


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    engine = create_db_engine()
    sessions = session_factory(engine)

    running = True

    def stop(*_: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    listener = psycopg.connect(_psycopg_url(), autocommit=True)
    listener.execute(f"LISTEN {CHANNEL}")
    logger.info("worker up, listening on %s", CHANNEL)

    while running:
        # Drain first: a job queued before this worker started has no
        # notification waiting for it.
        while running and run_one(sessions):
            pass
        # Then wait to be told, with a timeout so the drain runs again.
        with listener.cursor():
            for _ in listener.notifies(timeout=POLL_SECONDS, stop_after=1):
                break

    listener.close()
    engine.dispose()
    logger.info("worker down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
