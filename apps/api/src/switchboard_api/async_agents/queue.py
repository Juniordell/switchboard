"""The queue between a call ending and the agents that read it.

A table, not a broker. Postgres is already here, already announces rows, and
the entire async workload is one job per phone call - adding a queue service
for that would be infrastructure nobody needs and one more thing to deploy.

`claim` uses `FOR UPDATE SKIP LOCKED`, so two workers never take the same
call and neither waits on the other.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

EXTRACT = "extract"

#: A job that has failed this many times stops being retried. An Extractor
#: that cannot parse one transcript must not consume the queue forever.
MAX_ATTEMPTS = 3


def enqueue(session: Session, call_id: str, kind: str = EXTRACT) -> str:
    """Queue one call. Idempotent per (call_id, kind) while still queued, so
    a session that ends twice does not extract twice."""
    existing = session.execute(
        text(
            "SELECT id FROM ops.async_jobs WHERE call_id = :c AND kind = :k "
            "AND status IN ('queued', 'running')"
        ),
        {"c": call_id, "k": kind},
    ).scalar_one_or_none()
    if existing:
        return existing

    job_id = f"job_{uuid.uuid4().hex}"
    session.execute(
        text(
            "INSERT INTO ops.async_jobs (id, call_id, kind, status) "
            "VALUES (:id, :c, :k, 'queued')"
        ),
        {"id": job_id, "c": call_id, "k": kind},
    )
    return job_id


def claim(session: Session) -> dict | None:
    """Take the oldest queued job, or nothing.

    SKIP LOCKED rather than a lock column: the database already knows how
    to hand one row to one worker, and a status column pretending to be a
    lock is the version of this that races.
    """
    row = (
        session.execute(
            text(
                """
            SELECT id, call_id, kind, attempts FROM ops.async_jobs
            WHERE status = 'queued' AND attempts < :max
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
            ),
            {"max": MAX_ATTEMPTS},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None

    session.execute(
        text(
            "UPDATE ops.async_jobs SET status = 'running', attempts = attempts + 1 "
            "WHERE id = :id"
        ),
        {"id": row["id"]},
    )
    return dict(row)


def finish(session: Session, job_id: str, error: str | None = None) -> None:
    session.execute(
        text(
            "UPDATE ops.async_jobs SET status = :s, error = :e, finished_at = now() "
            "WHERE id = :id"
        ),
        {"id": job_id, "s": "failed" if error else "done", "e": error},
    )
