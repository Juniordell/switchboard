"""`get_schedule` (Service, SQL) - scheduled work in a date range, scoped to
who is asking.

`docs/AGENTS.md`: "a homeowner may only see their own jobs." That scoping is
enforced here rather than in the query layer, because the caller's role is a
fact about the conversation, not about the data. A customer-shaped caller
without a resolved `customer_id` cannot build a request at all - the model
rejects it, which is the Triage boundary showing up as a type error rather
than as a leak.
"""

import datetime

from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from switchboard_core.knowledge.schedule import ScheduledJob
from switchboard_core.knowledge.schedule import get_schedule as _get_schedule
from switchboard_core.tools.caller_role import CallerRole
from switchboard_core.tools.contract import ToolResult, tool_call

#: Roles that only ever see their own work. `TECH` and `OWNER` are internal
#: and see the whole day.
CUSTOMER_ROLES = frozenset({CallerRole.HOMEOWNER, CallerRole.PROPERTY_MANAGER})


class ScheduleRequest(BaseModel):
    start: datetime.datetime
    end: datetime.datetime
    role: CallerRole

    #: Required for a customer-shaped caller, ignored for an internal one.
    customer_id: str | None = None

    @model_validator(mode="after")
    def _customers_must_be_identified(self) -> "ScheduleRequest":
        if self.role in CUSTOMER_ROLES and not self.customer_id:
            raise ValueError(
                f"role {self.role} may only see their own jobs, so "
                f"customer_id is required"
            )
        return self


class ScheduleOutput(ToolResult):
    jobs: list[ScheduledJob]

    def result_rows(self) -> int:
        return len(self.jobs)


@tool_call(name="get_schedule", agent="Service")
def get_schedule(
    request: ScheduleRequest,
    *,
    call_id: str,
    session: Session,
    as_of: datetime.datetime,
) -> ScheduleOutput:
    """Soonest first, stale scheduled jobs excluded.

    A `scheduled` job whose start has already passed is abandoned work
    (`docs/SCOPE.md`), and 38 of the dataset's 76 scheduled rows were in
    that state. None of them is ever spoken as an upcoming appointment.
    """
    return ScheduleOutput(
        jobs=_get_schedule(
            session,
            start=request.start,
            end=request.end,
            as_of=as_of,
            customer_id=request.customer_id,
        )
    )
