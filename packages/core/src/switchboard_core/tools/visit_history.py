"""`get_visit_history` (Service, SQL) - structured rows for one canonical
address, most recent first.

Rows only: no generated summary. `docs/ARCHITECTURE.md` is explicit that the
agent summarises at speaking time, where it has the caller's actual
question, so a pre-written sentence here would freeze an answer nobody asked
for yet. `job_number` is the number spoken to callers; invoice numbers are
aggregated per visit and labelled as invoice numbers when spoken.
"""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from switchboard_core.knowledge.visit_history import VisitRow
from switchboard_core.knowledge.visit_history import (
    get_visit_history as _get_visit_history,
)
from switchboard_core.tools.contract import ToolResult, tool_call
from switchboard_core.tools.ids import CanonicalId


class VisitHistoryRequest(BaseModel):
    canonical_id: CanonicalId


class VisitHistoryOutput(ToolResult):
    visits: list[VisitRow]

    def result_rows(self) -> int:
        return len(self.visits)


@tool_call(kind="SQL", name="get_visit_history", agent="Service")
def get_visit_history(
    request: VisitHistoryRequest, *, call_id: str, session: Session
) -> VisitHistoryOutput:
    """Every job at `canonical_id`, ordered so "last" is a fact rather than
    an inference. An address with no jobs returns no visits, not an error -
    a caller can be at an address this company has never been to.
    """
    return VisitHistoryOutput(visits=_get_visit_history(session, request.canonical_id))
