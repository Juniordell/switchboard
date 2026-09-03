"""`get_schedule`: scheduled work in a date range.

**Stale jobs are excluded.** `docs/SCOPE.md`: a job whose `work_status` is
`scheduled` and whose `scheduled_start` has already passed is abandoned, not
upcoming - 38 of the 76 scheduled rows were already in that state when the
dataset was measured. They are never spoken as an appointment. They belong
in the operations dashboard's own stale bucket (T6.3), not in an answer to
"when are you coming".

Jobs with no `scheduled_start` at all are not scheduled and never appear
here either.

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
    job_number: str
    customer_id: str
    scheduled_start: datetime.datetime

    #: Minutes. 120 on 1,874 of 1,992 jobs; 0 on 102, which is a missing
    #: value rather than an instantaneous visit.
    arrival_window: int

    work_status: str
    description: str
    techs: list[str]
    display_address: str


_SCHEDULE_QUERY = text(
    """
    SELECT
        j.id AS job_id,
        j.job_number,
        j.customer_id,
        j.scheduled_start,
        COALESCE(j.arrival_window, 0) AS arrival_window,
        j.work_status,
        j.description,
        trim(both ' ' from
            COALESCE(j.address_street, '') || ' ' ||
            COALESCE(j.address_street_line_2, '')) AS display_address,
        (
            SELECT array_agg(e.first_name || ' ' || e.last_name ORDER BY je.position)
            FROM source.job_employees je
            JOIN source.employees e ON e.id = je.employee_id
            WHERE je.job_id = j.id
        ) AS techs
    FROM source.jobs j
    WHERE j.scheduled_start IS NOT NULL
      AND j.scheduled_start >= :start
      AND j.scheduled_start < :end
      -- Stale: scheduled, but the start has already gone by.
      AND NOT (j.work_status = 'scheduled' AND j.scheduled_start < :as_of)
      -- Cast: Postgres cannot infer a bare NULL parameter's type here.
      AND (CAST(:customer_id AS text) IS NULL
           OR j.customer_id = CAST(:customer_id AS text))
    ORDER BY j.scheduled_start
    """
)


def get_schedule(
    session: Session,
    *,
    start: datetime.datetime,
    end: datetime.datetime,
    as_of: datetime.datetime,
    customer_id: str | None = None,
) -> list[ScheduledJob]:
    """Scheduled jobs in `[start, end)`, soonest first.

    `customer_id` narrows to one customer's jobs. `docs/AGENTS.md` requires
    that for a homeowner - a caller may only see their own work - and the
    tool layer is where that requirement is enforced, since only there is
    the caller's role known.
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
        )
        for row in rows
    ]
