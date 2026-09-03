"""What the operations platform reads: calls, their tool calls, and the
review queue.

**`tool_calls` is the reason this schema grows.** CLAUDE.md hard rule 5's
seven fields have been a log line since T3.1, which is right for a log and
useless for a dashboard: a log line does not cross a process boundary. The
requirement that a tool call show up in a live stream in under a second
makes it a row, and a row can be `NOTIFY`-ed.

The decorator is not changed to write it. `switchboard_core.observability`
installs a logging handler that persists what the decorator already emits,
so persistence stays a deployment choice - the agent turns it on, the test
suite does not - and the contract from T3.1 keeps its single job.

`ops.calls` and `ops.review_queue` are thin on purpose. A call is what the
dashboard groups by; the review queue is what T7.3's Reviewer fills. Both
are shaped for the endpoints that read them and nothing more.
"""

import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from switchboard_core.db.base import OPS_SCHEMA, Base


class Call(Base):
    """One phone call. `call_id` is the LiveKit room name, which is what
    every audit row and every tool call already carries."""

    __tablename__ = "calls"
    __table_args__ = (
        Index("ix_calls_started_at", "started_at"),
        {"schema": OPS_SCHEMA},
    )

    call_id: Mapped[str] = mapped_column(String, primary_key=True)

    #: The SIP participant, when the call came in over the phone. Null for
    #: a console or web session.
    caller: Mapped[str | None] = mapped_column(String)

    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ended_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    #: The last agent to hold the call - Triage, Service or Dispatch.
    last_agent: Mapped[str | None] = mapped_column(String)


class ToolCall(Base):
    """Hard rule 5's seven fields, as a row.

    `timings` carries the partial breakdown a result may report
    (`search_notes`: `embedding_ms` and `postgres_ms`), kept out of the
    seven so the row stays exactly what the rule names.
    """

    __tablename__ = "tool_calls"
    __table_args__ = (
        Index("ix_tool_calls_call_id", "call_id"),
        Index("ix_tool_calls_created_at", "created_at"),
        {"schema": OPS_SCHEMA},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    call_id: Mapped[str] = mapped_column(String)
    agent: Mapped[str] = mapped_column(String)
    tool: Mapped[str] = mapped_column(String)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB)
    duration_ms: Mapped[float] = mapped_column(Float)
    result_rows: Mapped[int] = mapped_column()
    ok: Mapped[bool] = mapped_column(Boolean)

    timings: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ReviewItem(Base):
    """Something a human should look at before it becomes a write.

    `docs/ARCHITECTURE.md`: anything the Reviewer scores below threshold
    becomes a proposal rather than a write, tagged `ai-ready-for-review`.
    T7.3 fills this; T6.1 exposes it so the screen exists first.
    """

    __tablename__ = "review_queue"
    __table_args__ = (
        Index("ix_review_queue_status", "status"),
        {"schema": OPS_SCHEMA},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    call_id: Mapped[str | None] = mapped_column(String)

    #: What kind of proposal. `ai-ready-for-review` is the one T7.3 emits.
    kind: Mapped[str] = mapped_column(String)

    #: open / approved / rejected. A string rather than an enum for the
    #: same reason the source tables have no CHECK constraints: an unknown
    #: value must stay visible, not be rejected at the boundary.
    status: Mapped[str] = mapped_column(String, default="open")

    title: Mapped[str] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
