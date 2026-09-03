"""`move_job` (Dispatch, write) - an existing job to a new slot.

The job itself is never mutated. A reschedule is a row in
`ops.job_reschedules` keyed on the job, and `get_schedule` applies it as an
overlay - so a job loaded from `data/` keeps its loaded values while
answering with its new time. One row per job: the latest move wins, and the
audit log keeps every step of how it got there.

Works on an agent booking as readily as on a loaded job, since the overlay
does not care which table the job came from.
"""

import datetime

from pydantic import BaseModel, field_validator
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from switchboard_core.db.ops.bookings import JobReschedule
from switchboard_core.knowledge.schedule import effective_job
from switchboard_core.tools.contract import ToolResult, tool_call
from switchboard_core.tools.errors import JobNotFoundError
from switchboard_core.tools.writes import idempotency_key, record_write


class MoveJobRequest(BaseModel):
    job_id: str
    scheduled_start: datetime.datetime

    #: Same rule as `book_job`: no schedule change without the caller's own
    #: words agreeing to it.
    spoken_confirmation: str

    @field_validator("spoken_confirmation")
    @classmethod
    def _must_be_real(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("move_job requires the caller's spoken confirmation")
        return value


class MoveJobOutput(ToolResult):
    job_id: str
    scheduled_start: datetime.datetime
    previous_start: datetime.datetime | None
    audit_id: str
    replayed: bool


@tool_call(name="move_job", agent="Dispatch")
def move_job(
    request: MoveJobRequest, *, call_id: str, session: Session
) -> MoveJobOutput:
    """Idempotent on `call_id + job_id + the new slot`.

    The audit row carries both the old and the new time, which is what
    makes it a record of a change rather than of a state - `docs/AGENTS.md`
    asks for exactly that here.
    """
    current = effective_job(session, request.job_id)
    if current is None:
        raise JobNotFoundError(f"no job {request.job_id!r} in source or the overlay")

    key = idempotency_key(call_id, request.job_id, request.scheduled_start.isoformat())
    previous_start = current.scheduled_start

    audit, replayed = record_write(
        session,
        key=key,
        call_id=call_id,
        agent="Dispatch",
        tool="move_job",
        action="moved",
        job_id=request.job_id,
        old_values={
            "scheduled_start": (previous_start.isoformat() if previous_start else None)
        },
        new_values={"scheduled_start": request.scheduled_start.isoformat()},
        spoken_confirmation=request.spoken_confirmation,
    )

    if not replayed:
        session.execute(
            insert(JobReschedule)
            .values(
                job_id=request.job_id,
                scheduled_start=request.scheduled_start,
                previous_start=previous_start,
                call_id=call_id,
            )
            .on_conflict_do_update(
                index_elements=["job_id"],
                set_={
                    "scheduled_start": request.scheduled_start,
                    "previous_start": previous_start,
                    "call_id": call_id,
                },
            )
        )
        session.flush()

    return MoveJobOutput(
        job_id=request.job_id,
        scheduled_start=request.scheduled_start,
        previous_start=previous_start,
        audit_id=audit.id,
        replayed=replayed,
    )
