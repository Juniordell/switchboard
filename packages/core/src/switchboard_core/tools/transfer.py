"""`transfer_to_human` (any agent, control) - hand the call to a person.

**`control`, not `write`.** CLAUDE.md hard rule 4 scopes the Dispatch-only
restriction to *customer-record* write tools, and this mutates no customer
record: it routes a phone call and logs why. Classifying it as a write would
force a general enquiry to reach the write-holding agent in order to be
handed to a person, which is the opposite of the boundary's purpose.

It still writes an audit row, into the same `ops.write_audit` the write
tools use - a transfer is exactly the kind of thing someone reconstructs
afterwards, and the reason, the promises and the summary are what they need.

Then it stops. `docs/AGENTS.md`: the agent says it is transferring and says
nothing further.
"""

from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from switchboard_core.tools.contract import ToolResult, tool_call
from switchboard_core.tools.writes import idempotency_key, record_write


class TransferRequest(BaseModel):
    #: Why, in one line, for the person picking up.
    reason: str

    #: What the caller was told would happen. `docs/ARCHITECTURE.md` calls
    #: for the warm transfer to carry "every promise made so far", and a
    #: promise nobody wrote down is the one that gets broken.
    promises: list[str] = []

    #: What has been established so far, in the agent's own words.
    summary: str = ""

    #: Set when identity resolved before the transfer.
    canonical_id: str | None = None
    customer_id: str | None = None

    @field_validator("reason")
    @classmethod
    def _must_say_why(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("transfer_to_human requires a reason")
        return value


class TransferOutput(ToolResult):
    audit_id: str
    replayed: bool

    #: What the agent says, and then stops.
    spoken: str = "Let me get you to someone who can help. One moment."


@tool_call(kind="control", name="transfer_to_human", agent="any")
def transfer_to_human(
    request: TransferRequest, *, call_id: str, session: Session
) -> TransferOutput:
    """Route the call to a person, carrying the reason, what was
    established, and every promise made.

    Idempotent on the call and the reason: an agent that says it is
    transferring twice in one turn sequence transfers once.
    """
    key = idempotency_key(call_id, "transfer", request.reason.strip())

    audit, replayed = record_write(
        session,
        key=key,
        call_id=call_id,
        agent="any",
        tool="transfer_to_human",
        action="transferred",
        new_values={
            "reason": request.reason,
            "promises": request.promises,
            "summary": request.summary,
            "canonical_id": request.canonical_id,
            "customer_id": request.customer_id,
        },
    )
    return TransferOutput(audit_id=audit.id, replayed=replayed)
