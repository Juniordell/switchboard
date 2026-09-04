"""`book_job` (Dispatch, write) - a new appointment.

Writes to `ops.booked_jobs`, never `source.jobs`: that schema mirrors
`data/` row for row and `scripts/verify_load.py` asserts it holds exactly
1,992 jobs. `get_schedule` unions the two, so the appointment is visible to
the same call that made it.

The slot is a proposal against an assumed working day (`docs/SCOPE.md`), and
`find_availability` carries that caveat. This tool records what the caller
agreed to, verbatim.
"""

import datetime

from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from switchboard_core.db.ops.bookings import BookedJob
from switchboard_core.knowledge.availability import SLOT_MINUTES
from switchboard_core.tools.contract import ToolResult, tool_call
from switchboard_core.tools.ids import CanonicalId, CustomerId
from switchboard_core.tools.writes import derived_id, idempotency_key, record_write


class BookJobRequest(BaseModel):
    customer_id: CustomerId
    scheduled_start: datetime.datetime
    description: str
    display_address: str

    canonical_id: CanonicalId | None = None
    arrival_window: int = SLOT_MINUTES
    tech_id: str | None = None
    tech_name: str | None = None

    #: What the caller actually said when they agreed, not a boolean
    #: asserting that they did. `docs/AGENTS.md`: no write without a spoken
    #: confirmation in the same turn sequence - so an unconfirmed booking
    #: is a request that cannot be built.
    spoken_confirmation: str

    @field_validator("spoken_confirmation")
    @classmethod
    def _must_be_real(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("book_job requires the caller's spoken confirmation")
        return value


class BookJobOutput(ToolResult):
    job_id: str

    #: Null, always. Job numbers are assigned by the field service system,
    #: and inventing one risks colliding with a real number exactly as
    #: `invoice_number` already collides with `job_number` in this dataset.
    #: The agent confirms the appointment without quoting a number.
    job_number: None = None

    scheduled_start: datetime.datetime
    arrival_window: int
    audit_id: str

    #: True when this call had already booked this slot at this address and
    #: nothing new was written.
    replayed: bool


@tool_call(kind="write", name="book_job", agent="Dispatch")
def book_job(
    request: BookJobRequest, *, call_id: str, session: Session
) -> BookJobOutput:
    """Idempotent on `call_id + slot + address`.

    `docs/AGENTS.md` specifies `call_id + slot`. The address is added
    because a property manager booking two of their buildings into the same
    window on one call is two legitimate appointments, and the narrower key
    would silently swallow the second as a retry. A real retry sends the
    same address, so nothing is lost - see `docs/DECISIONS.md`.
    """
    key = idempotency_key(
        call_id,
        request.scheduled_start.isoformat(),
        request.canonical_id or request.display_address,
    )
    job_id = derived_id("job_ops", key)

    audit, replayed = record_write(
        session,
        key=key,
        call_id=call_id,
        agent="Dispatch",
        tool="book_job",
        action="booked",
        job_id=job_id,
        new_values={
            "job_id": job_id,
            "customer_id": request.customer_id,
            "scheduled_start": request.scheduled_start.isoformat(),
            "arrival_window": request.arrival_window,
            "description": request.description,
            "display_address": request.display_address,
            "tech_name": request.tech_name,
        },
        spoken_confirmation=request.spoken_confirmation,
    )

    if not replayed:
        session.add(
            BookedJob(
                job_id=job_id,
                customer_id=request.customer_id,
                canonical_id=request.canonical_id,
                scheduled_start=request.scheduled_start,
                arrival_window=request.arrival_window,
                description=request.description,
                display_address=request.display_address,
                tech_id=request.tech_id,
                tech_name=request.tech_name,
                work_status="scheduled",
                call_id=call_id,
            )
        )
        session.flush()

    return BookJobOutput(
        job_id=job_id,
        scheduled_start=request.scheduled_start,
        arrival_window=request.arrival_window,
        audit_id=audit.id,
        replayed=replayed,
    )
