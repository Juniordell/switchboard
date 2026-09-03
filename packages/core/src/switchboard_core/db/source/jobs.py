"""``data/jobs.jsonl`` — 1,992 jobs, 2,114 tags, 2,551 assignments, 6,954 notes.

The source nests ``schedule``, ``work_timestamps``, ``customer``, ``address``,
``assigned_employees``, ``tags`` and ``notes`` inside each job. The first two
are flattened into columns, the customer and the employees become foreign keys
- their embedded copies were verified identical to the entity files, so nothing
is lost - and the rest become child tables. The address is a special case; see
:class:`Job`.
"""

import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from switchboard_core.db.base import SOURCE_SCHEMA, Base, Cents

#: Values seen in this export. Deliberately not a CHECK constraint: these
#: describe the export, they do not define the domain, and a new value should
#: load rather than fail. The loader warns on anything outside the set, with a
#: count, so absence of a constraint does not become absence of visibility.
WORK_STATUSES = frozenset(
    {
        "complete rated",
        "complete unrated",
        "user canceled",
        "scheduled",
        "pro canceled",
        "needs scheduling",
        "in progress",
    }
)

_JOBS_FK = f"{SOURCE_SCHEMA}.jobs.id"


class Job(Base):
    """One job.

    **The source field named ``invoice_number`` is the job number** and is
    loaded as :attr:`job_number`. It is on a different sequence from
    ``invoices.invoice_number`` in the same 4-digit range, so joining on the
    number lands on another customer's invoice 1,649 times out of 1,992.
    ``job_id`` is the only join key. See CLAUDE.md hard rule 8.

    The address is stored three ways, on purpose:

    * ``address_id`` - the source id, null on 4 jobs, so not a foreign key.
    * ``address_*`` columns - the address as the job carries it. Three jobs
      have a real street with no id and would lose it under a foreign key.
    * ``address_raw`` - the untouched JSONB object, as a tiebreaker for when
      the T2.1 normaliser does something surprising with a street.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_address_id", "address_id"),
        Index("ix_jobs_scheduled_start", "scheduled_start"),
        {"schema": SOURCE_SCHEMA},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)

    #: Source field ``invoice_number``. Renamed at the boundary; the source
    #: name exists nowhere past the loader.
    job_number: Mapped[str] = mapped_column(String, unique=True, index=True)

    description: Mapped[str] = mapped_column(String)
    work_status: Mapped[str] = mapped_column(String, index=True)
    lead_source: Mapped[str | None] = mapped_column(String)

    total_amount: Mapped[int] = mapped_column(Cents)
    outstanding_balance: Mapped[int] = mapped_column(Cents)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    customer_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SOURCE_SCHEMA}.customers.id"), index=True
    )

    # schedule
    scheduled_start: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    scheduled_end: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    time_zone: Mapped[str] = mapped_column(String)
    arrival_window: Mapped[int] = mapped_column()

    # work_timestamps
    on_my_way_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # address
    address_id: Mapped[str | None] = mapped_column(String)
    address_street: Mapped[str | None] = mapped_column(String)
    address_street_line_2: Mapped[str | None] = mapped_column(String)
    address_city: Mapped[str | None] = mapped_column(String)
    address_state: Mapped[str | None] = mapped_column(String)
    address_zip: Mapped[str | None] = mapped_column(String)
    address_latitude: Mapped[float | None] = mapped_column(Float)
    address_longitude: Mapped[float | None] = mapped_column(Float)
    address_raw: Mapped[dict[str, Any]] = mapped_column(JSONB)


class JobTag(Base):
    """``jobs[].tags``.

    23 distinct tags, including ``ACTIVE LEAK`` and ``ACTIVE LEAK\\`` as
    separate values. The trailing backslashes are data.
    """

    __tablename__ = "job_tags"
    __table_args__ = (
        Index("ix_job_tags_tag", "tag"),
        {"schema": SOURCE_SCHEMA},
    )

    job_id: Mapped[str] = mapped_column(ForeignKey(_JOBS_FK), primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    tag: Mapped[str] = mapped_column(String)


class JobEmployee(Base):
    """``jobs[].assigned_employees``. 95 jobs have none."""

    __tablename__ = "job_employees"
    __table_args__ = {"schema": SOURCE_SCHEMA}

    job_id: Mapped[str] = mapped_column(ForeignKey(_JOBS_FK), primary_key=True)
    employee_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SOURCE_SCHEMA}.employees.id"), primary_key=True, index=True
    )
    position: Mapped[int] = mapped_column()


class Note(Base):
    """``jobs[].notes``.

    A note is ``{id, content}`` and nothing else: no timestamp, no author.
    ``position`` preserves array order, which is roughly chronological and is
    the only ordering signal that exists. Any date shown for a note is the
    service date of its job. See docs/DATA.md.
    """

    __tablename__ = "notes"
    __table_args__ = (
        Index("ix_notes_job_id_position", "job_id", "position"),
        {"schema": SOURCE_SCHEMA},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    # No standalone index on job_id: ix_notes_job_id_position covers it as a
    # leading-column prefix, and a second index would cost writes for nothing.
    job_id: Mapped[str] = mapped_column(ForeignKey(_JOBS_FK))
    position: Mapped[int] = mapped_column()
    content: Mapped[str] = mapped_column(String)
