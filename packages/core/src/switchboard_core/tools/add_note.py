"""`add_note` (Dispatch, write) - a note attributed to the agent and the
call that produced it.

Lands in `ops.agent_notes`, not `source.notes`, for the same reason
bookings stay out of `source.jobs`: that table is the loaded export and
`scripts/verify_load.py` asserts it holds exactly 6,954 rows.

`docs/AGENTS.md` requires no spoken confirmation here, and none is asked
for: writing down what was said is not a change to the caller's schedule or
account, and demanding a confirmation for it would train the agent to ask
for one where it does not matter.
"""

from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from switchboard_core.db.ops.bookings import AgentNote
from switchboard_core.knowledge.schedule import effective_job
from switchboard_core.tools.contract import ToolResult, tool_call
from switchboard_core.tools.errors import JobNotFoundError
from switchboard_core.tools.writes import derived_id, idempotency_key, record_write


class AddNoteRequest(BaseModel):
    job_id: str
    content: str

    @field_validator("content")
    @classmethod
    def _must_say_something(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("add_note requires content")
        return value


class AddNoteOutput(ToolResult):
    note_id: str
    job_id: str
    audit_id: str
    replayed: bool


@tool_call(kind="write", name="add_note", agent="Dispatch")
def add_note(
    request: AddNoteRequest, *, call_id: str, session: Session
) -> AddNoteOutput:
    """Idempotent on `call_id + job_id + the note's content`.

    `docs/AGENTS.md` specifies `call_id + slot` for the tools that book,
    and a note has no slot. The principle carries over unchanged: retrying
    one turn must not append the same note twice. Two genuinely different
    notes on one call differ in their content and key apart.
    """
    if effective_job(session, request.job_id) is None:
        raise JobNotFoundError(f"no job {request.job_id!r} in source or the overlay")

    content = request.content.strip()
    key = idempotency_key(call_id, request.job_id, content)
    note_id = derived_id("nte_ops", key)

    audit, replayed = record_write(
        session,
        key=key,
        call_id=call_id,
        agent="Dispatch",
        tool="add_note",
        action="noted",
        job_id=request.job_id,
        new_values={"note_id": note_id, "content": content},
    )

    if not replayed:
        session.add(
            AgentNote(
                note_id=note_id,
                job_id=request.job_id,
                content=content,
                call_id=call_id,
                agent="Dispatch",
            )
        )
        session.flush()

    return AddNoteOutput(
        note_id=note_id,
        job_id=request.job_id,
        audit_id=audit.id,
        replayed=replayed,
    )
