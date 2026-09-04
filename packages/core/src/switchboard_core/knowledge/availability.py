"""`find_availability`: bookable slots as gaps in an **assumed** working day.

Everything about the calendar here is an assumption, and `docs/SCOPE.md`
states it rather than burying it: the dataset has no shift table, no
business hours and no time off. What the data does say is where the work
actually happened, and the rule below covers 83% of it.

- Monday to Saturday, 08:00-18:00 `America/New_York`. Sunday is not
  offered: the 108 historical Sunday jobs are emergency work, and a caller
  asking for one gets a human, not a slot invented from an assumption.
- 120-minute arrival windows, the dominant historical value (1,874 of
  1,992 jobs).
- Occupancy is computed against **future `scheduled` jobs only**. A stale
  scheduled row is abandoned work, and letting it block a slot would hide
  real availability behind a row nobody intends to service.
- Only `role = 'field tech'` employees are bookable: 15 of the 23, which is
  exactly the count `docs/SCOPE.md` arrives at. The filter reads the role
  off the record rather than hard-coding the office-line and admin ids,
  so it stays correct if the roster changes.

Every slot this returns is a proposal against an invented calendar, and
`docs/AGENTS.md` requires the booking confirmation to say so.
"""

import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

#: The only timezone in the dataset, on all 1,992 rows.
BUSINESS_TZ = ZoneInfo("America/New_York")

WORKDAY_START_HOUR = 8
WORKDAY_END_HOUR = 18

#: Minutes. Matches `arrival_window` on 94% of historical jobs.
SLOT_MINUTES = 120

#: Monday is 0; Sunday, 6, is excluded.
BOOKABLE_WEEKDAYS = frozenset({0, 1, 2, 3, 4, 5})

FIELD_TECH_ROLE = "field tech"

#: Three, because these are read aloud.
#:
#: The tool's whole premise is that "a caller is offered times, not a
#: roster", and ten rows contradicted it: on a real call the agent read
#: the list out for 26.6 seconds - the single longest thing that happened
#: on that call, longer than every LLM call in it put together. A caller
#: cannot hold ten options in their head anyway. Callers who want more
#: ask, and the model can raise `limit` when they do.
DEFAULT_LIMIT = 3


class AvailabilitySlot(BaseModel):
    start: datetime.datetime
    end: datetime.datetime
    tech_id: str
    tech_name: str


_BOOKABLE_TECHS = text(
    """
    SELECT id AS tech_id, first_name || ' ' || last_name AS tech_name
    FROM source.employees
    WHERE role = :role
    ORDER BY tech_name
    """
)

#: Future scheduled work only - the same staleness rule `schedule.py`
#: applies, for the same reason.
_OCCUPANCY = text(
    """
    SELECT
        je.employee_id AS tech_id,
        j.scheduled_start,
        j.scheduled_start + make_interval(
            mins => COALESCE(NULLIF(j.arrival_window, 0), :slot_minutes)
        ) AS scheduled_end
    FROM source.jobs j
    JOIN source.job_employees je ON je.job_id = j.id
    WHERE j.scheduled_start IS NOT NULL
      AND j.work_status = 'scheduled'
      AND j.scheduled_start >= :as_of
      AND j.scheduled_start < :end
    """
)


def _day_slots(day: datetime.date) -> list[tuple[datetime.datetime, datetime.datetime]]:
    """Every arrival window inside one working day, in business time."""
    if day.weekday() not in BOOKABLE_WEEKDAYS:
        return []

    slots = []
    cursor = datetime.datetime.combine(
        day, datetime.time(WORKDAY_START_HOUR), tzinfo=BUSINESS_TZ
    )
    closing = datetime.datetime.combine(
        day, datetime.time(WORKDAY_END_HOUR), tzinfo=BUSINESS_TZ
    )
    step = datetime.timedelta(minutes=SLOT_MINUTES)
    while cursor + step <= closing:
        slots.append((cursor, cursor + step))
        cursor += step
    return slots


def find_availability(
    session: Session,
    *,
    start: datetime.datetime,
    end: datetime.datetime,
    as_of: datetime.datetime,
    limit: int = DEFAULT_LIMIT,
) -> list[AvailabilitySlot]:
    """Free arrival windows between `start` and `end`, soonest first.

    A slot already in the past is never offered, so `as_of` bounds the
    search as well as defining which scheduled jobs still count as
    occupancy.
    """
    floor = max(start, as_of)

    techs = session.execute(_BOOKABLE_TECHS, {"role": FIELD_TECH_ROLE}).all()
    busy: dict[str, list[tuple[datetime.datetime, datetime.datetime]]] = {}
    for row in session.execute(
        _OCCUPANCY, {"as_of": as_of, "end": end, "slot_minutes": SLOT_MINUTES}
    ).all():
        busy.setdefault(row.tech_id, []).append(
            (row.scheduled_start, row.scheduled_end)
        )

    slots: list[AvailabilitySlot] = []
    day = floor.astimezone(BUSINESS_TZ).date()
    last_day = end.astimezone(BUSINESS_TZ).date()

    while day <= last_day and len(slots) < limit:
        for slot_start, slot_end in _day_slots(day):
            if slot_start < floor or slot_end > end:
                continue
            for tech in techs:
                occupied = any(
                    slot_start < job_end and job_start < slot_end
                    for job_start, job_end in busy.get(tech.tech_id, ())
                )
                if not occupied:
                    slots.append(
                        AvailabilitySlot(
                            start=slot_start,
                            end=slot_end,
                            tech_id=tech.tech_id,
                            tech_name=tech.tech_name,
                        )
                    )
                    # One row per window, not one per free tech. A caller
                    # is offered times, not a roster: 15 techs free at
                    # 10:00 is one option to speak, and filling `limit`
                    # with the same window under different names would
                    # leave the agent nothing else to offer.
                    break
        day += datetime.timedelta(days=1)

    slots.sort(key=lambda s: (s.start, s.tech_name))
    return slots[:limit]
