"""The write overlay: what the agent booked, moved, or wrote down.

These three tables are the current state; `write_audit` is the history of
how it got there. Read paths union them with `source` - see
`switchboard_core.knowledge.schedule`.

**No foreign key to `source.jobs`.** A reschedule or a note can target
either a job that was loaded from `data/` or one this agent booked minutes
ago, and no single foreign key can point at both tables. The tools check
the target exists in one of them before writing and return a typed error
when it does not, which is the check a foreign key would have made.
"""

import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from switchboard_core.db.base import OPS_SCHEMA, Base


class BookedJob(Base):
    """An appointment that did not come from `data/`. Shaped like the parts
    of `source.jobs` a schedule answer actually needs, not like the whole
    row: there is no invoice, no completion, no history on something that
    has not happened yet.
    """

    __tablename__ = "booked_jobs"
    __table_args__ = (
        Index("ix_booked_jobs_scheduled_start", "scheduled_start"),
        Index("ix_booked_jobs_customer_id", "customer_id"),
        {"schema": OPS_SCHEMA},
    )

    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str] = mapped_column(String)
    canonical_id: Mapped[str | None] = mapped_column(String)

    scheduled_start: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    #: Minutes, matching `source.jobs.arrival_window`.
    arrival_window: Mapped[int] = mapped_column()

    description: Mapped[str] = mapped_column(String)
    display_address: Mapped[str] = mapped_column(String)

    tech_id: Mapped[str | None] = mapped_column(String)
    tech_name: Mapped[str | None] = mapped_column(String)

    #: Always 'scheduled' today. A column rather than a constant because
    #: the dashboard reads this table beside `source.jobs`, where it is one.
    work_status: Mapped[str] = mapped_column(String, default="scheduled")

    call_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class JobReschedule(Base):
    """A new slot for an existing job. One row per job - the latest move
    wins, and the audit log keeps every step of how it got there.
    """

    __tablename__ = "job_reschedules"
    __table_args__ = {"schema": OPS_SCHEMA}

    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    scheduled_start: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    #: Where it was before the most recent move, for a dashboard that wants
    #: to show the change without joining the audit log.
    previous_start: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    call_id: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AgentNote(Base):
    """A note the agent added, attributed to the call that produced it.

    Kept out of `source.notes` for the same reason bookings stay out of
    `source.jobs`: that table is the loaded export, and
    `scripts/verify_load.py` asserts it holds exactly 6,954 rows.
    """

    __tablename__ = "agent_notes"
    __table_args__ = (
        Index("ix_agent_notes_job_id", "job_id"),
        {"schema": OPS_SCHEMA},
    )

    note_id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(String)
    call_id: Mapped[str] = mapped_column(String)
    agent: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
