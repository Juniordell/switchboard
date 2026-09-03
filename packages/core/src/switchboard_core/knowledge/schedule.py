"""`get_schedule`: scheduled work in a date range, over `source` **and** the
write overlay.

Nothing the agent books goes into `source.jobs` - that schema mirrors
`data/` row for row and `scripts/verify_load.py` asserts its exact counts.
Bookings live in `ops.booked_jobs` and reschedules in `ops.job_reschedules`,
and this module is where the two halves become one answer. Without that
union a caller could book an appointment and be told, thirty seconds later
in the same call, that they have nothing scheduled.

**Stale jobs are excluded.** `docs/SCOPE.md`: a job whose `work_status` is
`scheduled` and whose start has already passed is abandoned, not upcoming -
38 of the 76 scheduled rows were in that state when the dataset was
measured. They are never spoken as an appointment; they belong in the
dashboard's own stale bucket (T6.3). Staleness is tested against the
**effective** start, so moving an abandoned job into the future revives it,
which is exactly what moving it means.

Jobs with no `scheduled_start` at all are not scheduled and never appear.

`as_of` is a parameter, never `now()` inside the query, for the same reason
`evaluate_warranty_status` takes one: what counts as past has to be fixed by
the caller for the answer to be reproducible or testable.
"""

import datetime

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session


class ScheduledJob(BaseModel):
    job_id: str

    #: **Null for an agent booking.** Job numbers come from the field
    #: service system, and inventing one risks colliding with a real
    #: number the way `invoice_number` already collides with `job_number`
    #: (`docs/DATA.md`). Until the office assigns one, the agent confirms
    #: the appointment without quoting a number.
    job_number: str | None

    customer_id: str
    scheduled_start: datetime.datetime

    #: Minutes. 120 on 1,874 of 1,992 source jobs; 0 on 102, which is a
    #: missing value rather than an instantaneous visit.
    arrival_window: int

    work_status: str
    description: str
    techs: list[str]
    display_address: str

    #: True when this row came from `ops.booked_jobs` rather than `source`.
    agent_booked: bool

    #: True when `ops.job_reschedules` moved it off its loaded slot.
    rescheduled: bool


_SCHEDULE_QUERY = text(
    """
    WITH from_source AS (
        SELECT
            j.id AS job_id,
            j.job_number,
            j.customer_id,
            COALESCE(r.scheduled_start, j.scheduled_start) AS scheduled_start,
            COALESCE(j.arrival_window, 0) AS arrival_window,
            j.work_status,
            j.description,
            trim(both ' ' from
                COALESCE(j.address_street, '') || ' ' ||
                COALESCE(j.address_street_line_2, '')) AS display_address,
            (
                SELECT array_agg(
                    e.first_name || ' ' || e.last_name ORDER BY je.position
                )
                FROM source.job_employees je
                JOIN source.employees e ON e.id = je.employee_id
                WHERE je.job_id = j.id
            ) AS techs,
            false AS agent_booked,
            (r.job_id IS NOT NULL) AS rescheduled
        FROM source.jobs j
        LEFT JOIN ops.job_reschedules r ON r.job_id = j.id
        WHERE COALESCE(r.scheduled_start, j.scheduled_start) IS NOT NULL
    ),
    from_overlay AS (
        SELECT
            b.job_id,
            NULL AS job_number,
            b.customer_id,
            COALESCE(r.scheduled_start, b.scheduled_start) AS scheduled_start,
            b.arrival_window,
            b.work_status,
            b.description,
            b.display_address,
            CASE WHEN b.tech_name IS NULL THEN NULL
                 ELSE ARRAY[b.tech_name] END AS techs,
            true AS agent_booked,
            (r.job_id IS NOT NULL) AS rescheduled
        FROM ops.booked_jobs b
        LEFT JOIN ops.job_reschedules r ON r.job_id = b.job_id
    ),
    everything AS (
        SELECT * FROM from_source
        UNION ALL
        SELECT * FROM from_overlay
    )
    SELECT *
    FROM everything
    WHERE scheduled_start >= :start
      AND scheduled_start < :end
      -- Stale: still marked scheduled, but its effective start has gone by.
      AND NOT (work_status = 'scheduled' AND scheduled_start < :as_of)
      -- Cast: Postgres cannot infer a bare NULL parameter's type here.
      AND (CAST(:customer_id AS text) IS NULL
           OR customer_id = CAST(:customer_id AS text))
    ORDER BY scheduled_start
    """
)

#: The effective slot of one job, wherever it lives. `move_job` needs the
#: old value for its audit row, and needs to know the job exists at all.
_EFFECTIVE_JOB = text(
    """
    SELECT job_id, customer_id, scheduled_start, agent_booked FROM (
        SELECT
            j.id AS job_id,
            j.customer_id,
            COALESCE(r.scheduled_start, j.scheduled_start) AS scheduled_start,
            false AS agent_booked
        FROM source.jobs j
        LEFT JOIN ops.job_reschedules r ON r.job_id = j.id
        WHERE j.id = :job_id
        UNION ALL
        SELECT
            b.job_id,
            b.customer_id,
            COALESCE(r.scheduled_start, b.scheduled_start) AS scheduled_start,
            true AS agent_booked
        FROM ops.booked_jobs b
        LEFT JOIN ops.job_reschedules r ON r.job_id = b.job_id
        WHERE b.job_id = :job_id
    ) found
    """
)


class EffectiveJob(BaseModel):
    job_id: str
    customer_id: str
    scheduled_start: datetime.datetime | None
    agent_booked: bool


def effective_job(session: Session, job_id: str) -> EffectiveJob | None:
    """The job as it currently stands, overlay applied, or `None` if no
    such job exists in either place."""
    row = session.execute(_EFFECTIVE_JOB, {"job_id": job_id}).first()
    if row is None:
        return None
    return EffectiveJob(
        job_id=row.job_id,
        customer_id=row.customer_id,
        scheduled_start=row.scheduled_start,
        agent_booked=row.agent_booked,
    )


def get_schedule(
    session: Session,
    *,
    start: datetime.datetime,
    end: datetime.datetime,
    as_of: datetime.datetime,
    customer_id: str | None = None,
) -> list[ScheduledJob]:
    """Scheduled jobs in `[start, end)`, soonest first, agent bookings
    included and reschedules applied.

    `customer_id` narrows to one customer's jobs. `docs/AGENTS.md` requires
    that for a homeowner - a caller may only see their own work - and the
    tool layer is where that is enforced, since only there is the caller's
    role known.
    """
    rows = session.execute(
        _SCHEDULE_QUERY,
        {
            "start": start,
            "end": end,
            "as_of": as_of,
            "customer_id": customer_id,
        },
    ).all()

    return [
        ScheduledJob(
            job_id=row.job_id,
            job_number=row.job_number,
            customer_id=row.customer_id,
            scheduled_start=row.scheduled_start,
            arrival_window=row.arrival_window,
            work_status=row.work_status,
            description=row.description,
            techs=row.techs or [],
            display_address=row.display_address,
            agent_booked=row.agent_booked,
            rescheduled=row.rescheduled,
        )
        for row in rows
    ]
