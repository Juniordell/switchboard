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
from sqlalchemy.orm import Session

from switchboard_core.knowledge.warranty_status import WarrantyStatusResult
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
    return WarrantyStatusOutput(
        warranty=_evaluate_warranty_status(
            session,
            request.canonical_id,
            equipment=request.equipment,
            as_of=as_of,
        ),
        as_of=as_of,
    )
