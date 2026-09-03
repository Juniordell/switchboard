"""The operations platform: calls, tool calls, jobs, review queue, and the
live feed.

`GET /events` is the one that carries the requirement. A tool call made on
a live phone call has to reach a browser in under a second, which rules out
polling and rules out anything that has to wait for someone else's
transaction to finish. Postgres `LISTEN`/`NOTIFY` delivers on commit, and
`switchboard_core.observability` commits each tool call row on its own
connection precisely so that commit happens immediately.

The read endpoints are deliberately dull: page over a table, newest first.
`jobs` is the only one that joins, because a job is `source.jobs` with the
`ops` overlay applied - the same union `get_schedule` does, for the same
reason.
"""

import asyncio
import contextlib
import json
import logging
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from switchboard_api.tools import get_session
from switchboard_core.db.session import database_url

router = APIRouter(tags=["platform"])
logger = logging.getLogger(__name__)

#: The channels the migrations announce on. Both are read by one stream so
#: the dashboard has a single connection rather than one per event kind.
CHANNELS = ("switchboard_tool_calls", "switchboard_writes")

#: How often the stream emits a comment when nothing has happened. Proxies
#: and browsers drop an idle connection; this keeps it open without
#: inventing an event.
KEEPALIVE_SECONDS = 15.0

DEFAULT_LIMIT = 50
MAX_LIMIT = 500

SessionDep = Annotated[Session, Depends(get_session)]
LimitQuery = Annotated[int, Query(ge=1, le=MAX_LIMIT)]


class Page(BaseModel):
    items: list[dict[str, Any]]
    count: int


def _page(session: Session, statement, **params) -> Page:
    rows = session.execute(text(statement), params).mappings().all()
    return Page(items=[dict(r) for r in rows], count=len(rows))


@router.get("/calls")
def list_calls(session: SessionDep, limit: LimitQuery = DEFAULT_LIMIT) -> Page:
    """Calls, most recent first, with how many tools each one used."""
    return _page(
        session,
        """
        SELECT c.call_id, c.caller, c.started_at, c.ended_at, c.last_agent,
               (SELECT count(*) FROM ops.tool_calls t
                 WHERE t.call_id = c.call_id) AS tool_calls
        FROM ops.calls c
        ORDER BY c.started_at DESC
        LIMIT :limit
        """,
        limit=limit,
    )


@router.get("/tool_calls")
def list_tool_calls(
    session: SessionDep,
    limit: LimitQuery = DEFAULT_LIMIT,
    call_id: str | None = None,
) -> Page:
    """Hard rule 5's seven fields, as rows. `call_id` narrows to one call."""
    return _page(
        session,
        """
        SELECT id, call_id, agent, tool, args, duration_ms, result_rows, ok,
               timings, created_at
        FROM ops.tool_calls
        WHERE (CAST(:call_id AS text) IS NULL OR call_id = CAST(:call_id AS text))
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        limit=limit,
        call_id=call_id,
    )


@router.get("/jobs")
def list_jobs(session: SessionDep, limit: LimitQuery = DEFAULT_LIMIT) -> Page:
    """Scheduled work, `source` and the write overlay as one list.

    A job the agent booked has no job number - the field service system
    assigns those - so the column is null rather than invented.
    """
    return _page(
        session,
        """
        SELECT * FROM (
            SELECT j.id AS job_id, j.job_number, j.customer_id,
                   COALESCE(r.scheduled_start, j.scheduled_start) AS scheduled_start,
                   j.work_status, j.description,
                   false AS agent_booked, (r.job_id IS NOT NULL) AS rescheduled
            FROM source.jobs j
            LEFT JOIN ops.job_reschedules r ON r.job_id = j.id
            WHERE COALESCE(r.scheduled_start, j.scheduled_start) IS NOT NULL
            UNION ALL
            SELECT b.job_id, NULL, b.customer_id,
                   COALESCE(r.scheduled_start, b.scheduled_start),
                   b.work_status, b.description,
                   true, (r.job_id IS NOT NULL)
            FROM ops.booked_jobs b
            LEFT JOIN ops.job_reschedules r ON r.job_id = b.job_id
        ) everything
        ORDER BY scheduled_start DESC
        LIMIT :limit
        """,
        limit=limit,
    )


@router.get("/review_queue")
def list_review_queue(
    session: SessionDep,
    limit: LimitQuery = DEFAULT_LIMIT,
    status: str = "open",
) -> Page:
    """What a human still has to look at. T7.3's Reviewer fills this."""
    return _page(
        session,
        """
        SELECT id, call_id, kind, status, title, payload, created_at, resolved_at
        FROM ops.review_queue
        WHERE status = :status
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        limit=limit,
        status=status,
    )


def _psycopg_url() -> str:
    """`database_url()` returns SQLAlchemy's dialect form
    (`postgresql+psycopg://`), which psycopg itself cannot parse. The
    listener talks to Postgres directly, so it needs the plain URL."""
    return database_url().replace("postgresql+psycopg://", "postgresql://", 1)


async def _listen() -> "asyncio.Queue[str]":
    """A queue fed by Postgres notifications on every channel."""
    queue: asyncio.Queue[str] = asyncio.Queue()
    connection = await psycopg.AsyncConnection.connect(_psycopg_url(), autocommit=True)
    for channel in CHANNELS:
        await connection.execute(f"LISTEN {channel}")

    async def pump() -> None:
        try:
            async for note in connection.notifies():
                await queue.put(
                    json.dumps(
                        {"channel": note.channel, "data": json.loads(note.payload)}
                    )
                )
        except Exception:
            logger.warning("notification stream ended", exc_info=True)
        finally:
            await connection.close()

    task = asyncio.create_task(pump())
    queue._pump_task = task
    return queue


@router.get("/events")
async def events() -> StreamingResponse:
    """Server-sent events: every tool call and every write, as it happens.

    No polling. Postgres delivers the notification on commit and this
    forwards it, which is what keeps a live tool call under a second away
    from the browser.
    """

    async def stream():
        queue = await _listen()
        try:
            yield ": connected\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(
                        queue.get(), timeout=KEEPALIVE_SECONDS
                    )
                except TimeoutError:
                    # A comment, not an event: nothing happened, and saying
                    # nothing happened is different from inventing one.
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {payload}\n\n"
        finally:
            task = getattr(queue, "_pump_task", None)
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
