"""`get_warranty_status` (Service, SQL) - the six-level precedence rule,
scoped to a canonical address plus the equipment the caller named.

Always returns the basis and the level, never a bare yes/no: levels 1-3 are
stated as facts with their basis, levels 4-6 are spoken as uncertain and
offered for a human check (`docs/AGENTS.md`). The tool does not decide how
confidently to speak - it returns what the rule found and lets the agent
apply the refusal rules against `level` and `confidence`.
"""

import datetime

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from switchboard_core.knowledge.warranty_status import (
    WarrantyEvidence,
    WarrantyStatusResult,
)
from switchboard_core.knowledge.warranty_status import (
    evaluate_warranty_status as _evaluate_warranty_status,
)
from switchboard_core.tools.contract import ToolResult, tool_call
from switchboard_core.tools.ids import CanonicalId


class WarrantyStatusRequest(BaseModel):
    canonical_id: CanonicalId

    #: The equipment the caller named, if they named any. Levels 1 and 2
    #: match on it; the rule still evaluates without it, at lower levels.
    equipment: str | None = None


class WarrantyStatusOutput(ToolResult):
    warranty: WarrantyStatusResult

    #: Echoed back because the verdict depends on it - a labor warranty that
    #: covers today does not cover a date six months out, and an audit of
    #: this answer needs to know which "today" produced it.
    as_of: datetime.datetime


@tool_call(kind="SQL", name="get_warranty_status", agent="Service")
def get_warranty_status(
    request: WarrantyStatusRequest,
    *,
    call_id: str,
    session: Session,
    as_of: datetime.datetime,
) -> WarrantyStatusOutput:
    """`as_of` is injected by the caller, never defaulted to "now" inside
    the rule - the same discipline the underlying function already enforces,
    kept here rather than relaxed at the tool boundary. It is deliberately
    not a request field: an agent filling tool arguments should not be
    inventing timestamps, and the runtime knows the real one.
    """
    warranty = _evaluate_warranty_status(
        session,
        request.canonical_id,
        equipment=request.equipment,
        as_of=as_of,
    )
    if warranty.evidence is not None:
        warranty.evidence.spoken = _spoken_form(session, warranty.evidence)
    return WarrantyStatusOutput(warranty=warranty, as_of=as_of)


def _spoken_form(session: Session, evidence: WarrantyEvidence) -> str:
    """What the agent may say for this evidence. Never the id.

    Hard rule 8: the agent speaks the job *number*. The rule's evidence
    for a job carries the internal id, because that is what the
    precedence rule joins on; the number is looked up here, at the one
    place the result is shaped for speaking.
    """
    if evidence.kind == "invoice":
        return f"invoice {evidence.id}"
    if evidence.kind == "note":
        return "the technician's note from that visit"
    number = session.execute(
        text("SELECT job_number FROM source.jobs WHERE id = :j"), {"j": evidence.id}
    ).scalar()
    return f"job number {number}" if number else "that visit"
