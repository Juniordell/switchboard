"""Persist the tool call log, so a dashboard can see it.

T3.1 made `{call_id, agent, tool, args, duration_ms, result_rows, ok}` a log
line, which is the right shape for a log and the wrong shape for anything in
another process. T6.2 needs a live feed, and a feed needs a row: Postgres
announces rows, not log records.

The decorator is left alone. This is a `logging.Handler` on the same logger,
installed by whoever wants the rows - the agent does, the test suite does
not - so persistence is a deployment choice rather than a second job bolted
onto the contract.

**Each row commits on its own connection.** Postgres holds a notification
until commit, so a row written inside the caller's still-open transaction
would not reach the SSE endpoint until that transaction ended. The whole
requirement is that a tool call shows up in under a second; waiting on
someone else's commit is exactly how that gets missed.

A failure here never reaches the caller. Losing a dashboard row is not
worth losing a phone call over.
"""

import json
import logging
import uuid

from sqlalchemy import text
from sqlalchemy.engine import Engine

from switchboard_core.db.session import create_db_engine, session_factory

log = logging.getLogger(__name__)

TOOL_LOGGER = "switchboard_core.tools"

#: The seven fields of CLAUDE.md hard rule 5. Anything else in the record is
#: a partial timing (T3.1) and goes to the `timings` column.
_RESERVED = frozenset(
    {"call_id", "agent", "tool", "args", "duration_ms", "result_rows", "ok"}
)

_INSERT = text(
    """
    INSERT INTO ops.tool_calls
        (id, call_id, agent, tool, args, duration_ms, result_rows, ok, timings)
    VALUES
        (:id, :call_id, :agent, :tool, CAST(:args AS jsonb), :duration_ms,
         :result_rows, :ok, CAST(:timings AS jsonb))
    """
)


class ToolCallRecorder(logging.Handler):
    """Writes every tool call the decorator logs into `ops.tool_calls`."""

    def __init__(self, engine: Engine | None = None) -> None:
        super().__init__(level=logging.INFO)
        self._engine = engine or create_db_engine()
        self._sessions = session_factory(self._engine)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = json.loads(record.getMessage())
        except ValueError:
            # Not a tool call. This logger carries nothing else today, but
            # a stray line must not take the handler down.
            return

        if not payload.keys() >= _RESERVED:
            return

        timings = {k: v for k, v in payload.items() if k not in _RESERVED}
        try:
            with self._sessions() as session, session.begin():
                session.execute(
                    _INSERT,
                    {
                        "id": f"tc_{uuid.uuid4().hex}",
                        "call_id": payload["call_id"],
                        "agent": payload["agent"],
                        "tool": payload["tool"],
                        "args": json.dumps(payload["args"]),
                        "duration_ms": payload["duration_ms"],
                        "result_rows": payload["result_rows"],
                        "ok": payload["ok"],
                        "timings": json.dumps(timings) if timings else None,
                    },
                )
        except Exception:
            # Never let the dashboard cost someone their call.
            log.warning("could not record tool call", exc_info=True)


def record_tool_calls(engine: Engine | None = None) -> ToolCallRecorder:
    """Install the recorder. Idempotent: calling twice does not double-write.

    Returns the handler so a caller that wants to shut it down cleanly can.
    """
    logger = logging.getLogger(TOOL_LOGGER)
    for existing in logger.handlers:
        if isinstance(existing, ToolCallRecorder):
            return existing

    handler = ToolCallRecorder(engine)
    logger.addHandler(handler)
    # The decorator logs at INFO; without this the record never reaches a
    # handler when the root is left at WARNING.
    if logger.level == logging.NOTSET or logger.level > logging.INFO:
        logger.setLevel(logging.INFO)
    return handler
