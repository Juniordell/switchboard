"""`find_availability` (Dispatch, SQL) - free arrival windows.

Every slot is a proposal against an assumed working day, not a fact read
out of a calendar: the dataset has no shift table, no business hours and no
time off. `docs/SCOPE.md` states the assumption; `knowledge/availability.py`
implements it; `docs/AGENTS.md` requires the booking confirmation to say so
out loud.
"""

import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, BaseModel
from sqlalchemy.orm import Session

from switchboard_core.knowledge.availability import (
    DEFAULT_LIMIT,
    AvailabilitySlot,
)
from switchboard_core.knowledge.availability import (
    find_availability as _find_availability,
)
from switchboard_core.tools.contract import ToolDomainError, ToolResult, tool_call

#: The caller's clock. A model filling this request writes wall-clock
#: times with no zone; they mean Miami.
COMPANY_TZ = ZoneInfo("America/New_York")


def _aware(value: datetime.datetime) -> datetime.datetime:
    """A naive datetime is read as company local time, not rejected.

    The model produced "2023-10-09T08:00:00" on a real call - no zone -
    and the comparison against an aware `as_of` raised TypeError, which by
    T3.1's rule propagated as a defect. The input was wrong, but it was
    the model's, and the model needs a message, not a traceback.
    """
    return value if value.tzinfo else value.replace(tzinfo=COMPANY_TZ)


class AvailabilityRequest(BaseModel):
    start: Annotated[datetime.datetime, AfterValidator(_aware)]
    end: Annotated[datetime.datetime, AfterValidator(_aware)]
    limit: int = DEFAULT_LIMIT


class AvailabilityOutput(ToolResult):
    slots: list[AvailabilitySlot]

    #: Carried in the result so the agent cannot offer a slot without
    #: having been handed the caveat that goes with it.
    assumed_calendar: str = (
        "Monday to Saturday, 08:00-18:00 America/New_York, 120-minute "
        "arrival windows. The dataset carries no working hours; this is an "
        "assumption covering 83% of how this company has actually scheduled."
    )

    def result_rows(self) -> int:
        return len(self.slots)


@tool_call(kind="SQL", name="find_availability", agent="Dispatch")
def find_availability(
    request: AvailabilityRequest,
    *,
    call_id: str,
    session: Session,
    as_of: datetime.datetime,
) -> AvailabilityOutput:
    """One row per window rather than one per free tech: a caller is
    offered times, not a roster. Sunday and after-hours are never returned,
    so a caller who needs one gets a human instead of a slot invented from
    an assumption.
    """
    if request.end <= as_of:
        # The same real call: the model asked for a week in October 2023.
        # Saying which "today" this is lets it re-ask with a real one,
        # where "internal error" got the caller transferred.
        today = as_of.astimezone(COMPANY_TZ)
        raise ToolDomainError(
            f"that range is entirely in the past. Today is "
            f"{today:%A, %B %d, %Y}; ask for dates from today onward."
        )
    return AvailabilityOutput(
        slots=_find_availability(
            session,
            start=request.start,
            end=request.end,
            as_of=as_of,
            limit=request.limit,
        )
    )
