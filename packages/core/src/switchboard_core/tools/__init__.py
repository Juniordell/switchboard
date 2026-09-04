"""The tool layer: one Pydantic contract per entry in `docs/AGENTS.md`'s
tool table.

Every tool takes a Pydantic request, returns a Pydantic result, logs
`{call_id, agent, tool, args, duration_ms, result_rows, ok}` including on
failure, and returns a typed `ToolError` for a recognised domain outcome
while letting a defect propagate.

`agent` on each tool is the agent allowed to hold it. What is here is
exactly the read half of that table; write tools (T3.3) and `web_search`
(T3.4) do not exist yet.
"""

from switchboard_core.tools.add_note import (
    AddNoteOutput,
    AddNoteRequest,
    add_note,
)
from switchboard_core.tools.availability import (
    AvailabilityOutput,
    AvailabilityRequest,
    find_availability,
)
from switchboard_core.tools.book_job import (
    BookJobOutput,
    BookJobRequest,
    book_job,
)
from switchboard_core.tools.call_log import log_tool_call
from switchboard_core.tools.caller_role import (
    CallerRole,
    CallerRoleOutput,
    CallerRoleRequest,
    identify_caller_role,
)
from switchboard_core.tools.contract import (
    ToolDomainError,
    ToolError,
    ToolResult,
    tool_call,
)
from switchboard_core.tools.customer_balance import (
    CustomerBalanceOutput,
    CustomerBalanceRequest,
    get_customer_balance,
)
from switchboard_core.tools.errors import (
    InvalidEntityIdError,
    JobNotFoundError,
    RetrievalUnavailableError,
    WebSearchUnavailableError,
)
from switchboard_core.tools.ids import CanonicalId, CustomerId, JobId
from switchboard_core.tools.move_job import (
    MoveJobOutput,
    MoveJobRequest,
    move_job,
)
from switchboard_core.tools.resolve_address import (
    ResolveAddressOutput,
    ResolveAddressRequest,
    resolve_address,
)
from switchboard_core.tools.resolve_customer import (
    ResolveCustomerOutput,
    ResolveCustomerRequest,
    resolve_customer,
)
from switchboard_core.tools.schedule import (
    ScheduleOutput,
    ScheduleRequest,
    get_schedule,
)
from switchboard_core.tools.search_notes import (
    SearchNotesOutput,
    SearchNotesRequest,
    search_notes,
)
from switchboard_core.tools.transfer import (
    TransferOutput,
    TransferRequest,
    transfer_to_human,
)
from switchboard_core.tools.visit_history import (
    VisitHistoryOutput,
    VisitHistoryRequest,
    get_visit_history,
)
from switchboard_core.tools.warranty_status import (
    WarrantyStatusOutput,
    WarrantyStatusRequest,
    get_warranty_status,
)
from switchboard_core.tools.web_search import (
    WebSearchOutput,
    WebSearchRequest,
    web_search,
)

#: Every read tool, keyed by the name `docs/AGENTS.md` gives it. The T4.0
#: client binds these and T3.5 exposes them; both look a tool up by the
#: name the model emitted, so a dict rather than a list.
READ_TOOLS = {
    "resolve_address": resolve_address,
    "resolve_customer": resolve_customer,
    "identify_caller_role": identify_caller_role,
    "get_visit_history": get_visit_history,
    "get_warranty_status": get_warranty_status,
    "get_customer_balance": get_customer_balance,
    "search_notes": search_notes,
    "get_schedule": get_schedule,
    "find_availability": find_availability,
    "web_search": web_search,
}

#: Every write tool. `agent` is "Dispatch" on all of them, and
#: `test_write_tools_are_dispatch_only.py` fails if that ever stops being
#: true or if one of these leaks into READ_TOOLS - CLAUDE.md hard rule 4 as
#: a test rather than as a convention.
WRITE_TOOLS = {
    "book_job": book_job,
    "move_job": move_job,
    "add_note": add_note,
}

#: `control`: changes call routing, writes an audit row, mutates no
#: customer record. Reachable from any agent by design - hard rule 4 is
#: scoped to customer-record writes, and forcing a caller through the
#: write-holding agent to reach a person would invert the boundary.
CONTROL_TOOLS = {
    "transfer_to_human": transfer_to_human,
}

__all__ = [
    "CONTROL_TOOLS",
    "READ_TOOLS",
    "WRITE_TOOLS",
    "AddNoteOutput",
    "AddNoteRequest",
    "AvailabilityOutput",
    "AvailabilityRequest",
    "BookJobOutput",
    "BookJobRequest",
    "CallerRole",
    "CallerRoleOutput",
    "CallerRoleRequest",
    "CanonicalId",
    "CustomerBalanceOutput",
    "CustomerBalanceRequest",
    "CustomerId",
    "InvalidEntityIdError",
    "JobId",
    "JobNotFoundError",
    "MoveJobOutput",
    "MoveJobRequest",
    "ResolveAddressOutput",
    "ResolveAddressRequest",
    "ResolveCustomerOutput",
    "ResolveCustomerRequest",
    "RetrievalUnavailableError",
    "ScheduleOutput",
    "ScheduleRequest",
    "SearchNotesOutput",
    "SearchNotesRequest",
    "ToolDomainError",
    "ToolError",
    "ToolResult",
    "TransferOutput",
    "TransferRequest",
    "VisitHistoryOutput",
    "VisitHistoryRequest",
    "WarrantyStatusOutput",
    "WarrantyStatusRequest",
    "WebSearchOutput",
    "WebSearchRequest",
    "WebSearchUnavailableError",
    "add_note",
    "book_job",
    "find_availability",
    "get_customer_balance",
    "get_schedule",
    "get_visit_history",
    "get_warranty_status",
    "identify_caller_role",
    "log_tool_call",
    "move_job",
    "resolve_address",
    "resolve_customer",
    "search_notes",
    "tool_call",
    "transfer_to_human",
    "web_search",
]
