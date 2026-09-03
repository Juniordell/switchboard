"""Every write the agent makes, one row, with the key that stops a retry
becoming a second booking.

`idempotency_key` is **unique in the database**, which is the whole
mechanism. A `SELECT` before the `INSERT` would be a check-then-act race:
two retries of the same turn can both find nothing and both write. The
constraint cannot be raced - the second insert conflicts, the tool reads
back what the first one wrote, and the caller gets the original result
marked as a replay.

The `NOTIFY` is emitted by a trigger on this table rather than by the tool
(see the migration). A write that forgot to notify would be invisible to
the dashboard with nothing failing, so the guarantee belongs where it
cannot be forgotten - the same reasoning that made `content_tsv` a
generated column in T2.5.

`transfer_to_human` is `control`, not `write`, and does not exist yet
(T5.4). It writes an audit row when it does, which is why `job_id`,
`old_values` and `spoken_confirmation` are all nullable here.
"""

import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from switchboard_core.db.base import OPS_SCHEMA, Base


class WriteAudit(Base):
    __tablename__ = "write_audit"
    __table_args__ = (
        Index("ix_write_audit_call_id", "call_id"),
        Index("ix_write_audit_job_id", "job_id"),
        {"schema": OPS_SCHEMA},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)

    #: Derived from the arguments that define "the same write" - for
    #: `book_job`, `call_id` + the slot. Unique: this is the retry guard.
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)

    call_id: Mapped[str] = mapped_column(String)
    agent: Mapped[str] = mapped_column(String)
    tool: Mapped[str] = mapped_column(String)

    #: What happened, in the tool's own words: booked, moved, noted.
    action: Mapped[str] = mapped_column(String)

    #: The job this touched. Null only for a future write that targets no
    #: job at all.
    job_id: Mapped[str | None] = mapped_column(String)

    #: Null for a creation. `move_job` fills it, which is what makes the
    #: row a record of a change rather than of a state.
    old_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_values: Mapped[dict[str, Any]] = mapped_column(JSONB)

    #: What the caller actually said, verbatim, not a boolean claiming they
    #: said something. Required by the tools that mutate a schedule.
    spoken_confirmation: Mapped[str | None] = mapped_column(String)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
